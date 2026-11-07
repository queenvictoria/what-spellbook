"""Searching the vector index directly, for inspection and testing.

Two questions are easy to confuse, and this module is the second one:

* ``retrieval`` asks *what is legal for this character*, and answers only from an
  eligibility-filtered pool. The scenario narrows an already-legal list.
* This asks *what is in the index, and what does a query bring back*. It can surface a
  spell the character could never pick, on purpose - that is how you find out why a
  recommendation went missing.

Nothing in the recommender calls this. It is a diagnostic surface, exposed as
``GET /api/search`` and driven by the search screen, so a filter can be checked against
the index without generating a book and reading the answer for clues.

Three modes, because they fail differently and telling them apart is most of the work:

* ``vector`` - a similarity search, i.e. what the recommender itself does. Requires text
  to embed; the scores are Chroma distances, lower being closer.
* ``text`` - a substring scan over the chunk bodies. This is the mode that answers "which
  chunks mention X", which a vector search cannot. All words are required by default
  (``all_terms``), because a match on one common word is the noise this mode exists to cut
  through - but the strictness is the caller's to relax, and when the strict form finds
  nothing the result says so rather than looking like an empty index.
* ``hybrid`` - the vector candidates, re-ordered so hits containing the query's words come
  first. It is a ranking aid, not a retrieval algorithm: it cannot find a spell the
  embedding did not return.

Importing this module has no side effects and needs no network.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field

from . import spells

MODES = ("vector", "text", "hybrid")
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# What a search can be restricted to. ``all`` is the default because the diagnostic surface
# exists to show what is in the index, and hiding two thirds of it by default would make
# "why is this spell missing" unanswerable. The recommender is the opposite: it names
# ``spell`` explicitly, because a rule is not a legal pick.
DOC_TYPES = ("all", spells.DOC_TYPE_SPELL, spells.DOC_TYPE_ITEM, spells.DOC_TYPE_SRD)

# The index stores several chunks per spell, so a raw k of ``limit`` yields roughly
# ``limit / 2.35`` distinct spells. Vector mode asks for a wider pool than it returns so
# that collapsing chunks back into spells still fills the requested page.
CANDIDATE_FACTOR = 4
MAX_CANDIDATES = 400


def level_label(level: int | None) -> str:
    """How a spell level is written, in one place so every surface agrees.

    0 is a cantrip, not "Level 0", and the index stores -1 for the magic items that share
    the collection - which is "Not a spell" rather than a negative level.
    """
    if level is None or level < 0:
        return "Not a spell"
    return "Cantrip" if level == 0 else f"Level {level}"


@dataclass
class Hit:
    """One distinct spell, with the chunk that best matched.

    ``chunks`` is how many of that spell's chunks matched, not how many the spell has: in
    vector mode every returned chunk is a hit, and in text mode only chunks containing the
    words are. It is a signal about the query, not about the spell.
    """

    name: str
    level: int | None
    school: str | None
    classes: list[str]
    ritual: bool
    is_spell: bool
    filename: str
    text: str
    chunks: int = 1
    # Which kind of indexed text this is: "spell", "item" or "srd". Carried so a client can
    # tell a rule from a spell without inferring it from an empty school or a level of 0.
    doc_type: str = spells.DOC_TYPE_SPELL
    # For an SRD row, the document and heading it came from, so a hit can be opened as a
    # rule rather than shown as an orphaned paragraph.
    document: str | None = None
    slug: str | None = None
    # Chroma's distance for the best chunk, or None when the store cannot score (a minimal
    # test double exposes only a retriever). Lower is closer; it is not a percentage and
    # must not be shown as one - the scale depends on the embedding model.
    distance: float | None = None
    # How many of the query's words this spell's matching chunks contain.
    terms_matched: int = 0

    @property
    def level_label(self) -> str:
        # A rule is not a spell, so it has no level to report. Its ``level`` is 0 as a
        # placeholder, and calling that "Cantrip" would be a lie a client could not detect.
        if self.doc_type == spells.DOC_TYPE_SRD:
            return "Rule"
        return level_label(self.level)


@dataclass
class Facet:
    value: str
    count: int


@dataclass
class LevelFacet:
    level: int
    count: int

    @property
    def label(self) -> str:
        return level_label(self.level)


@dataclass
class Facets:
    """What the index holds, so a client can offer real filter values.

    Counted per spell rather than per chunk: the collection holds ~1280 chunks for 544
    spells, so counting rows would report every class two or three times over.
    """

    classes: list[Facet] = field(default_factory=list)
    schools: list[Facet] = field(default_factory=list)
    levels: list[LevelFacet] = field(default_factory=list)
    rituals: int = 0
    spells: int = 0
    chunks: int = 0
    # How many rows of each kind the collection holds, so a client can offer the doc-type
    # filter with real counts and a reader can see the rulebook is in there.
    doc_types: list[Facet] = field(default_factory=list)


@dataclass
class Result:
    """One search, with enough provenance to tell a filter problem from a query problem.

    ``where`` is the Chroma clause actually sent, echoed back because a filter that
    silently matches nothing is the commonest failure here and the clause is the fastest
    way to see why. ``total_matching`` counts the distinct spells the request's *criteria*
    admit - filters always, plus the words in text mode - so it says whether a filter is
    too narrow rather than whether the query was any good. A vector search has no
    threshold, so it cannot say how many spells are "relevant".
    """

    query: str
    mode: str
    limit: int
    offset: int = 0
    hits: list[Hit] = field(default_factory=list)
    total_matching: int = 0
    elapsed_ms: float = 0.0
    where: dict | None = None
    filters: dict = field(default_factory=dict)
    note: str | None = None


# --- reading the store ---
def _metadatas(db, where=None) -> list[dict]:
    payload = db.get(where=where, include=["metadatas"])
    return list(payload.get("metadatas") or [])


def _chunks(db, where=None) -> list[tuple[dict, str]]:
    """Every matching chunk's metadata and text.

    A store that cannot return documents yields an empty text per row rather than
    failing, so a filter can still be inspected when only metadata is available.
    """
    payload = db.get(where=where, include=["metadatas", "documents"])
    metadatas = payload.get("metadatas") or []
    documents = payload.get("documents") or []
    return [
        (metadata, documents[i] if i < len(documents) else "")
        for i, metadata in enumerate(metadatas)
    ]


def _distinct_spells(rows) -> list[dict]:
    """One row per document, first seen wins.

    The collection holds several chunks per spell, so any count taken over rows would
    report the same spell two or three times.

    The key includes ``doc_type`` because the three kinds of text share a namespace: an SRD
    section is named after its heading, and a heading can collide with a spell name - the
    SRD has a ``#### Fireball`` *and* the corpus has a Fireball spell. Keying on the name
    alone would fold the rule into the spell and report one fewer row than exists.

    For an SRD row the key is the *section*, not the heading text, because the SRD repeats
    headings: ``classes.md`` has six ``Level 1: Spellcasting`` sections, one per class, and
    keying on the text would report five of them as duplicates of the first.
    """
    seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        seen.setdefault(_document_key(row), row)
    return list(seen.values())


def _document_key(row: dict) -> tuple[str, str]:
    """What identifies one indexed document, for collapsing chunks into rows."""
    doc_type = str(row.get("doc_type") or spells.DOC_TYPE_SPELL)
    if doc_type == spells.DOC_TYPE_SRD:
        return (doc_type, f"{row.get('document') or ''}#{row.get('slug') or ''}")
    return (doc_type, str(row.get("spell_name") or row.get("filename") or ""))


def _as_level(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _hit(metadata: dict, *, text: str = "", distance: float | None = None) -> Hit:
    level = _as_level(metadata.get("level"))
    classes = [
        part.strip()
        for part in str(metadata.get("classes") or "").split(",")
        if part.strip()
    ]
    doc_type = str(metadata.get("doc_type") or "")
    if doc_type not in spells.DOC_TYPES:
        # An index written before ``doc_type`` existed. Everything in it was a spell or a
        # magic item, and ``is_spell`` is the only marker it carries - so it is read the
        # same way the old code read it rather than reported as an unknown type.
        doc_type = (spells.DOC_TYPE_SPELL if metadata.get("is_spell") is not False
                    else spells.DOC_TYPE_ITEM)
    return Hit(
        name=str(metadata.get("spell_name") or metadata.get("filename") or ""),
        # -1 is the index's marker for the magic items that share the collection, not a
        # level. It is reported as "no level" so a client never has to know the marker.
        level=level if level is not None and level >= 0 else None,
        school=str(metadata.get("school") or "") or None,
        classes=classes,
        ritual=bool(metadata.get("ritual")),
        # Absent metadata means an older index, where everything was a spell; only an
        # explicit False marks an item.
        is_spell=metadata.get("is_spell") is not False,
        filename=str(metadata.get("filename") or ""),
        text=text,
        distance=distance,
        doc_type=doc_type,
        document=str(metadata.get("document") or "") or None,
        slug=str(metadata.get("slug") or "") or None,
    )


# --- filters ---
def _class_clause(db, wanted) -> tuple[dict | None, bool]:
    """A clause matching any of ``wanted`` classes, and whether it can match nothing.

    Class lists are stored as one comma-joined string - ``"Bard, Cleric, Wizard"`` -
    because the index predates a list-valued field. Chroma's ``$contains`` does not match
    inside a metadata string (it returns nothing, silently), and ``$in`` compares the whole
    value, so ``{"classes": {"$in": ["Wizard"]}}`` misses the 863 chunks whose class list
    is ``"Sorcerer, Wizard"``. The only correct filter is an ``$or`` over the exact
    combinations that name the class.
    """
    wanted_folded = {str(name).strip().casefold() for name in wanted if str(name).strip()}
    if not wanted_folded:
        return None, False

    combos = sorted(
        {
            str(row.get("classes") or "")
            for row in _metadatas(db)
            if any(
                part.strip().casefold() in wanted_folded
                for part in str(row.get("classes") or "").split(",")
            )
        }
        - {""}
    )
    if not combos:
        # A filter that names a class the index never uses must match nothing. Dropping
        # the clause instead would quietly widen the search to the whole collection, which
        # is the one outcome a filter must never have.
        return None, True
    if len(combos) == 1:
        return {"classes": combos[0]}, False
    return {"$or": [{"classes": combo} for combo in combos]}, False


def _filters(*, classes, school, level_min, level_max, ritual, spells_only,
             doc_type="all") -> dict:
    return {
        "classes": [str(c) for c in classes],
        "school": school,
        "level_min": level_min,
        "level_max": level_max,
        "ritual": ritual,
        "spells_only": spells_only,
        "doc_type": doc_type,
    }


def _where(db, filters: dict) -> tuple[dict | None, bool]:
    """The Chroma clause for a filter set, and whether it is unsatisfiable."""
    clauses: list[dict] = []

    # ``doc_type`` supersedes ``spells_only`` when it is set to anything but ``all``: the
    # two are the same question asked at different resolutions, and honouring both would
    # make ``doc_type=srd`` with the default ``spells_only=true`` match nothing at all.
    doc_type = filters.get("doc_type") or "all"
    if doc_type != "all":
        clauses.append(spells.doc_type_filter(doc_type))
    elif filters["spells_only"]:
        clauses.append(spells.doc_type_filter(spells.DOC_TYPE_SPELL))

    class_clause, impossible = _class_clause(db, filters["classes"])
    if impossible:
        return None, True
    if class_clause:
        clauses.append(class_clause)

    if filters["school"]:
        clauses.append({"school": filters["school"]})
    if filters["level_min"] is not None:
        clauses.append({"level": {"$gte": filters["level_min"]}})
    if filters["level_max"] is not None:
        clauses.append({"level": {"$lte": filters["level_max"]}})
    if filters["ritual"] is not None:
        clauses.append({"ritual": bool(filters["ritual"])})

    return spells.build_where(*clauses), False


# --- search ---
def _validate(mode: str, limit: int, offset: int, level_min, level_max,
              doc_type: str = "all") -> None:
    if mode not in MODES:
        raise ValueError(f"Unknown search mode '{mode}'. Use one of {', '.join(MODES)}.")
    if doc_type not in DOC_TYPES:
        raise ValueError(
            f"Unknown doc_type '{doc_type}'. Use one of {', '.join(DOC_TYPES)}."
        )
    if not 1 <= int(limit) <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}.")
    if int(offset) < 0:
        raise ValueError("offset must not be negative.")
    for name, value in (("level_min", level_min), ("level_max", level_max)):
        if value is not None and not 0 <= int(value) <= 9:
            raise ValueError(f"{name} must be between 0 and 9.")
    if level_min is not None and level_max is not None and int(level_min) > int(level_max):
        raise ValueError("level_min is greater than level_max.")


def _terms(query: str) -> list[str]:
    """The words a text match requires, case-folded.

    All of them, not any: "grappled ally" should show chunks that mention both, because
    a chunk matching only one is the noise this mode exists to cut through.
    """
    return [term for term in re.split(r"\s+", query.casefold()) if term]


def _collapse(scored, terms) -> list[Hit]:
    """Fold the many chunks of one document into one hit, keeping its best chunk.

    ``scored`` is ``(metadata, text, distance)``. The best chunk is the nearest one in
    vector mode and the first seen otherwise; either way its text is what the hit shows,
    because that is the chunk the index matched.

    Keyed the same way ``_distinct_spells`` keys a row, so a hit and a count agree about
    what one document is. Keying on the name alone would merge the SRD's six
    ``Level 1: Spellcasting`` sections into one hit and silently drop five classes.
    """
    hits: dict[tuple[str, str], Hit] = {}
    matched: dict[tuple[str, str], set[str]] = {}

    for metadata, text, distance in scored:
        hit = _hit(metadata, text=text, distance=distance)
        key = _document_key(metadata)
        folded = text.casefold()
        matched.setdefault(key, set()).update(t for t in terms if t in folded)

        existing = hits.get(key)
        if existing is None:
            hits[key] = hit
            continue
        existing.chunks += 1
        if _closer(hit.distance, existing.distance):
            existing.distance = hit.distance
            existing.text = hit.text

    for key, hit in hits.items():
        hit.terms_matched = len(matched.get(key, ()))
    return list(hits.values())


def _closer(candidate: float | None, current: float | None) -> bool:
    """Whether ``candidate`` is a better distance than ``current``.

    An unscored store reports None for both, in which case the first chunk stays - which
    is the order the retriever returned, and the only ordering available.
    """
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate < current


def _vector_chunks(db, query: str, where: dict | None, k: int):
    """Similarity search, tolerating a store that cannot score.

    Mirrors ``retrieval.retrieve``: a minimal test double implements only
    ``as_retriever()``, so a missing ``similarity_search_with_score`` falls back to the
    retriever path and the hits are returned unscored rather than not at all.
    """
    try:
        results = db.similarity_search_with_score(query, k=k, filter=where)
    except (AttributeError, TypeError):
        kwargs = {"k": k}
        if where:
            kwargs["filter"] = where
        documents = db.as_retriever(search_kwargs=kwargs).invoke(query)
        return [(doc.metadata, doc.page_content, None) for doc in documents]
    return [
        (doc.metadata, doc.page_content, float(score)) for doc, score in results
    ]


def search(db, query: str = "", *, mode: str = "vector", limit: int = DEFAULT_LIMIT,
           offset: int = 0, classes=(), school: str | None = None,
           level_min: int | None = None, level_max: int | None = None,
           ritual: bool | None = None, spells_only: bool = True,
           all_terms: bool = True, doc_type: str = "all") -> Result:
    """Search the index, returning distinct documents rather than chunks.

    ``mode='text'`` accepts an empty query, which lists everything the filters admit -
    the way to check that a filter selects the spells you think it does. ``offset`` pages
    through the ordered hits; there is no cursor, because the ordering is total and stable
    for a given query so a page number is enough.

    ``doc_type`` narrows to one kind of indexed text - ``spell``, ``item`` or ``srd`` - and
    defaults to ``all`` so the diagnostic surface shows the whole collection. It takes
    precedence over ``spells_only``, which is the same question at a coarser resolution.
    """
    started = time.perf_counter()
    query = " ".join(str(query or "").split())
    _validate(mode, limit, offset, level_min, level_max, doc_type)

    if mode in ("vector", "hybrid") and not query:
        raise ValueError(
            "A vector search needs some text to embed. Use mode=text to list what the "
            "filters admit."
        )

    filters = _filters(
        classes=classes, school=school or None, level_min=level_min,
        level_max=level_max, ritual=ritual, spells_only=spells_only, doc_type=doc_type,
    )
    where, impossible = _where(db, filters)
    terms = _terms(query)
    note = None

    if impossible:
        return Result(
            query=query, mode=mode, limit=limit, offset=offset, where=None,
            filters=filters,
            note="No spell in the index lists that class, so nothing can match.",
            elapsed_ms=_elapsed(started),
        )

    if mode == "text":
        collapsed = _collapse(
            [(metadata, text, None) for metadata, text in _chunks(db, where)], terms
        )
        hits = collapsed
        if terms:
            wanted = len(terms) if all_terms else 1
            hits = [hit for hit in collapsed if hit.terms_matched >= wanted]
        if not hits and terms and len(terms) > 1 and all_terms:
            # "All the words" is an AND, and a chunk in this corpus is ~1200 characters,
            # so two words can easily both be present in a spell yet never in the same
            # chunk. Saying so beats returning an empty page that reads as a broken index.
            any_term = [hit for hit in collapsed if hit.terms_matched > 0]
            if any_term:
                note = (
                    f"No chunk contains all {len(terms)} words. "
                    f"{len(any_term)} spell(s) contain at least one - retry with "
                    "all_terms=false to see them."
                )
        hits.sort(key=lambda hit: (-hit.terms_matched, hit.name.casefold()))
        total = len(hits)
        hits = hits[offset:offset + limit]
    else:
        candidates = min((offset + limit) * CANDIDATE_FACTOR, MAX_CANDIDATES)
        scored = _vector_chunks(db, query, where, candidates)
        hits = _collapse(scored, terms)
        if mode == "hybrid":
            # Words first, then distance: the point of the mode is to see what a keyword
            # would have promoted, so the ordering must not be distance-first.
            hits.sort(
                key=lambda hit: (
                    -hit.terms_matched,
                    hit.distance if hit.distance is not None else float("inf"),
                    hit.name.casefold(),
                )
            )
        else:
            hits.sort(
                key=lambda hit: (
                    hit.distance if hit.distance is not None else float("inf"),
                    hit.name.casefold(),
                )
            )
        # A vector search has no relevance threshold, so "how many matched" is really "how
        # many the filter admits" - and that is the useful number here, because it says
        # whether the filter is too narrow.
        total = len(_distinct_spells(_metadatas(db, where)))
        if len(hits) >= candidates:
            note = (
                f"Results are capped at {candidates} candidate chunk(s); ranking beyond "
                "that was not considered. Raise limit or narrow the filters."
            )
        hits = hits[offset:offset + limit]

    return Result(
        query=query, mode=mode, limit=limit, offset=offset, hits=hits,
        total_matching=total, elapsed_ms=_elapsed(started), where=where,
        filters=filters, note=note,
    )


def facets(db) -> Facets:
    """Every value the filters accept, with how many documents carry it.

    Counted over the whole collection, including the SRD rows. The class, school and level
    facets are therefore spell facets - a rule carries none of them - while ``doc_types``
    is what says how much of the collection is rulebook.
    """
    rows = _metadatas(db)
    distinct = _distinct_spells(rows)

    classes: Counter[str] = Counter()
    for row in distinct:
        for part in str(row.get("classes") or "").split(","):
            name = part.strip()
            if name:
                classes[name] += 1

    schools: Counter[str] = Counter(
        str(row.get("school")) for row in distinct if row.get("school")
    )
    # SRD rows carry level 0 as a placeholder, so they are excluded here rather than
    # reported as 1280 cantrips. The filter is on the row itself, not on a leaked loop
    # variable - a comprehension's ``if`` clause runs in the enclosing scope, so referring
    # to ``row`` there would silently test whichever row the loop above finished on.
    levels: Counter[int] = Counter(
        level for level, doc_type in (
            (_as_level(row.get("level")), row.get("doc_type")) for row in distinct
        )
        if level is not None and doc_type != spells.DOC_TYPE_SRD
    )
    doc_types: Counter[str] = Counter(
        str(row.get("doc_type") or spells.DOC_TYPE_SPELL) for row in distinct
    )

    return Facets(
        classes=[Facet(value, count) for value, count in sorted(classes.items())],
        schools=[Facet(value, count) for value, count in sorted(schools.items())],
        levels=[
            LevelFacet(level, count) for level, count in sorted(levels.items())
        ],
        rituals=sum(1 for row in distinct if row.get("ritual")),
        spells=sum(1 for row in distinct
                   if row.get("doc_type") == spells.DOC_TYPE_SPELL
                   or (row.get("doc_type") is None and row.get("is_spell") is not False)),
        chunks=len(rows),
        doc_types=[Facet(value, count) for value, count in sorted(doc_types.items())],
    )


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)