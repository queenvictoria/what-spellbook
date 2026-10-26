"""Spell metadata parsing and Book of Shadows eligibility rules.

This module is deliberately dependency-free (no LangChain, no Chroma, no network)
so it can be unit-tested in isolation and reused when building the vector index.

Two jobs:

1. **Parse** a spell's markdown file into structured facts (level, school, class
   list, ritual). The corpus stores these as hashtags in the header, but the
   ordering is inconsistent, so the parsing here is tolerant.
2. **Decide** whether a parsed spell is a legal pick for a given slot, applying the
   2024 Pact of the Tome / Book of Shadows rules. These functions are pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config

# The nine class lists a spell can appear on. Anything else in a `(...)` group is
# not a class list (e.g. a magic item's rarity or attunement note).
CLASS_NAMES = frozenset(
    {"Artificer", "Bard", "Cleric", "Druid", "Paladin", "Ranger", "Sorcerer", "Warlock", "Wizard"}
)

SCHOOL_NAMES = frozenset(
    {
        "Abjuration",
        "Conjuration",
        "Divination",
        "Enchantment",
        "Evocation",
        "Illusion",
        "Necromancy",
        "Transmutation",
    }
)

# Book of Shadows picks, 2024 rules: three cantrips and two level 1 rituals,
# drawn from any class's list.
BOOK_CANTRIP_PICKS = 3
BOOK_RITUAL_PICKS = 2
BOOK_RITUAL_MAX_LEVEL = 1

# A magic item page in the corpus is not a spell. The corpus mixes them in.
_MAGIC_ITEM_MARKER = "/magic-items/"

_CASTING_TIME = re.compile(r"\*\*Casting Time:\*\*")
_CASTING_TIME_VALUE = re.compile(r"\*\*Casting Time:\*\*\s*([^\n]*)", re.IGNORECASE)
_LEVEL = re.compile(r"#?(?:Level\s*(\d+)|(Cantrip))\b")
_SCHOOL = re.compile(r"#(" + "|".join(sorted(SCHOOL_NAMES)) + r")\b")
_CLASS_LIST = re.compile(r"\(([^)]*)\)")
_HASHTAG = re.compile(r"#(\w+)")
_RITUAL = re.compile(r"\bRitual\b", re.IGNORECASE)

# Model output parsing for the book-pick validation guard.
# Matches a pick-list label at the start of a line. It must be anchored: an
# unanchored 'Cantrip' also appears inside a pick's annotation
# ('1. **Light** (Cantrip; Evocation; Bard)') and would be mistaken for a new label.
# A leading bullet is allowed, because the model often writes the label as a list item
# ('- **Cantrips:** Word of Radiance, ...').
_BOOK_HEADING = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*{1,2}\s*)?(?:Level\s*\d+\s*)?(Cantrips?|Rituals?)\s*:?\s*\*{0,2}",
    re.IGNORECASE,
)
_ANY_HEADING = re.compile(r"^\s*(?:[-*+]\s+)?\*{1,2}[A-Z][^*]*:?\s*\*{0,2}")
_BOOK_ITEM = re.compile(r"^\s*(?:\d+\.|[-*])\s+(.+)$")
_SECTION_NAMES = {"cantrip": "cantrips", "cantrips": "cantrips",
                  "ritual": "rituals", "rituals": "rituals"}

# A pick list is written either as bullets on their own lines or inline after the
# label ('**Cantrips:** Light, Sacred Flame, Message'). Only handling bullets meant an
# inline list silently produced zero picks, so validation passed on an unreadable
# answer - the exact case the guard exists to catch.
_INLINE_LIST_SEPARATOR = re.compile(r"\s*[,;]\s*")

# The header block is everything before the casting-time line. Some pages (magic
# items, malformed entries) never have one, so fall back to a bounded prefix.
_HEADER_FALLBACK_CHARS = 600

# A spell's stats line names a level or a cantrip; a magic item's names a rarity.
_SPELL_LEVEL = re.compile(r"#(?:Level\d+|Cantrip)\b")


def corpus_spell_names(docs_path=None) -> list[str]:
    """Every spell name in the retrieval corpus, for cross-referencing prose.

    Read from the filenames rather than from the index: this is a list of *names* for
    matching against generated text, and it must include spells the index has not been
    rebuilt with. The corpus is the authority on what the model may name, so this is what
    the front end offers as linkable.

    The corpus's `Spells/` directory also holds 22 magic items - Glamerweave, Armblade,
    Docent - which are not spells. Offering one would make the front end link it and the
    lookup then 404, so they are filtered out by their stats line: a spell names a level
    or a cantrip, an item names a rarity.
    """
    root = Path(docs_path) if docs_path is not None else config.DOCS_DIR_PATH
    if not root.is_dir():
        return []
    names = set()
    for path in root.rglob("*.md"):
        try:
            head = path.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        if not _SPELL_LEVEL.search(head):
            continue
        # The page's own title wins over the filename, which is wrong for six files.
        name = spell_title(head) or prettify_name(path.stem)
        if name:
            names.add(name)
    return sorted(names)


def prettify_name(stem: str) -> str:
    """Turn a corpus filename stem into a display name.

    The corpus escapes apostrophes as ``_s`` ("Tenser_s Floating Disk"), so the escape
    has to be undone. Nothing else is done to the casing: the stems are already written
    the way the spell is spelled, and title-casing them is actively wrong. ``title()``
    capitalises every word, so "Ray of Frost" becomes "Ray Of Frost" - which then never
    matches the prose, and 77 spells containing a minor word (of, the, and, with, to,
    from, via, or, into) silently stop being linkable. It also breaks the possessive in
    "Melf's Acid Arrow" into "Melf'S", and the hyphenated "Abi-Dalzim's" and
    "Green-Flame" are already correct as written.

    The one stem that is genuinely malformed is "Heroes_ Feast", where the underscore
    stands in for an apostrophe rather than the ``_s`` escape.

    A filename is still only a filename: six corpus files are named after a different
    spell than the one they contain ("Confusion.md" holds Conjure Animals). Where the
    file itself can be read, prefer :func:`spell_title`, which takes the name from the
    page rather than the path.
    """
    name = re.sub(r"[_-]s\b", "'s", stem)
    return _straighten_apostrophes(name.replace("Heroes_ ", "Heroes' "))


def _straighten_apostrophes(name: str) -> str:
    """Normalise a typographic apostrophe to a straight one.

    The corpus writes "Tenser\u2019s Floating Disk" and the SRD writes "Tenser's Floating
    Disk". They are the same spell, and a name that differs only in which apostrophe it
    uses is a name that fails to match, so both sources are normalised to the SRD's
    convention. The front end folds the two together as well, for names it holds itself.
    """
    return name.replace("\u2019", "'")


# The corpus writes a spell's title as its first line, either as a markdown link to
# D&D Beyond (`# [Fireball](https://...)`) or, in 133 files, as a bare heading (`# Fireball`).
_TITLE_LINK = re.compile(r"^\s*#\s*\[([^\]]+)\]\([^)]*\)\s*$")
_TITLE_PLAIN = re.compile(r"^\s*#\s+(.+?)\s*$")


def spell_title(text: str) -> str | None:
    """The spell's own name, read from the first heading of its page.

    This is the authority on what a corpus file contains, because the filename is not:
    six files are named after a different spell than the page holds, and one
    ("Meld Into Stone.md") capitalises a minor word the page does not. Reading the title
    means a lookup and a link agree with the text the reader is shown.

    Returns None when the page has no heading, so a caller can fall back to the filename.
    """
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _TITLE_LINK.match(line) or _TITLE_PLAIN.match(line)
        return _straighten_apostrophes(match.group(1).strip()) if match else None
    return None


def header_block(text: str) -> str:
    """Return the part of a spell page that carries its metadata tags.

    Class lists and levels appear only in the header. Restricting the search to
    this region stops body prose from producing false matches.
    """
    match = _CASTING_TIME.search(text)
    if match:
        return text[: match.start()]
    return text[:_HEADER_FALLBACK_CHARS]


def _is_ritual(text: str, block: str) -> bool:
    """Detect the Ritual property.

    The corpus has no ``#Ritual`` tag, so the marker is the Casting Time value
    itself ("Action or Ritual", "1 hour (Ritual)"). That line sits *after* the
    header block, so it has to be matched separately - searching the whole page
    instead would false-positive on prose that merely mentions rituals.
    """
    if "#Ritual" in block:
        return True
    match = _CASTING_TIME_VALUE.search(text)
    return bool(match and _RITUAL.search(match.group(1)))


@dataclass(frozen=True)
class Spell:
    """Structured facts about one entry in the spell corpus."""

    name: str
    filename: str
    level: int | None = None  # 0 for cantrips; None when unparseable
    school: str | None = None
    classes: frozenset[str] = field(default_factory=frozenset)
    is_ritual: bool = False
    is_spell: bool = True

    @property
    def is_cantrip(self) -> bool:
        return self.level == 0


def parse_spell(name: str, filename: str, text: str) -> Spell:
    """Parse one spell page into a :class:`Spell`.

    Never raises: unrecognised pages come back with ``level=None`` so callers can
    decide whether to keep them.
    """
    if _MAGIC_ITEM_MARKER in text:
        return Spell(name=name, filename=filename, is_spell=False)

    block = header_block(text)

    level: int | None = None
    level_match = _LEVEL.search(block)
    if level_match:
        level = 0 if level_match.group(2) else int(level_match.group(1))

    school_match = _SCHOOL.search(block)
    school = school_match.group(1) if school_match else None

    classes: set[str] = set()
    for group in _CLASS_LIST.findall(block):
        classes.update(tag for tag in _HASHTAG.findall(group) if tag in CLASS_NAMES)

    return Spell(
        name=name,
        filename=filename,
        level=level,
        school=school,
        classes=frozenset(classes),
        is_ritual=_is_ritual(text, block),
    )


def spell_from_metadata(metadata: dict) -> Spell:
    """Rebuild a :class:`Spell` from Chroma metadata.

    Numeric ``level`` is preferred when present; older indexes only carry the
    hashtag string, so fall back to parsing that.
    """
    filename = str(metadata.get("filename") or "")
    level = metadata.get("level")
    if isinstance(level, int):
        parsed_level: int | None = level
    else:
        # Legacy indexes stored metadata as a comma-joined tag string, e.g.
        # "Level3, Necromancy, Bard" - parse the level back out of it.
        level_match = _LEVEL.search(str(metadata.get("tags") or ""))
        if level_match:
            parsed_level = 0 if level_match.group(2) else int(level_match.group(1))
        else:
            parsed_level = None

    classes = metadata.get("classes")
    if isinstance(classes, str):
        class_set = frozenset(c.strip() for c in classes.split(",") if c.strip() in CLASS_NAMES)
    elif isinstance(classes, (list, tuple, set, frozenset)):
        class_set = frozenset(c for c in classes if c in CLASS_NAMES)
    else:
        class_set = frozenset()

    return Spell(
        name=str(metadata.get("spell_name") or filename.removesuffix(".md")),
        filename=filename,
        level=parsed_level,
        school=metadata.get("school") if isinstance(metadata.get("school"), str) else None,
        classes=class_set,
        is_ritual=bool(metadata.get("ritual")),
        is_spell=metadata.get("is_spell", True) is not False,
    )


def build_metadata(spell: Spell, source_path: str) -> dict:
    """Build the Chroma metadata payload for a parsed spell.

    ``level`` is written as a real integer because Chroma can only do numeric
    comparisons (``$lte``) on numeric metadata. The index is shared by every
    character, so nothing character-specific is baked in here - whether a spell is
    *castable* depends on the character's slot level and is filtered at query time.
    """
    return {
        "source": source_path,
        "filename": spell.filename,
        "spell_name": spell.name,
        "level": spell.level if spell.level is not None else -1,
        "school": spell.school or "",
        "classes": ", ".join(sorted(spell.classes)),
        "ritual": spell.is_ritual,
        "is_spell": spell.is_spell,
        "tags": ", ".join(sorted(spell.classes)) or "None",
    }


def build_where(*clauses):
    """Combine Chroma ``where`` clauses into a single valid filter.

    Chroma requires exactly one top-level operator, and rejects an ``$and`` with a
    single child, so one clause is returned bare and an empty set becomes ``None``.
    """
    present = [c for c in clauses if c]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    return {"$and": present}


def _not_known(clause_key: str, exclude_names) -> dict | None:
    """``$nin`` clause skipping the case where there is nothing to exclude."""
    names = [n for n in exclude_names if n]
    if not names:
        return None
    return {clause_key: {"$nin": names}}



def book_cantrip_filter(*, exclude_names=()) -> dict | None:
    """Cantrips eligible for the Book of Shadows."""
    return build_where(
        {"is_spell": True},
        {"level": 0},
        _not_known("spell_name", exclude_names),
    )


def book_ritual_filter(*, exclude_names=()) -> dict | None:
    """Level 1 ritual spells eligible for the Book of Shadows."""
    return build_where(
        {"is_spell": True},
        {"level": BOOK_RITUAL_MAX_LEVEL},
        {"ritual": True},
        _not_known("spell_name", exclude_names),
    )


def eligible_cantrips(spells, *, known_spells=frozenset()) -> list:
    """Cantrips that may be written into the Book of Shadows.

    Any class list is allowed; spells already prepared as Warlock spells are not,
    because the book's picks must be spells you do not already have prepared.
    """
    known = {s.lower() for s in known_spells}
    return [
        s
        for s in spells
        if s.is_spell
        and s.is_cantrip
        and s.name.lower() not in known
    ]


def eligible_rituals(spells, *, known_spells=frozenset()) -> list:
    """Level 1 ritual spells that may be written into the Book of Shadows."""
    known = {s.lower() for s in known_spells}
    return [
        s
        for s in spells
        if s.is_spell
        and s.level == BOOK_RITUAL_MAX_LEVEL
        and s.is_ritual
        and s.name.lower() not in known
    ]



def _entry_name(entry: str) -> str:
    """Extract the spell name from one bullet like '1. **Light** - provides light'.

    Models often copy the pool's annotation into the bolded name, producing
    '**Light (Cantrip; Evocation; Bard)**'. That annotation has to be dropped or the
    name never matches the pool and every pick is falsely reported as illegal.

    Apostrophes are normalised to ASCII: models reliably emit a typographic '’' for
    "Tenser's Floating Disk" while the indexed corpus uses "'", so without this a
    legal pick is reported as illegal purely on the character used.

    Internal spaces are preserved: collapsing them turns "Detect Magic" into
    "DetectMagic", which matches nothing.
    """
    text = _BOLD_NAME.search(entry)
    name = text.group(1) if text else entry.split(" - ")[0]
    name = _ANNOTATION.sub("", name)
    name = re.sub(r"^\s*\d+[.)]\s*", "", name)
    return name.strip(" \t`*_").translate(_APOSTROPHES)


# Typographic apostrophes mapped to ASCII, so a model's '’' still matches the corpus.
# Typographic apostrophes mapped to ASCII, so a model's '’' still matches the corpus.
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u00b4": "'"})


_BOLD_NAME = re.compile(r"\*\*([^*]+)\*\*")
_ANNOTATION = re.compile(r"\s*[\(\[]\s*(?:Cantrip|Level\s*\d|Ritual).*$", re.IGNORECASE)


def _iter_books(answer: str):
    """Yield the text of each book section.

    Delegates the split to ``cache.split_books``, which knows the heading shapes
    models actually produce (``## Book 1 — Title``, ``**Book 1: Title**``) and ignores
    prose that merely mentions a book. Splitting here as well produced two behaviours,
    and this one silently yielded nothing for a bold heading - so validation passed
    vacuously on an answer it never examined.

    Split per book, otherwise the picks from all three books accumulate and the
    per-book pick counts look wildly wrong.
    """
    from . import cache

    for book in cache.split_books(answer):
        if book["text"].strip():
            yield book["text"]


def _book_picks(section: str) -> dict[str, list[str]]:
    """Extract the cantrip and ritual pick lists from one book section.

    Handles both shapes the model produces: bulleted items under a label, and an
    inline comma-separated list on the label line itself.
    """
    found: dict[str, list[str]] = {"cantrips": [], "rituals": []}
    section_name = None
    for line in section.splitlines():
        heading = _BOOK_HEADING.search(line)
        if heading:
            # Casefolded: the model writes 'level 1 rituals' as often as 'Rituals'.
            section_name = _SECTION_NAMES.get(heading.group(1).strip().lower())
            # Anything after the label on the same line is the list itself.
            remainder = line[heading.end():].strip(" \t*:`-")
            if section_name and remainder:
                found[section_name].extend(_split_pick_list(remainder))
            continue
        # Any other bold heading (How to Use, Rationale, ...) ends the pick list.
        if _ANY_HEADING.match(line):
            section_name = None
            continue
        if section_name is None:
            continue
        item = _BOOK_ITEM.match(line)
        if item:
            found[section_name].append(_entry_name(item.group(1)))
        elif line.strip() and _INLINE_LIST_SEPARATOR.search(line):
            # A wrapped inline list continuing on the next line.
            found[section_name].extend(_split_pick_list(line))
    return found


_ANNOTATION_SPAN = re.compile(
    r"[\(\[]\s*(?:Cantrip|Level\s*\d|Ritual)[^)\]]*[\)\]]?", re.IGNORECASE
)


def _split_pick_list(text: str) -> list[str]:
    """Split an inline 'Light, Sacred Flame, Message' list into clean names.

    Annotation spans are removed *before* splitting: they are written with semicolons
    ('Light (Cantrip; Evocation; Bard)'), so splitting first would tear one pick into
    three fragments and report every one of them as illegal.
    """
    cleaned = _ANNOTATION_SPAN.sub("", text)
    names = []
    for chunk in _INLINE_LIST_SEPARATOR.split(cleaned):
        name = _entry_name(chunk)
        if name:
            names.append(name)
    return names


def validate_book_picks(answer: str, cantrips, rituals, *, known=()) -> list[str]:
    """Check the model's book pick lists against the eligible pool.

    Returns a list of human-readable problems, empty when the answer is clean. This is
    a deterministic backstop: models reliably mis-file spells that appear in the rules
    context but not in the pool (a Celestial Warlock's always-prepared Guiding Bolt is
    the recurring example), and a wrong book is only discovered at the table.
    """
    pools = {
        "cantrips": {s.name.lower(): s.name for s in cantrips},
        "rituals": {s.name.lower(): s.name for s in rituals},
    }
    required = {"cantrips": BOOK_CANTRIP_PICKS, "rituals": BOOK_RITUAL_PICKS}
    known_lower = {k.lower() for k in known}
    problems: list[str] = []

    for index, section in enumerate(_iter_books(answer), start=1):
        picked = _book_picks(section)
        for kind, names in picked.items():
            if not names:
                continue
            # Never demand more picks than the pool can supply.
            want = min(required[kind], len(pools[kind]))
            if len(names) != want:
                problems.append(
                    f"book {index}: expected {want} {kind}, listed {len(names)} ({names})"
                )
            for name in names:
                if name.lower() in known_lower:
                    problems.append(
                        f"book {index}: '{name}' is already prepared and cannot be a book pick"
                    )
                elif name.lower() not in pools[kind]:
                    problems.append(
                        f"book {index}: '{name}' is not an eligible {kind[:-1]} in the pool"
                    )

    return problems


def describe_pool(spells, *, exclude=()) -> str:
    """Render a spell pool as the compact list handed to the model.

    One line per spell keeps the prompt small. Duplicates are dropped and anything in
    ``exclude`` skipped, because the pool arrives from several retrieval lanes that
    can each return the same spell (and, before dedupe, the same spell once per chunk).
    """
    skip = {s.lower() for s in exclude}
    seen: set[str] = set()
    lines = []
    for s in sorted(spells, key=lambda x: (x.level if x.level is not None else 99, x.name)):
        key = s.name.lower()
        if key in seen or key in skip:
            continue
        seen.add(key)

        level = "Cantrip" if s.is_cantrip else (f"Level {s.level}" if s.level is not None else "Level ?")
        bits = [level]
        if s.school:
            bits.append(s.school)
        if s.is_ritual:
            bits.append("Ritual")
        if s.classes:
            bits.append("/".join(sorted(s.classes)))
        lines.append(f"- {s.name} ({'; '.join(bits)})")
    return "\n".join(lines)
