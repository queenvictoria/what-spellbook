"""Browsing the vendored 2024 SRD as documents, rather than as answers.

``rules`` answers a *question*: it ranks sections by how well their headings name the
subject and quotes the one that wins. This module answers a different need - "show me the
rulebook" - and the difference is not cosmetic.

A browser must be **complete and stable**. Every file, every heading, in document order,
with an anchor that does not move when the corpus is re-read. Retrieval is allowed to be
selective and order-dependent, because a question has one best answer; a table of contents
that omitted a section would simply be wrong. So the two share the corpus (``rules``
remains the authority on which files are SRD text and how to read one) but not the
matching.

Two conversions happen here that ``rules`` does differently, for the same reason:

* **Tables become Markdown pipe tables, not sentences.** ``rules.tables_to_text`` flattens
  a table into ``header: cell; header: cell.`` because a prompt cannot read markup. A
  reader can, and the numbers in a table are the rule - ``### Cover``'s prose only says
  "as detailed in the Cover table", so a browser that dropped the table would show a
  confident rule with its numbers missing.
* **Headings keep their level.** ``rules.markdown_to_text`` flattens every heading to
  ``##`` so the matcher sees one flat list of sections. A browser needs the nesting: the
  whole point of the tree is that ``#### Attack [Action]`` sits under ``## Actions``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import config, rules

# The BOM is real: ``spells.md`` starts with one, and left in place it becomes part of the
# first heading's text - so the file's title would be "\ufeffSpells" and its slug would
# begin with a stray hyphen.
_BOM = "\ufeff"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

_TABLE = re.compile(r"<table>(.*?)</table>", re.S | re.I)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t([hd])([^>]*)>(.*?)</t\1>", re.S | re.I)
_COLSPAN = re.compile(r'colspan\s*=\s*"(\d+)"', re.I)
_EMPHASIS = re.compile(r"<em>(.*?)</em>", re.S | re.I)
_THEAD = re.compile(r"<thead>(.*?)</thead>", re.S | re.I)
_TBODY = re.compile(r"<tbody>(.*?)</tbody>", re.S | re.I)


@dataclass(frozen=True)
class Heading:
    """One heading in a document, with the anchor that identifies it.

    ``slug`` is de-duplicated within its document. The SRD repeats headings - ``classes.md``
    has six ``Level 1: Spellcasting`` sections, one per class - so a slug derived from the
    text alone would collide and every link after the first would open the wrong section.
    """

    text: str
    level: int
    slug: str
    # Line index of the heading in the file, used to slice a section out. Not part of the
    # wire contract: a client addresses a section by slug, never by line.
    line: int = field(default=0, repr=False, compare=False)
    children: tuple["Heading", ...] = ()


@dataclass(frozen=True)
class Document:
    """One vendored SRD file, as a table of contents."""

    name: str
    title: str
    path: str
    headings: tuple[Heading, ...] = ()


@dataclass(frozen=True)
class Section:
    """One heading's own text, from the heading line to the next same-or-higher one.

    ``ancestors`` is the chain of headings above this one, outermost first, and excludes the
    heading itself. It is what a breadcrumb is drawn from: a rule is reached by descending
    through its parents, and "Prone [Condition]" alone does not say it lives under *Rules
    Definitions* in the *Rules Glossary*.
    """

    document: Document
    heading: Heading
    text: str
    ancestors: tuple[Heading, ...] = ()


def _slugify(text: str) -> str:
    """A URL-safe anchor for a heading.

    Deliberately not GitHub's algorithm. The anchors are internal to this app - nothing
    links to them from outside - so the only requirement is that they are stable and
    readable, and a plain lowercase-and-hyphenate is easier to reason about than a
    reimplementation of someone else's rules.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def _unique_slug(text: str, used: dict[str, int]) -> str:
    base = _slugify(text)
    count = used.get(base, 0) + 1
    used[base] = count
    return base if count == 1 else f"{base}-{count}"


def _scan(text: str) -> list[tuple[int, str, int]]:
    """``(level, text, line)`` for every heading, in document order.

    A heading inside a blockquote (``> ### Breaking Your Oath``) is *not* matched, because
    the line does not begin with ``#``. That is correct: it is quoted text inside a rule,
    not a section of the document, and giving it an anchor would put a Paladin's oath
    discussion in the table of contents as a sibling of the Paladin class.
    """
    found: list[tuple[int, str, int]] = []
    for index, line in enumerate(text.split("\n")):
        match = _HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2), index))
    return _repair_stat_blocks(found)


# A creature stat block's own subsections. Every stat block in the SRD opens with
# ``#### Traits``, and nothing else in the corpus uses that heading.
_STAT_BLOCK_OPENING = "Traits"


def _repair_stat_blocks(
    entries: list[tuple[int, str, int]],
) -> list[tuple[int, str, int]]:
    """Re-level a stat block that the conversion left at the wrong depth.

    Three spells - *Find Steed*, *Giant Insect* and *Summon Dragon* - carry a creature stat
    block, and the vendored conversion wrote the stat block's name as ``##`` while the spell
    that owns it is ``####``. Left alone, the tree is badly wrong in a way that is invisible
    until you read it: ``## Otherworldly Steed`` closes ``## Spell Descriptions``, so the 121
    spells after *Find Steed* - Fireball among them - become children of a steed's stat
    block, and the same happens again at *Giant Insect* and *Draconic Spirit*.

    The repair is narrow on purpose. It fires only when a heading is followed immediately by
    a deeper ``#### Traits``, which is the stat-block signature and appears nowhere else in
    the corpus, and it moves the heading to the depth of the spell it belongs to rather than
    guessing. A general "fix the levels" pass would rewrite the class chapters, where a
    ``###`` after a ``####`` is the real structure.
    """
    repaired = list(entries)
    for index, (level, text, line) in enumerate(entries[:-1]):
        next_level, next_text, _ = entries[index + 1]
        if next_text != _STAT_BLOCK_OPENING or next_level <= level:
            continue
        # The stat block belongs to the spell above it, so it takes that spell's level.
        owner = next(
            (entries[k][0] for k in range(index - 1, -1, -1) if entries[k][0] > level),
            None,
        )
        if owner is not None:
            repaired[index] = (owner, text, line)
    return repaired


def _freeze(node: dict) -> Heading:
    return Heading(
        text=node["text"],
        level=node["level"],
        slug=node["slug"],
        line=node["line"],
        children=tuple(_freeze(child) for child in node["children"]),
    )


def _tree(entries: list[tuple[int, str, int]]) -> tuple[Heading, ...]:
    """Nest a flat heading list by level.

    A stack rather than recursion, because the SRD's levels are not guaranteed to step by
    one: ``spells.md`` goes from ``## Spell Descriptions`` straight to ``#### Fireball``
    for 352 spells, and a parser that required an intervening ``###`` would drop every one
    of them.
    """
    roots: list[dict] = []
    stack: list[dict] = []
    used: dict[str, int] = {}

    for level, text, line in entries:
        node = {
            "text": text,
            "level": level,
            "slug": _unique_slug(text, used),
            "line": line,
            "children": [],
        }
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)

    return tuple(_freeze(node) for node in roots)


def _title(entries: list[tuple[int, str, int]], name: str) -> str:
    """The file's own H1, or its name prettified when it has none.

    ``spells.md`` is the file without an H1 in the usual sense - its first line is
    ``\ufeff# Spells``, which the BOM strip turns into a real one - so the fallback is for
    a file that genuinely starts at ``##``.
    """
    for level, text, _ in entries:
        if level == 1:
            return text
    return name.replace("-", " ").title()


def _cell_text(raw: str) -> str:
    """One table cell as inline Markdown.

    Whitespace is collapsed because the source wraps cells across lines (155 of them), and
    a newline inside a pipe-table cell ends the row. ``<em>`` becomes ``*`` because the SRD
    italicises the group labels in a header row and the emphasis is meaningful there.
    """
    text = _EMPHASIS.sub(r"*\1*", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split()).replace("|", r"\|")


def _expand(row: str) -> list[str]:
    """One ``<tr>`` as a list of cells, with ``colspan`` widened to empty neighbours.

    Markdown has no colspan, so a span becomes its label followed by empty cells. That
    keeps every row the same width - which is what makes the table render at all - and
    puts the label where a reader expects it, in the first column of the span.
    """
    cells: list[str] = []
    for match in _CELL.finditer(row):
        text = _cell_text(match.group(3))
        span = _COLSPAN.search(match.group(2))
        width = int(span.group(1)) if span else 1
        cells.append(text)
        cells.extend([""] * (width - 1))
    return cells


def _merge_header(rows: list[list[str]]) -> list[str]:
    """Fold a multi-row ``<thead>`` into the single header row Markdown allows.

    The class progression tables have two: the column names, then the spell-slot levels
    under a ``colspan="9"`` group label. Joining column-wise keeps both - "Spell Slots per
    Spell Level 1" - where taking only the last row would lose the group label and taking
    only the first would lose the levels.
    """
    width = max((len(row) for row in rows), default=0)
    merged: list[str] = []
    for column in range(width):
        parts = [row[column] for row in rows if column < len(row) and row[column]]
        merged.append(" ".join(parts))
    return merged


def _table_to_markdown(match: re.Match) -> str:
    body = match.group(1)
    head = _THEAD.search(body)
    header_rows = [_expand(row) for row in _ROW.findall(head.group(1))] if head else []

    # A table with no <thead> has no header, and Markdown requires one. An empty header is
    # the honest rendering: the SRD's headerless tables are key/value blocks and
    # abbreviation grids, where promoting the first row would label "Primary Ability" as a
    # column heading and put "Strength" under it.
    header = _merge_header(header_rows) if header_rows else []

    tbody = _TBODY.search(body)
    body_rows = [_expand(row) for row in _ROW.findall(tbody.group(1) if tbody else body)]

    width = max([len(header), *(len(row) for row in body_rows)], default=0)
    if width == 0:
        return ""

    def line(cells: list[str]) -> str:
        padded = cells + [""] * (width - len(cells))
        return "| " + " | ".join(padded) + " |"

    out = [line(header or [""] * width), "| " + " | ".join(["---"] * width) + " |"]
    out.extend(line(row) for row in body_rows)
    return "\n".join(out)


def to_markdown(text: str) -> str:
    """The vendored file as Markdown a renderer can draw.

    Only two things change: the BOM is dropped, and HTML tables become pipe tables. Nothing
    else is rewritten - the point of a browser is to show the rulebook, and every
    transformation is a chance to show something the rulebook does not say.
    """
    return _TABLE.sub(_table_to_markdown, text.lstrip(_BOM))


@lru_cache(maxsize=8)
def _read(path: Path) -> str:
    """The file's text with the BOM removed.

    Stripped here rather than in ``to_markdown`` because the *scanner* needs it too:
    ``spells.md`` begins ``\\ufeff# Spells``, and a BOM in front of the ``#`` stops the
    heading regex matching, which silently demotes the file's title and leaves its 15
    top-level sections as siblings of nothing.
    """
    return rules.read_srd(path).lstrip(_BOM)


def _document(path: Path) -> Document:
    text = _read(path)
    entries = _scan(text)
    return Document(
        name=path.stem,
        title=_title(entries, path.stem),
        path=_reference(path),
        headings=_tree(entries),
    )


def _reference(path: Path) -> str:
    """Repo-relative path, so the UI can show where a rule came from."""
    try:
        return str(Path(path).resolve().relative_to(config.ROOT))
    except ValueError:
        return str(path)


@lru_cache(maxsize=1)
def documents() -> tuple[Document, ...]:
    """Every vendored SRD file, as a table of contents.

    Cached because the Rules screen asks for it on every mount and parsing 880KB of
    Markdown to answer "what headings exist" is pure waste. ``clear_cache`` exists because
    the corpus is editable: a stale tree after an edit is a confusing bug in a tool whose
    whole job is showing what is on disk.
    """
    return tuple(_document(path) for path in rules.source_files())


def clear_cache() -> None:
    """Drop the parsed tree *and* the file text, so an edit is picked up immediately."""
    documents.cache_clear()
    _read.cache_clear()


def document(name: str) -> Document:
    """One document by its file stem, e.g. ``classes``.

    Raises ``rules.RulesUnavailable`` for an unknown name rather than returning ``None``,
    so the API maps it to a 404 through the same path every other missing-rule case uses.
    """
    wanted = str(name).strip().lower()
    for found in documents():
        if found.name.lower() == wanted:
            return found
    known = ", ".join(found.name for found in documents()) or "none"
    raise rules.RulesUnavailable(
        f"No SRD document named '{name}'. The vendored SRD has: {known}."
    )


def anchor(name: str, heading: str) -> str | None:
    """The slug of the heading called ``heading`` in document ``name``, or None.

    Used to turn a whole-file reference into a link to the rule inside it. A spell's
    ``url`` is ``context/srd/spells.md`` because that is the file it was read from, but
    opening 325KB of spell descriptions to find Fireball is not a useful thing to offer -
    the anchor is what makes the path a link to the rule rather than to the book.

    Matched on the heading text, case-insensitively, because the caller has a name and not
    a slug. The *first* match wins, which is right for a spell: the SRD has one
    ``#### Fireball``, and the stat blocks that repeat a name come after the spell.
    """
    wanted = " ".join(str(heading).split()).casefold()
    if not wanted:
        return None

    def walk(headings: tuple[Heading, ...]) -> str | None:
        for found in headings:
            if found.text.casefold() == wanted:
                return found.slug
            deeper = walk(found.children)
            if deeper is not None:
                return deeper
        return None

    try:
        return walk(document(name).headings)
    except rules.RulesUnavailable:
        return None


def _find(headings: tuple[Heading, ...], slug: str) -> Heading | None:
    for heading in headings:
        if heading.slug == slug:
            return heading
        found = _find(heading.children, slug)
        if found is not None:
            return found
    return None


def _trail(headings: tuple[Heading, ...], slug: str,
           trail: tuple[Heading, ...] = ()) -> tuple[Heading, ...] | None:
    """The chain of headings from the root down to ``slug``, inclusive, or None.

    The same walk as ``_find``, carrying the path. Kept separate rather than folded into
    ``_find`` because the two answer different questions and only one of them needs the
    path - a caller that wants the heading alone should not pay for a tuple it discards.
    """
    for heading in headings:
        here = trail + (heading,)
        if heading.slug == slug:
            return here
        found = _trail(heading.children, slug, here)
        if found is not None:
            return found
    return None


def section(name: str, slug: str) -> Section:
    """One heading's own text, from its heading line to the next same-or-higher heading.

    The heading line is included, so the returned Markdown reads as a document fragment
    rather than a body with no title. A caller that also shows the heading as a card title
    would print it twice - so the card shows the *document* title and lets the section
    heading be the first line of the text.
    """
    found = document(name)
    heading = _find(found.headings, slug)
    if heading is None:
        raise rules.RulesUnavailable(
            f"'{found.title}' has no section '{slug}'. "
            "The heading may have been renamed in the vendored file."
        )

    lines = _read(rules.srd_dir() / f"{found.name}.md").split("\n")
    entries = _scan("\n".join(lines))
    start = heading.line
    end = len(lines)
    for level, _, line in entries:
        if line > start and level <= heading.level:
            end = line
            break

    trail = _trail(found.headings, slug) or (heading,)
    return Section(
        document=found,
        heading=heading,
        text=to_markdown("\n".join(lines[start:end]).rstrip() + "\n"),
        # The heading itself is dropped: a breadcrumb shows where the rule sits, and
        # repeating the rule's own name as the last crumb would state it twice - the card
        # already titles it.
        ancestors=trail[:-1],
    )


def text(name: str) -> str:
    """A whole document as renderable Markdown."""
    found = document(name)
    return to_markdown(_read(rules.srd_dir() / f"{found.name}.md"))


def _flatten(headings: tuple[Heading, ...]):
    """Every heading in a tree, depth first, in document order."""
    for heading in headings:
        yield heading
        yield from _flatten(heading.children)


def _index_sections(name: str) -> list[tuple[Heading, str]]:
    """Every heading in one document with its own text, in document order.

    The same slice ``section`` computes, done for all 1279 headings in one pass instead of
    one file read per heading. Indexing calls this once per document; calling ``section`` in
    a loop would re-read and re-scan the file 1279 times.

    A heading with no body of its own is still returned. ``## Spell Descriptions`` holds
    nothing but 352 children, and dropping it would lose the one row that says the chapter
    exists - which is exactly what a reader searching for "spell descriptions" wants.
    """
    found = document(name)
    lines = _read(rules.srd_dir() / f"{found.name}.md").split("\n")
    entries = _scan("\n".join(lines))

    # The end of a section is the next heading at the same or a higher level. Computed with
    # a stack in one pass: a nested scan per heading would be quadratic over 11,000 lines.
    ends = [len(lines)] * len(entries)
    stack: list[int] = []
    for index, (level, _, _) in enumerate(entries):
        while stack and entries[stack[-1]][0] >= level:
            ends[stack.pop()] = entries[index][2]
        stack.append(index)

    by_line = {line: index for index, (_, _, line) in enumerate(entries)}
    flat: list[tuple[Heading, str]] = []
    for heading in _flatten(found.headings):
        index = by_line.get(heading.line)
        if index is None:
            continue
        body = "\n".join(lines[heading.line:ends[index]]).rstrip()
        # The file's own H1 is a title wrapper, not a section: ``# Classes`` is immediately
        # followed by ``## Barbarian`` and holds no text of its own, so indexing it would
        # add one row containing the entire 298KB chapter. Its children are indexed
        # normally, and the document title is carried on every one of them anyway.
        if heading.level == 1:
            continue
        flat.append((heading, to_markdown(body + "\n")))
    return flat


def sections() -> list[tuple[Document, Heading, str]]:
    """Every SRD section as ``(document, heading, markdown)``, for indexing.

    This is the whole rulebook in one list, which is what the vector store needs and what
    nothing else does: ``documents`` gives the tree without text, and ``section`` gives one
    section's text but re-reads the file to do it.
    """
    found: list[tuple[Document, Heading, str]] = []
    for document_ in documents():
        for heading, body in _index_sections(document_.name):
            found.append((document_, heading, body))
    return found
