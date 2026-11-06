"""Local result cache: a shared run file plus one file per generated book.

A run is written under ``.cache/`` so a recommendation can be revisited later, and so
a repeat of the same scenario is served without a model call. The point of the store
is outcome ratings: after the scenario is played, the book that was used can be scored.

Layout::

    .cache/
      <character>/
        <level>-<party>-<dbversion>-<scenario>/
          run.json
          1-illuminated-kill-zone.json
          2-ambush-breaker.json
          3-bridge-hold-defense.json

The directory path *is* the key (character, level, party, database version, scenario).
``run.json`` holds what is identical across the books - the sheet, resolved rule
context, eligible pool, the assembled prompt and the raw response - so it is stored
once instead of copied into each book. Each book file then holds only its own markdown
and picks, because a book is the unit of rating and must be scoreable independently.

Nothing here imports LangChain or Chroma, and every function takes an explicit
``cache_dir`` so tests never write to the working tree.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE_DIR = ".cache"

# The shared half of a run lives here; each book gets its own numbered file beside it.
RUN_FILENAME = "run.json"

# Bump when the entry shape changes in a way an old entry cannot survive - a renamed
# field, a changed meaning, a new required key. An *added* optional key does not need a
# bump: readers already treat a missing key as "no data", so bumping would throw away
# every cached run (and every rating) to gain nothing.
SCHEMA_VERSION = 2

_WORD = re.compile(r"[a-z0-9]+")
_BOOK_HEADING = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?\*{0,2}\s*Book\s*(\d+)\b(?P<rest>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)

# A heading is short and names a theme. The model's trailing summary section writes
# lines like '**Book 1 pairs with:** Hex, Hypnotic Pattern, ...' which would otherwise
# be parsed as extra books, so reject anything prose-like.
_MAX_HEADING = 90
_PROSE_AFTER_LABEL = re.compile(
    r"^\s*:?\s*(pairs?|combos?|is|are|has|have|contains|includes|works|use[sd]?"
    r"|should|can|will|and|then|gives?|adds?|plus)\b",
    re.IGNORECASE,
)


def _is_book_heading(line: str) -> bool:
    """True when a line is a book title rather than a sentence that mentions one."""
    if len(line) > _MAX_HEADING:
        return False
    match = _BOOK_HEADING.match(line)
    if not match:
        return False
    return not _PROSE_AFTER_LABEL.match(match.group("rest").replace("*", ""))


def now() -> str:
    """UTC timestamp, second precision, always with a timezone."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str, *, max_length: int = 60) -> str:
    """Filesystem-safe slug; empty input becomes 'untitled'."""
    words = _WORD.findall(str(text).lower())
    slug = "-".join(words)[:max_length].strip("-")
    return slug or "untitled"


def scenario_fingerprint(scenario: str) -> str:
    """Server-stable short hash of a scenario.

    The scenario text is far too long (and too punctuation-heavy) to be a directory
    name, but it has to be part of the key, so hash it and keep a short prefix that
    is recognisable at a glance.
    """
    normalised = " ".join(str(scenario).split()).lower()
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:12]
    return digest


def character_fingerprint(sheet) -> str:
    """Stable hash of a character sheet.

    Name and level are not enough to decide whether a cached run still applies: a
    sheet edited between runs (new spells prepared, a different subclass, a swapped
    magic item) produces a different recommendation at the same level. Hashing the
    whole sheet catches that, and it is stored in the entry rather than put in the
    path, so a re-run overwrites in place instead of littering directories.
    """
    canonical = json.dumps(sheet, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def key_parts(*, character: str, level, party, db_version, scenario: str,
              books: int | None = None) -> dict:
    """The cache key: everything that would change the recommendation.

    ``books`` belongs here for the same reason ``db_version`` does: asking for two
    loadouts is a different request from asking for three. Without it a stored run
    would be replayed for a different request and the caller would silently receive the
    wrong number of books.
    """
    return {
        "character": _slug(character),
        "level": level,
        "party": _slug(", ".join(party) if isinstance(party, (list, tuple, set)) else party),
        "db_version": db_version,
        "scenario": scenario_fingerprint(scenario),
        "books": books,
    }


def key_dir(key: dict) -> str:
    """Directory name for a key: level, party, database version, book count, hash."""
    return "-".join(
        str(part) for part in (
            key["level"], key["party"], key["db_version"],
            key.get("books"), key["scenario"],
        )
    )


def entry_dir(cache_dir, key: dict) -> Path:
    """``<cache_dir>/<character>/<key>``."""
    return Path(cache_dir) / key["character"] / key_dir(key)


def book_slug(index: int, name: str) -> str:
    """Filename stem for one book, e.g. ``1-ambush-and-control``."""
    return f"{index}-{_slug(name, max_length=40)}"


# The delimited format. `=== BOOK 3 ===` on its own line is the only thing that separates
# books, and it cannot collide with prose: the model's trailing summary writes
# `**Book 1 pairs with:** ...`, which is a sentence, not a delimiter.
_BOOK_MARK = re.compile(r"(?m)^[ \t]*={2,}\s*BOOK\s*(\d+)\s*={2,}[ \t]*$", re.IGNORECASE)

# Any markdown heading, used to find the *last* one in a legacy answer.
_MD_HEADING = re.compile(r"(?m)^[ \t]*#{1,4}[ \t]*[^\n]*$")

# A heading the model wrote for its trailing summary rather than for a book. The vocabulary
# is deliberately narrow: it must name pairings, invocations or the existing kit, because a
# book heading never does and a book's own subheading might.
_SUMMARY_HEADING = re.compile(
    r"(?i)^[ \t]*#{1,4}[ \t]*(?:\d+[.)][ \t]*)?(?=[^\n]*(?:pair|invocation|existing))[^\n]*$")

# The other sections of the same format, which bound a book from the outside.
_SECTION_MARK = re.compile(
    r"(?m)^[ \t]*={2,}\s*(?:PREAMBLE|PAIRINGS|SUMMARY)\s*={2,}[ \t]*$", re.IGNORECASE)
_FIELD = re.compile(r"^[ \t]*(Title|Cantrips|Rituals)[ \t]*:[ \t]*(.*)$", re.IGNORECASE)
_HOW_TO = re.compile(r"^[ \t]*How to use[ \t]*:?[ \t]*$", re.IGNORECASE)
_SUMMARY_LABEL = re.compile(r"(?m)^[ \t]*={2,}\s*(PAIRINGS|SUMMARY)\s*={2,}[ \t]*$",
                            re.IGNORECASE)


def split_answer(answer: str) -> dict:
    """Split a model answer into ``{"preamble", "books", "pairings"}``.

    Two formats are understood, and the delimited one is tried first:

    * **Delimited** - ``=== BOOK n ===`` sections carrying ``Title:``, ``Cantrips:`` and
      ``Rituals:`` as fields, with ``=== PAIRINGS ===`` after the last book. The
      structure is explicit, so nothing has to be inferred from prose.
    * **Legacy** - a ``**Book 1 — Name**`` heading followed by a prose pick list, which is
      what every run before the format change contains. Kept because the answers already
      in the cache are real records with real ratings attached, and a parser that refuses
      them would make every stored run unreadable.

    The distinction matters more than it looks. The legacy format's headings and the
    model's trailing summary share a shape - the summary writes ``**Book 1 pairs with:**``
    - so separating them needs a heuristic that guesses from the words after the label
    whether a line is a title or a sentence. The delimited format removes that collision:
    a delimiter is never prose, so a summary cannot be mistaken for a book.
    """
    text = str(answer or "")
    if not text.strip():
        return {"preamble": "", "books": [], "pairings": ""}

    marks = list(_BOOK_MARK.finditer(text))
    if not marks:
        return _legacy_split(text)

    preamble = text[: marks[0].start()]
    # A book ends at the *next marker of any kind*, not just the next book. Bounding on book
    # marks alone let the last book run on to the end of the answer, so `=== PAIRINGS ===`
    # and the whole summary landed inside it - which is the same defect the delimited format
    # exists to fix, reintroduced by the parser reading it.
    boundaries = sorted(
        [m.start() for m in marks]
        + [m.start() for m in _SECTION_MARK.finditer(text)]
        + [len(text)]
    )
    books = []
    for mark in marks:
        end = next(bound for bound in boundaries if bound > mark.end())
        books.append(_book_from_section(int(mark.group(1)), text[mark.end(): end]))

    return {
        "preamble": _section_body(preamble, "PREAMBLE"),
        "books": books,
        "pairings": _after_summary(text),
    }


def _section_body(text: str, name: str) -> str:
    """The prose of a named section, or ``text`` itself when it is not delimited.

    The preamble arrives in two shapes and both are ordinary: the model may write the
    sample's ``=== PREAMBLE ===`` marker, or simply begin with a sentence before the first
    book. Treating the bare case as the preamble means a model that skips one label still
    has its reasoning read.
    """
    match = re.search(rf"(?im)^[ \t]*={{2,}}[ \t]*{name}[ \t]*={{2,}}[ \t]*$", text)
    if not match:
        return _strip_delimiters(text)
    rest = text[match.end():]
    nxt = _SECTION_MARK.search(rest)
    if nxt:
        rest = rest[: nxt.start()]
    return _strip_delimiters(rest)


def _after_summary(text: str) -> str:
    """Everything after the pairings marker, up to the next section marker.

    A run that never writes the marker has its summary as the tail of the last book, which
    is exactly the defect the delimited format exists to fix - so this returns an empty
    string rather than guessing, and the book keeps whatever it was given.
    """
    match = _SUMMARY_LABEL.search(text)
    if not match:
        return ""
    rest = text[match.end():]
    # One book is normally the last section and so is the *last* marker - but a model that
    # puts the summary in the middle would otherwise swallow every book after it.
    nxt = _SECTION_MARK.search(rest)
    while nxt and re.match(r"(?i)={2,}\s*(?:PAIRINGS|SUMMARY)\s*={2,}", nxt.group(0)):
        rest = rest[nxt.end():]
        nxt = _SECTION_MARK.search(rest)
    if nxt:
        rest = rest[: nxt.start()]
    return _strip_delimiters(rest)


def _strip_delimiters(text: str) -> str:
    """Remove any section markers left in a fragment, so they never reach the reader."""
    return _SECTION_MARK.sub("", text).strip()


def _book_from_section(index: int, body: str) -> dict:
    """One delimited book: its three fields, and the prose after ``How to use:``.

    The fields are read as data, so the *prose* is what remains. That is the same deletion
    the reader used to need as a display hack - the panel renders the name in its header
    and the picks as linked badges - except it now happens once, on the way in, instead of
    on every render.
    """
    title, cantrips, rituals = "", [], []
    lines = body.split("\n")
    cursor = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            cursor = i + 1
            continue
        if _HOW_TO.match(stripped):
            cursor = i + 1
            break
        field = _FIELD.match(line)
        if not field:
            break
        name, value = field.group(1).lower(), field.group(2).strip()
        if name == "title":
            title = value.strip("*_ ")
        elif name == "cantrips":
            cantrips = _split_names(value)
        else:
            rituals = _split_names(value)
        cursor = i + 1

    return {
        "index": index,
        "name": title or f"Book {index}",
        # No title: the caller renders `book.name` in the card header, so repeating it in
        # the prose would show it twice - which is the duplication this format removes.
        "text": "\n".join(lines[cursor:]).strip(),
        "picks": {"cantrips": cantrips, "rituals": rituals},
    }


def _split_names(value: str) -> list[str]:
    """A comma-separated pick list, cleaned of the decoration a model may still add.

    Tolerant on purpose: the prompt asks for bare names, but a model that writes
    ``Light (Cantrip)`` or ``**Light**`` is still naming a legal pick, and refusing to read
    it would report a legal book as broken.

    The annotation pattern is the spells parser's own, imported rather than copied: it is
    already the thing that decides what counts as an annotation, and a second copy would
    eventually disagree about ``Light (Cantrip; Evocation; Bard)``.
    """
    from . import spells

    value = spells._ANNOTATION_SPAN.sub("", value)
    names = []
    for chunk in re.split(r"\s*[,;]\s*", value):
        name = chunk.strip().strip("*_` ")
        name = re.sub(r"^\d+[.)]\s*", "", name)
        if name:
            names.append(name)
    return names


def _legacy_split(answer: str) -> dict:
    """Parse the pre-delimiter format, which every stored run still uses.

    Kept because those answers are real records with real ratings attached, and the
    headings the model wrote are the only structure they have. The heuristic that separates
    a book heading from the summary's ``**Book 1 pairs with:**`` lives in
    :func:`_is_book_heading` and is not needed by the delimited path at all.

    The pairing summary is recovered only when the model gave it a *markdown heading* of its
    own, which it did in 7 of the 12 stored runs (``## 4. Existing spells/features and
    invocations that pair with each book``). Without one it is ordinary prose at the end of
    the last book and cannot be told apart from that book's own text - which is the defect
    the delimited format fixes - so it stays where it was found.

    A bolded label (``**4. Pairings and invocations**``) is deliberately *not* accepted, even
    though one stored run uses it. The vocabulary that identifies a summary - "pair",
    "invocation", "existing" - also appears in a book's own prose, and measured against the
    stored runs the bold pattern matched ``**Book 1 - Rust-Monster Triage / Armor Repair**``
    on the "pair" inside "Repair". Truncating a real book to recover one summary is the worse
    trade, and the delimited format makes the question moot for every future run.
    """
    matches = [m for m in _BOOK_HEADING.finditer(answer) if _is_book_heading(m.group(0))]
    books = []
    for position, match in enumerate(matches):
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(answer)
        section = answer[start:end].strip()
        books.append({
            "index": int(match.group(1)),
            "name": book_name(section),
            "text": section,
            "picks": parse_picks(section),
        })

    # A trailing summary can push a real book's text into a sibling's section; keep the
    # first occurrence of each number so 'Book 3' is not reported twice.
    seen: set[int] = set()
    deduped = []
    for book in books:
        if book["index"] in seen:
            continue
        seen.add(book["index"])
        deduped.append(book)

    if not deduped:
        text = answer.strip()
        books = [{"index": 1, "name": "Untitled", "text": text, "picks": parse_picks(text)}] \
            if text else []
        return {"preamble": "", "books": books, "pairings": ""}

    pairings = ""
    if matches:
        heading = _legacy_summary_heading(answer, matches[-1].start())
        if heading is not None:
            # The heading is the label, so it is cut from the book but not shown in the
            # pairings - the card already has a title.
            pairings = answer[heading.end():].strip()
            last = deduped[-1]
            last["text"] = answer[matches[-1].start():heading.start()].strip()
            last["picks"] = parse_picks(last["text"])

    return {"preamble": "", "books": deduped, "pairings": pairings}


def _legacy_summary_heading(answer: str, last_book_start: int) -> re.Match | None:
    """The heading a legacy answer gave its trailing summary, or ``None`` when it gave none.

    The summary is the *trailing* section, so it is only a candidate when it is the last
    heading in the answer and it comes after the last book. Requiring both is what keeps a
    subheading inside a book's own prose from truncating that book.
    """
    last_heading = None
    for heading in _MD_HEADING.finditer(answer):
        last_heading = heading
    if (last_heading is None or last_heading.start() <= last_book_start
            or not _SUMMARY_HEADING.match(last_heading.group(0))):
        return None
    return last_heading


def legacy_summary_heading(answer: str) -> re.Match | None:
    """The heading a legacy answer gave its trailing summary, or ``None`` when it gave none.

    Public because the read path needs it: a run stored before the delimited format has its
    summary inside its last book's *recorded* text, and that text is not re-cut on read, so
    the summary has to be trimmed from it there instead. Sharing this with the parser is what
    stops the summary appearing twice - once as a book's text and once as the pairings.
    """
    matches = [m for m in _BOOK_HEADING.finditer(answer) if _is_book_heading(m.group(0))]
    if not matches:
        return None
    return _legacy_summary_heading(answer, matches[-1].start())


def split_books(answer: str) -> list[dict]:
    """The per-book sections of a model answer, in order.

    Kept as the narrow accessor for the callers that only want the books (validation,
    prompt checks). ``split_answer`` is the full split and the only parser - this delegates
    so the two can never disagree about where one book ends.
    """
    return split_answer(answer)["books"]


def book_name(section: str) -> str:
    """Best-effort display name for a book section.

    Models head these inconsistently - quotes, a colon, an em dash, or nothing - so
    the label is taken from whichever separator is present. A bare 'Book 1' heading
    with no theme is not a name, so it falls back to 'Untitled'.
    """
    heading = section.splitlines()[0] if section.splitlines() else ""
    quoted = re.search(r"[\"'\u201c\u2018]([^\"'\u201d\u2019]{2,60})[\"'\u201d\u2019]", heading)
    if quoted:
        return quoted.group(1).strip()

    # 'Book 1: Theme', 'Book 1 - Theme', 'Book 1 — Theme', 'Book 1 Theme'.
    after_label = re.sub(r"^[\s#*]*\**\s*Book\s*\d+\s*\**\s*[-:\u2013\u2014]?\s*", "", heading)
    name = after_label.strip(" *#`_").strip()
    if name and not name.lower().startswith("book"):
        return name
    return "Untitled"


def parse_picks(section: str) -> dict:
    """Extract the cantrip and ritual picks from one book section.

    Delegates to ``spells._book_picks`` rather than re-implementing the parse. The
    cached picks and the legality check must agree about what was chosen: if they
    diverge, a book can be recorded as legal and validated as illegal (or worse, an
    unreadable answer passes both). Imported here rather than at module scope so this
    stays importable without the parsing layer.
    """
    from . import spells

    return spells._book_picks(section)


def save_run(
    *,
    answer: str,
    cache_dir=DEFAULT_CACHE_DIR,
    character: str,
    level,
    party,
    db_version,
    scenario: str,
    input_data: dict | None = None,
    context: dict | None = None,
    prompts: dict | None = None,
    model: str | None = None,
    character_fingerprint: str | None = None,
    timings: dict | None = None,
    book_count: int | None = None,
) -> list[Path]:
    """Write a run to the cache: one shared file plus one file per book.

    The prompt, sheet and pool are identical for all the books, so storing them per
    book copied ~35KB each time. They live once in ``run.json``; each book file holds
    only what is specific to that book.

    A book file is the unit of rating, so its rating is written to its own file and a
    regeneration never disturbs a sibling's rating. Returns the paths written.
    """
    parts = key_parts(
        character=character, level=level, party=party, db_version=db_version,
        scenario=scenario, books=book_count,
    )
    directory = entry_dir(cache_dir, parts)
    split = split_answer(answer)
    books = split["books"]
    directory.mkdir(parents=True, exist_ok=True)

    run_path = directory / RUN_FILENAME
    previous_run = _read(run_path)
    run = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "key": {
            **parts,
            "scenario_text": scenario.strip(),
            "character_fingerprint": character_fingerprint,
        },
        "input": input_data or {},
        "context": context or {},
        "prompt": prompts or {},
        "response": answer,
        # How many book files were written, recorded here rather than only in the key. The
        # key carries it too when the caller supplied one, but a run saved without it had no
        # record of how many books to expect - so a book deleted from the end of the set
        # looked complete, and the reader was shown fewer books than the model produced.
        "book_count": len(books),
        # The pairing summary, split out of the books at write time. Stored rather than
        # re-derived because it is *part of the answer*, not a view of it: it names the
        # prepared spells and invocations that pair with each book, and in the old format it
        # was indistinguishable from the last book's prose, so reading it back would be
        # guesswork.
        "pairings": split["pairings"],
        "preamble": split["preamble"],
        "model": model,
        # Per-phase wall-clock breakdown, so slow runs can be averaged and attributed.
        "timings": timings or {},
    }
    run_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

    written = [run_path]
    # A rating belongs to a book *slot* (1st, 2nd, 3rd), not to its generated name:
    # a regeneration almost always renames the books, and matching on the name would
    # silently drop every rating on the next run.
    previous = _ratings_by_slot(directory)

    current_names = set()
    for book in books:
        slug = f"{book['index']}-{_slug(book['name'], max_length=40)}"
        current_names.add(f"{slug}.json")
        path = directory / f"{slug}.json"
        carried = _read(path).get("rating") or previous.get(book["index"])
        entry = {
            "schema_version": SCHEMA_VERSION,
            "run": RUN_FILENAME,
            "key": run["key"],
            "output": {
                "book_index": book["index"],
                "book_name": book["name"],
                # The prose only. The title and the pick lists are their own fields now, so
                # storing them inside the text as well would be the duplication this format
                # removes - and it is what forced the front end to strip them back out.
                "text": book["text"],
                "picks": book["picks"],
            },
            # A rating is human effort and is never silently discarded. It is carried
            # forward so the user can see it and judge whether it still applies.
            "rating": carried or _empty_rating(),
        }
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)

    # A rename from a regeneration would otherwise leave an orphan book in the
    # directory, which find_run would count as a full set.
    for stale in directory.glob("*.json"):
        if stale.name not in current_names and stale.name != RUN_FILENAME:
            stale.unlink()
    return written


def _ratings_by_slot(directory: Path) -> dict[int, dict]:
    """Existing ratings keyed by book index, for carrying across a regeneration."""
    ratings: dict[int, dict] = {}
    for path in directory.glob("*.json"):
        if path.name == RUN_FILENAME:
            continue
        entry = _read(path)
        rating = entry.get("rating") or {}
        index = (entry.get("output") or {}).get("book_index")
        if index is not None and rating.get("score") is not None:
            ratings[index] = rating
    return ratings


def _empty_rating() -> dict:
    return {"score": None, "rated_at": None, "notes": None, "outcome": None}


def find_run(
    *,
    cache_dir=DEFAULT_CACHE_DIR,
    character: str,
    level,
    party,
    db_version,
    scenario: str,
    character_fingerprint: str | None = None,
    book_count: int | None = None,
) -> dict | None:
    """Return ``{"run": ..., "books": [...]}`` for these exact inputs, or None.

    This is the read side of the cache. A hit requires the whole key to match *and*
    the left character fingerprint, so editing the sheet between runs misses instead
    of replaying advice for a character that no longer exists.
    """
    parts = key_parts(
        character=character, level=level, party=party, db_version=db_version,
        scenario=scenario, books=book_count,
    )
    directory = entry_dir(cache_dir, parts)
    if not directory.is_dir():
        return None

    run = _read(directory / RUN_FILENAME)
    if not run or run.get("response") is None:
        return None
    if run.get("schema_version") != SCHEMA_VERSION:
        return None
    stored = (run.get("key") or {}).get("character_fingerprint")
    if character_fingerprint is not None and stored != character_fingerprint:
        return None

    books = []
    for path in directory.glob("*.json"):
        if path.name == RUN_FILENAME:
            continue
        book = _read(path)
        if not book or book.get("output") is None:
            continue
        book["_path"] = str(path)
        books.append(book)

    # A partial set is a miss: half a cache would show the user fewer books than the
    # model produced, which is worse than regenerating.
    #
    # The expected count comes from the run's own key, not from re-parsing the stored
    # response. The book files *are* the written record, so re-deriving them on every read
    # meant a parser change could retroactively invalidate runs that were stored correctly -
    # and it was the only place a read did any parsing at all.
    indices = sorted((b.get("output") or {}).get("book_index") or 0 for b in books)
    expected = run.get("book_count")
    if expected is None:
        expected = (run.get("key") or {}).get("books")
    # A set is complete when its slots are `1..n` with nothing missing and nothing extra.
    # Contiguity is what catches a book deleted from the middle or the front - the case a
    # recorded count cannot see on its own, because the count has to be recorded to be
    # checked and a run stored before that key existed has no count at all.
    contiguous = indices == list(range(1, len(indices) + 1))
    if not books or not contiguous or (expected is not None and len(books) != expected):
        return None

    books.sort(key=lambda b: b.get("output", {}).get("book_index", 0))
    run["_path"] = str(directory / RUN_FILENAME)
    return {"run": run, "books": books}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_entries(cache_dir=DEFAULT_CACHE_DIR, *, character: str | None = None) -> list[Path]:
    """List cached *book* files, newest first; optionally filtered to one character.

    The shared ``run.json`` is excluded: it has no book output and no rating, so it
    would be noise in a listing or a rating target.
    """
    root = Path(cache_dir)
    if not root.is_dir():
        return []
    pattern = f"{_slug(character)}/*/*.json" if character else "*/*/*.json"
    paths = [p for p in root.glob(pattern) if p.name != RUN_FILENAME]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def load_runs(cache_dir=DEFAULT_CACHE_DIR, *, character: str | None = None) -> list[dict]:
    """Every cached run, newest first, as ``{path, key, timings, book_count, ...}``.

    ``load_entries`` lists *books*, which is the unit of rating; this lists *runs*,
    which is the unit of reading - a scenario's books taken together. Reopening a
    stored recommendation needs the run, because the books only make sense beside the
    scenario and sheet that produced them.

    A run whose ``run.json`` is missing or unreadable is skipped rather than reported
    as an empty entry.
    """
    root = Path(cache_dir)
    if not root.is_dir():
        return []
    pattern = f"{_slug(character)}/*/{RUN_FILENAME}" if character else f"*/*/{RUN_FILENAME}"

    runs = []
    for path in root.glob(pattern):
        data = _read(path)
        if not data or data.get("response") is None:
            continue
        key = data.get("key") or {}
        books = [
            p for p in path.parent.glob("*.json")
            if p.name != RUN_FILENAME and (_read(p).get("output") or {}).get("book_name")
        ]
        runs.append({
            "path": str(path),
            "directory": str(path.parent),
            "key": key,
            "scenario": key.get("scenario_text", ""),
            "character": key.get("character"),
            "level": key.get("level"),
            "created_at": data.get("created_at"),
            "model": data.get("model"),
            "timings": data.get("timings") or {},
            "book_count": len(books),
            "book_names": [
                (_read(p).get("output") or {}).get("book_name") for p in sorted(books)
            ],
        })
    return sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True)


def find_run_dir(reference: str, cache_dir=DEFAULT_CACHE_DIR,
                 *, character: str | None = None) -> Path | None:
    """Resolve a reference from ``/history`` to the run directory it names.

    Accepts an explicit path, a run directory, a full or trailing scenario hash, or a
    distinctive fragment of the scenario text - so a number from the listing is enough.
    """
    candidate = Path(reference)
    if candidate.is_dir() and (candidate / RUN_FILENAME).is_file():
        return candidate
    if candidate.is_file() and candidate.name == RUN_FILENAME:
        return candidate.parent

    runs = load_runs(cache_dir, character=character)
    if not runs:
        return None

    needle = reference.strip().lower().replace("\\", "/")
    if not needle:
        return None

    for run in runs:
        directory = run["directory"]
        if str(directory).lower().endswith(needle):
            return Path(directory)
    for run in runs:
        if (run.get("key") or {}).get("scenario") == needle:
            return Path(run["directory"])
    for run in runs:
        if needle in run["scenario"].lower() or needle in run["directory"].lower():
            return Path(run["directory"])
    return None


def load_run(directory, *, cache_dir=DEFAULT_CACHE_DIR) -> dict | None:
    """Re-open a stored run as ``{"run": ..., "books": [...]}``, exactly like a hit.

    Deliberately the same shape ``find_run`` returns, so the caller replays a stored
    run and a freshly cached one through one code path.
    """
    directory = Path(directory)
    run = _read(directory / RUN_FILENAME)
    if not run or run.get("response") is None:
        return None

    books = []
    for path in directory.glob("*.json"):
        if path.name == RUN_FILENAME:
            continue
        book = _read(path)
        if not book or book.get("output") is None:
            continue
        book["_path"] = str(path)
        books.append(book)

    books.sort(key=lambda b: b.get("output", {}).get("book_index", 0))
    run["_path"] = str(directory / RUN_FILENAME)
    return {"run": run, "books": books}


def find_book(reference: str, cache_dir=DEFAULT_CACHE_DIR, *, character: str | None = None) -> Path | None:
    """Resolve a book reference to a cache file.

    Accepts an explicit path, a character-relative ``<key>/<file>``, a filename, or
    the longest trailing fragment (``1-ambush`` or just ``ambush``) so typing a short
    prefix at the prompt is enough.
    """
    candidate = Path(reference)
    if candidate.is_file():
        return candidate

    paths = load_entries(cache_dir, character=character)
    if not paths:
        return None

    needle = reference.strip().lower().replace("\\", "/")
    if "/" in needle:
        for path in paths:
            if str(path).lower().endswith(needle) or str(path.parent).lower().endswith(needle):
                return path

    exact = [p for p in paths if p.stem.lower() == needle]
    if exact:
        return exact[0]
    # load_entries is newest-first, so the first partial match is the most recent one.
    # Sorting by anything else here would surface a stale book ahead of a fresh one.
    for path in paths:
        if needle in str(path).lower():
            return path
    return None


def rate(path, *, score: int, notes: str | None = None, outcome: str | None = None,
         rated_at: str | None = None) -> dict:
    """Record an outcome rating for a cached book and rewrite the entry."""
    path = Path(path)
    entry = _read(path)
    entry["rating"] = {
        "score": score,
        "rated_at": rated_at or now(),
        "notes": notes,
        "outcome": outcome,
    }
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry
