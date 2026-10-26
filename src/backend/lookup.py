"""Answer factual questions about a character sheet without calling a model.

Two kinds of question look identical at the prompt but are not:

* **A number the sheet already records** - "what's my passive perception?", "what's my
  spell save DC?". These have exactly one right answer and it is already in the YAML.
  Sending them to a model is slower, costs money, and introduces a chance of being
  wrong about a fact we hold verbatim. They are answered here, deterministically.
* **A question *about* the sheet** - "why do I have two Light spells?", "where does my
  +7 spell attack come from?". These need the sheet read and reasoned over. The answer
  is still grounded in the sheet, but it is not a lookup, so the caller falls back to
  the model (see ``service.ask_character``).

This module is the first half only: it either returns an answer with its evidence, or
``None`` to mean "not a lookup, ask the model". Returning None is a normal outcome, not
a failure - a miss must not be reported as "no such value on your sheet".

Nothing here imports the vector store or a model, so it is fast, testable and safe to
call from an API request.
"""

from __future__ import annotations

import re

from . import characters

# Sheet fields that are prose rather than a single number, so a match must quote them
# instead of parsing them. "Passive Scores" is 'Perception 12, Insight 15'.
_MULTI_VALUE = re.compile(r"([A-Za-z][A-Za-z ']*?)\s+(-?\d+)")

# Synonyms a player types -> the sheet key that holds the answer. Ordered longest-first
# at match time, because "spell save dc" must win over "spell save".
ALIASES: dict[str, tuple[str, ...]] = {
    "ac": ("ac", "armour class", "armor class"),
    "hp": ("hp", "hit points", "health", "max hp"),
    "proficiency bonus": ("proficiency bonus", "proficiency", "prof bonus", "prof"),
    "spell save dc": ("spell save dc", "save dc", "spell dc", "ssdc", "dc"),
    "spell attack": ("spell attack bonus", "spell attack", "spell attack mod",
                     "spellcasting attack"),
    "initiative": ("initiative", "initiative bonus", "init"),
    "speed": ("speed", "movement", "walk speed"),
    "level": ("level", "character level", "class level"),
    "hit dice": ("hit dice", "hit die", "hd"),
    "darkvision": ("darkvision", "senses"),
    "passive perception": ("passive perception", "perception", "passive wisdom"),
    "passive insight": ("passive insight", "insight"),
    "passive investigation": ("passive investigation", "investigation"),
    "spellcasting ability": ("spellcasting ability", "spell casting ability",
                             "casting ability", "spellcasting mod"),
    "class": ("class", "classes"),
    "subclass": ("subclass", "patron"),
    "species": ("species", "race"),
    "background": ("background",),
    "pact": ("pact", "pact boon"),
    "alignment": ("alignment",),
    "party": ("party", "the party"),
    "languages": ("languages", "language"),
}

# Ability scores and saves are asked about as a family ("my dex save", "strength score").
_ABILITY_WORDS = {
    "str": "STR", "strength": "STR",
    "dex": "DEX", "dexterity": "DEX",
    "con": "CON", "constitution": "CON",
    "int": "INT", "intelligence": "INT",
    "wis": "WIS", "wisdom": "WIS",
    "cha": "CHA", "charisma": "CHA",
}


def _clean(text: str) -> str:
    return " ".join(str(text).lower().split()).strip(" ?.!")


def _find_key(data: dict, *names: str):
    """Case-insensitive sheet lookup, tolerating underscores for spaces."""
    lowered = {str(k).lower().replace("_", " "): k for k in data}
    for name in names:
        key = lowered.get(name.lower())
        if key is not None:
            return key, data[key]
    return None, None


def _answer_from_field(data: dict, field: str) -> str | None:
    """The value of a whole sheet field, e.g. 'Spell Save DC' -> '15'."""
    _, value = _find_key(data, field)
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value).strip()


def _lookup_in_passives(data: dict, which: str) -> str | None:
    """Pull one score out of a combined field like 'Perception 12, Insight 15'."""
    for field in ("Passive Scores", "Passives"):
        _, value = _find_key(data, field)
        if not value:
            continue
        for label, number in _MULTI_VALUE.findall(str(value)):
            if which in _clean(label):
                return number
    return None


def _parse_pairs(value) -> dict[str, tuple[str, str]]:
    """Parse 'STR 8 (-1), DEX 14 (+2)' into {'STR': ('8', '-1'), ...}.

    Sheets record the score and the modifier together and label neither, so both are
    kept: which one is wanted depends on the question, and guessing for the caller
    produces a confidently wrong number.
    """
    pairs: dict[str, tuple[str, str]] = {}
    for chunk in re.split(r"[,;]", str(value or "")):
        chunk = chunk.strip()
        if not chunk:
            continue
        label = chunk.split()[0].strip(":")
        numbers = re.findall(r"[+-]?\d+", chunk)
        if label and numbers:
            score = numbers[0]
            modifier = numbers[1] if len(numbers) > 1 else numbers[0]
            pairs[label.upper()] = (score, modifier)
    return pairs


def _lookup_ability(data: dict, field: str, ability: str, *, want_modifier: bool):
    """One ability's score or modifier out of 'STR 8 (-1), DEX 14 (+2)'."""
    _, value = _find_key(data, field)
    if not value:
        return None
    pairs = _parse_pairs(value)
    entry = pairs.get(ability.upper())
    if entry is None:
        return None
    score, modifier = entry
    return modifier if want_modifier else score


def _lookup_save(data: dict, ability: str):
    """One save bonus, plus its '(proficient)' annotation when the sheet has one."""
    _, value = _find_key(data, "Saving Throws")
    if not value:
        return None
    for chunk in re.split(r"[,;]", str(value)):
        chunk = chunk.strip()
        if not chunk:
            continue
        label = chunk.split()[0].strip(":").upper()
        if label != ability.upper():
            continue
        numbers = re.findall(r"[+-]?\d+", chunk)
        if not numbers:
            return None
        note = " (proficient)" if "proficient" in chunk.lower() else ""
        return f"{numbers[0]}{note}"
    return None


def sheet_keys() -> list[str]:
    """Every alias a caller can ask about, for help text and error messages."""
    return sorted(set(ALIASES) | {"ability", "save"})


# Framing that asks *why* rather than *what*. A lookup returns a value, so answering
# "where does my +7 come from?" with the number alone answers a different question -
# those go to the model, which can explain the derivation from the sheet.
_EXPLANATORY = re.compile(
    r"\b(why|how\s+come|where\s+does|where\s+do|where\s+did|explain|derived?|"
    r"calculated?|work(?:s|ed)?\s+out|come\s+from|comes\s+from)\b",
    re.IGNORECASE,
)


def answer(question: str, sheet: dict) -> dict | None:
    """Answer ``question`` from ``sheet``, or return None to defer to the model.

    Returns ``{"answer", "source", "field"}`` so a caller can show the evidence: a
    number quoted from a sheet field is only trustworthy if the user can see where it
    came from.

    An explanatory question ("why", "where does X come from") always defers, even when
    the field exists, because the answer is a reason rather than a number.
    """
    if not sheet:
        return None
    asked = _clean(question)
    if not asked or _EXPLANATORY.search(asked):
        return None

    # --- ability scores and saving throws: "dex", "my dex save", "strength score" ---
    ability = None
    for word, short in _ABILITY_WORDS.items():
        if re.search(rf"\b{word}\b", asked):
            ability = short
            break
    if ability:
        wants_save = bool(re.search(r"\b(save|saving|saves|throw|throws)\b", asked))
        if wants_save:
            found = _lookup_save(sheet, ability)
            if found is not None:
                return {"answer": found, "source": f"{ability} saving throw",
                        "field": "Saving Throws"}
        else:
            # "DEX modifier" is the modifier; a bare "DEX" is the score, which is what a
            # player reads off the sheet.
            wants_modifier = bool(re.search(r"\b(mod|modifier|bonus)\b", asked))
            found = _lookup_ability(
                sheet, "Ability Scores", ability, want_modifier=wants_modifier
            )
            if found is not None:
                label = "modifier" if wants_modifier else "score"
                return {"answer": found, "source": f"{ability} {label}",
                        "field": "Ability Scores"}

    # --- a named score such as passive perception ---
    for key, aliases in ALIASES.items():
        # Longest alias first, so "spell save dc" is not matched as "dc".
        for alias in sorted(aliases, key=len, reverse=True):
            if not re.search(rf"\b{re.escape(alias)}\b", asked):
                continue
            if key.startswith("passive "):
                which = key.split(" ", 1)[1]
                found = _lookup_in_passives(sheet, which)
                if found is not None:
                    return {"answer": found, "source": f"passive {which}",
                            "field": "Passive Scores"}
                continue

            field = {
                "ac": "Armor Class",
                "hp": "Hit Points",
                "proficiency bonus": "Proficiency Bonus",
                "spell save dc": "Spell Save DC",
                "spell attack": "Spell Attack Bonus",
                "speed": "Speed",
                "hit dice": "Hit Dice",
                "darkvision": "Senses",
                "spellcasting ability": "Spellcasting Ability",
                "class": "Class",
                "subclass": "Subclass",
                "species": "Species",
                "background": "Background",
                "pact": "Pact",
                "alignment": "Alignment",
                "party": "Party",
                "languages": "Languages",
                "level": "Current Level",
            }.get(key)
            if field is None:
                continue
            found = _answer_from_field(sheet, field)
            if found is not None:
                return {"answer": found, "source": key, "field": field}
    return None


def _spell_sources(sheet: dict) -> dict[str, list[str]]:
    """Spell name -> the sheet fields that grant it, for "why do I have two?"."""
    sources: dict[str, list[str]] = {}
    for field in characters.KNOWN_SPELL_FIELDS + characters.CURRENT_BOOK_FIELDS:
        _, value = _find_key(sheet, field)
        for name in characters.split_names(value):
            sources.setdefault(name.lower(), []).append(field)
    return sources


def spell_origins(sheet: dict, name: str) -> list[str]:
    """Which sheet fields grant ``name``. More than one explains a duplicate.

    Answering this from the sheet rather than the model matters: the question "why do I
    have two Light spells?" has a factual answer in the YAML, and a model asked it
    generically will invent a plausible-sounding rule instead.
    """
    return _spell_sources(sheet).get(_clean(name), [])
