"""Character sheet loading and the rules-derived questions we ask of a sheet.

A sheet is not one field per concept: "what the character already has" arrives spread
across Warlock picks, the patron's always-prepared list, species and feat grants, and
free casts. These helpers centralise that reading so the pool, the prompt and the
validator all agree about what a character owns.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from . import config

# Typographic apostrophes mapped to ASCII. Models and hand-written sheets emit '’'
# where the indexed corpus uses "'", and an unmatched name is silently dropped from
# the pool or falsely reported as an illegal pick.
APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u00b4": "'"})

# Every sheet field that means "the character permanently has this spell". The Book of
# Shadows explicitly cannot duplicate what is already prepared, and the model will
# suggest them anyway if they are left in the pool, so they are all excluded.
KNOWN_SPELL_FIELDS = (
    "Known/Prepared Base Spells",
    "Known Prepared Base Spells",
    "Prepared Spells",
    "Known Spells",
    "Always Prepared Spells",
    "Cantrips From Other Sources",
    "Free Casts Per Long Rest",
)

# The book's *current* loadout. Deliberately NOT excluded: the book is conjured
# freshly each rest and its picks are not permanent, so re-picking the same spell is
# legal. Treating it as known would also let this tool's own previous answer
# permanently constrain the next one.
CURRENT_BOOK_FIELDS = (
    "Book of Shadows Cantrips",
    "Book of Shadows Rituals",
)

# Human-readable labels for the per-source breakdown in the prompt. Kept next to the
# field list they annotate so the two cannot drift apart.
KNOWN_SOURCE_LABELS = {
    "Known/Prepared Base Spells": "Warlock picks",
    "Always Prepared Spells": "always prepared (patron, species or subclass)",
    "Cantrips From Other Sources": "from species, background or feats",
    "Free Casts Per Long Rest": "free casts per long rest",
}


class CharacterNotFound(FileNotFoundError):
    """Raised when no sheet matches the requested name."""


def format_character(data: dict) -> str:
    """Render a parsed character sheet as the plain-text block the prompt expects."""
    lines = []
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        lines.append(f"{str(key).replace('_', ' ').title()}: {value}")
    return "\n".join(lines)


def load_character_data(name: str, characters_dir=None) -> dict:
    """Load ``<characters_dir>/<name>.yaml`` and return the parsed mapping.

    Name can be a bare stem (or 'data/characters/x.yaml') supplied by --character or
    the CHARACTER env var. Raises ``CharacterNotFound`` rather than exiting, so the
    caller chooses how to report it.
    """
    directory = config.resolve(characters_dir or config.CHARACTERS_DIR)
    path = directory / f"{Path(name).stem}.yaml"
    if not path.exists():
        available = sorted(p.stem for p in directory.glob("*.yaml"))
        raise CharacterNotFound(
            f"No character sheet at '{path}'. Available: {', '.join(available) or '(none)'}"
        )

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise CharacterNotFound(f"Could not parse '{path}': {e}") from e

    if not isinstance(data, dict):
        raise CharacterNotFound(f"'{path}' must contain a mapping of sheet fields.")
    return data


def load_character(name: str, characters_dir=None) -> str:
    """Load a character sheet and return it as prompt-ready text."""
    return format_character(load_character_data(name, characters_dir))


def first_present(data: dict, *keys):
    """Return the first non-empty value among ``keys`` (sheets vary in casing)."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def character_name(data: dict) -> str:
    """The sheet's `Name`, or 'unknown' so a cache key is always formable."""
    return str(first_present(data, "Name", "name") or "unknown")


def character_level(data: dict) -> int | None:
    """Extract the character's level, tolerating the label variants sheets use."""
    raw = first_present(data, "Current Level", "current_level", "Level", "level")
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    match = re.search(r"\d+", str(raw))
    return int(match.group(0)) if match else None


def split_names(value) -> list[str]:
    """Split a sheet field like 'Eldritch Blast, Minor Illusion' into names.

    A trailing parenthetical is dropped, because sheets record the source there
    ('Light (Aasimar)') and it is not part of the spell's name. Typographic
    apostrophes are folded to ASCII so a hand-written sheet still matches the corpus.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = re.split(r"[,;]", str(value))
    names = []
    for item in items:
        name = re.sub(r"\s*\([^)]*\)\s*$", "", str(item)).strip().translate(APOSTROPHES)
        if name:
            names.append(name)
    return names


def known_spells(data: dict) -> list[str]:
    """Spells the character permanently has, from every field that grants one.

    This is deliberately a union rather than a single lookup. A real sheet spreads its
    spells across several fields: Warlock picks under 'Known/Prepared Base Spells',
    patron and Aasimar grants under 'Always Prepared Spells', and racial or feat
    cantrips under 'Cantrips From Other Sources'. Reading only the first field leaves
    'Light' and 'Sacred Flame' in the pool for a Celestial Warlock who always has both,
    so the model is invited to spend a book pick on a spell it already has.
    """
    names: list[str] = []
    for field in KNOWN_SPELL_FIELDS:
        names.extend(split_names(data.get(field)))
    # Order-preserving dedupe; the sheet repeats these across fields.
    return list(dict.fromkeys(names))


def current_book_spells(data: dict) -> list[str]:
    """The book's current loadout, for context only - these stay eligible."""
    names: list[str] = []
    for field in CURRENT_BOOK_FIELDS:
        names.extend(split_names(data.get(field)))
    return list(dict.fromkeys(names))


def max_spell_level(data: dict) -> int | None:
    """Highest spell level the character can cast, inferred from class and level.

    Warlocks have a single slot level, so this both describes every slot and caps which
    spells are worth recommending.
    """
    cls = str(first_present(data, "Class", "class") or "").lower()
    level = character_level(data)
    if level is None:
        return None
    if "warlock" in cls:
        # 2024 Warlock slot level: 1 (L1-2), 2 (L3-4), 3 (L5-6), 4 (L7-8), 5 (L9+).
        return min(5, max(1, (level + 1) // 2))
    # Other classes have a genuine spread; full-caster progression is the best
    # available approximation and is only used to bound recommendations.
    return min(9, max(1, (level + 1) // 2))
