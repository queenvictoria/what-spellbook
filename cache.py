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

# Bump when the entry shape changes, so old entries are recognisable rather than
# silently misread.
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
) -> list[Path]:
    """Write a run to the cache: one shared file plus one file per book.

    The prompt, sheet and pool are identical for all three books, so storing them per
    book copied ~35KB three times per run. They live once in ``run.json``; each book
    file holds only what is specific to that book.

    A book file is the unit of rating, so its rating is written to its own file and a
    regeneration never disturbs a sibling's rating. Returns the paths written.
    """
    parts = key_parts(
        character=character, level=level, party=party, db_version=db_version, scenario=scenario
    )
    directory = entry_dir(cache_dir, parts)
    books = split_books(answer)
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
        "model": model,
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
                "text": book["text"],
                "picks": parse_picks(book["text"]),
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
) -> dict | None:
    """Return ``{"run": ..., "books": [...]}`` for these exact inputs, or None.

    This is the read side of the cache. A hit requires the whole key to match *and*
    the left character fingerprint, so editing the sheet between runs misses instead
    of replaying advice for a character that no longer exists.
    """
    parts = key_parts(
        character=character, level=level, party=party, db_version=db_version, scenario=scenario
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
    expected = len(split_books(run["response"]))
    if not books or len(books) != expected:
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
