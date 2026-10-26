"""Local result cache: one JSON file per generated book.

Every generated book is written under ``.cache/`` so a recommendation can be
revisited later. The point of the store is to make outcome ratings possible: the
entry keeps the exact inputs, contexts, prompts and raw response alongside the
parsed book, and adds a ``rating`` block the user fills in after the session.

Layout::

    .cache/
      <character>/
        <level>-<party>-<dbversion>-<scenario>/
          <book-slug>.json

The directory path *is* the key (character, level, party, database version,
scenario), and each book gets its own file, so a book can be rated or replaced
without rewriting its siblings.

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

# Bump when the entry shape changes, so old entries are recognisable rather than
# silently misread.
SCHEMA_VERSION = 1

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


def key_parts(*, character: str, level, party, db_version, scenario: str) -> dict:
    """The cache key: everything that would change the recommendation."""
    return {
        "character": _slug(character),
        "level": level,
        "party": _slug(", ".join(party) if isinstance(party, (list, tuple, set)) else party),
        "db_version": db_version,
        "scenario": scenario_fingerprint(scenario),
    }


def key_dir(key: dict) -> str:
    """Directory name for a key: level, party, database version, scenario hash."""
    return "-".join(
        str(part) for part in (key["level"], key["party"], key["db_version"], key["scenario"])
    )


def entry_dir(cache_dir, key: dict) -> Path:
    """``<cache_dir>/<character>/<key>``."""
    return Path(cache_dir) / key["character"] / key_dir(key)


def book_slug(index: int, name: str) -> str:
    """Filename stem for one book, e.g. ``1-ambush-and-control``."""
    return f"{index}-{_slug(name, max_length=40)}"


def split_books(answer: str) -> list[dict]:
    """Split a model answer into per-book sections containing the original text.

    Each section keeps its exact markdown, so the raw response is never lost when a
    book is stored on its own. Books are the unit of rating, so they have to be
    separable; an answer with no recognisable headings becomes a single section.
    """
    matches = [m for m in _BOOK_HEADING.finditer(answer) if _is_book_heading(m.group(0))]
    if not matches:
        text = answer.strip()
        return [{"index": 1, "name": "Untitled", "text": text}] if text else []

    books = []
    for position, match in enumerate(matches):
        start = match.start()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(answer)
        text = answer[start:end].strip()
        books.append(
            {"index": int(match.group(1)), "name": book_name(text), "text": text}
        )

    # A trailing summary can push a real book's text into a sibling's section; keep the
    # first occurrence of each number so 'Book 3' is not reported twice.
    seen: set[int] = set()
    deduped = []
    for book in books:
        if book["index"] in seen:
            continue
        seen.add(book["index"])
        deduped.append(book)
    return deduped


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
    unreadable answer passes both). Imported lazily so this module stays dependency
    free for callers that only need the key helpers.
    """
    import spells

    return spells._book_picks(section)


def save_books(
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
    book_filters: dict | None = None,
    model: str | None = None,
) -> list[Path]:
    """Write one JSON entry per generated book. Returns the files written.

    Failures are reported by the caller and never raised: a cache that cannot be
    written must not lose a recommendation the user is reading.
    """
    parts = key_parts(
        character=character, level=level, party=party, db_version=db_version, scenario=scenario
    )
    directory = entry_dir(cache_dir, parts)
    books = split_books(answer)

    written: list[Path] = []
    for book in books:
        slug = book_slug(book["index"], book["name"])
        filters = (book_filters or {}).get(book["name"]) or (book_filters or {}).get(book["index"])
        entry = {
            "schema_version": SCHEMA_VERSION,
            "created_at": now(),
            "key": {**parts, "scenario_text": scenario.strip()},
            "input": input_data or {},
            "context": context or {},
            "prompt": prompts or {},
            "response": answer,
            "output": {
                "book_index": book["index"],
                "book_name": book["name"],
                "text": book["text"],
                "picks": parse_picks(book["text"]),
                "book_filters": filters or {},
            },
            "rating": {
                "score": None,
                "rated_at": None,
                "notes": None,
                "outcome": None,
            },
            "model": model,
        }
        path = directory / f"{slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_entries(cache_dir=DEFAULT_CACHE_DIR, *, character: str | None = None) -> list[Path]:
    """List cached entries, newest first; optionally filtered to one character."""
    root = Path(cache_dir)
    if not root.is_dir():
        return []
    pattern = f"{_slug(character)}/*/*.json" if character else "*/*/*.json"
    paths = list(root.glob(pattern))
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


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
