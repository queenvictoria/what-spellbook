"""Read a spell's stat block out of its own quoted text.

A spell is rendered from a vendored file, so its words are the SRD's and cannot be a
paraphrase. What the file does *not* carry is anything the reader has to already know: `V`
is Verbal only if you have memorised the Components rule, and the damage is buried in the
description's second paragraph where it is the single most important number on the page.

So this reads the stats back *out* of the text rather than adding them to it. Nothing here
decides what a spell does - every value is the one the file already wrote, and a field the
file omits stays absent. That is the same bargain :func:`normalise_corpus_spell` makes: it
may rewrite presentation, never a number.

Returning ``None`` when the text has no stat block is deliberate and load-bearing. An
Eldritch Invocation is a class feature quoted through the same card, and giving it a strip
of empty tiles would present a spell's shape for something the rules say is not a spell.
"""

from __future__ import annotations

import re

# What the component letters stand for. `R` is absent because the 2024 rules dropped it -
# a spell's component is Verbal, Somatic or Material, and the SRD writes nothing else.
COMPONENT_MEANINGS = {
    "V": "Verbal",
    "S": "Somatic",
    "M": "Material",
}

# The 13 damage types. Needed to tell a damage expression from the other dice a spell
# rolls, which are common and mean something else: a save's `1d4`, a healing spell's
# `2d8`, `1d20` on a table. Only "NdN <type> damage" is a damage roll, and the type is what
# proves it.
DAMAGE_TYPES = (
    "Acid",
    "Bludgeoning",
    "Cold",
    "Fire",
    "Force",
    "Lightning",
    "Necrotic",
    "Piercing",
    "Poison",
    "Psychic",
    "Radiant",
    "Slashing",
    "Thunder",
)

_DAMAGE_TYPE_ALTERNATION = "|".join(DAMAGE_TYPES)
_TYPE = f"(?:{_DAMAGE_TYPE_ALTERNATION})"
# "Acid", "Acid, Cold, Fire, Lightning, or Thunder". The separator is either a comma with
# an optional conjunction or a bare conjunction, because the SRD writes both.
_TYPE_LIST = rf"{_TYPE}(?:[ \t]*(?:,[ \t]*(?:(?:and|or)[ \t]+)?|(?:and|or)[ \t]+){_TYPE})*"

# `**Casting Time:** Action`. The field name is captured rather than a fixed list so an
# unknown field is noticed and ignored, not mistaken for prose. `Component` (singular)
# appears on 12 spells and is the same field.
_STAT_LINE = re.compile(r"^\*\*([A-Za-z][A-Za-z ]*):\*\*[ \t]*(.+?)[ \t]*$", re.MULTILINE)

# A damage roll, in the three shapes the SRD writes one. The modifier is kept because it is
# part of the roll, and the type list is kept whole because a spell that deals "Acid, Cold,
# Fire, Lightning, or Thunder" deals any one of them, not five.
#
# The third shape - `3d8 damage of the chosen type` - has no type word at all, and is why
# the type cannot simply be required. It is Chromatic Orb and Sorcerous Burst, where the
# caster picks the type at cast time; guessing one would be inventing a fact.
#
# `<dice> damage` is accepted as an alternative to `<dice> <type> damage` rather than as a
# separate pattern, because the two overlap: "5d8 Acid, Cold, ... damage" starts a type list
# and "3d8 damage" does not, and one alternation reads that better than two passes whose
# results then have to be reconciled.
_DAMAGE = re.compile(
    rf"(\d+d\d+(?:[ \t]*[+-][ \t]*\d+)?)[ \t]*"
    rf"(?:({_TYPE_LIST})[ \t]*)?damage\b",
    re.IGNORECASE,
)

# The same roll stated as a count of dice: `1 Fire damage` per beam, `1 Radiant damage` per
# creature at the start of its turn. A die count of 1 is normally written without the `1`,
# and the SRD does write `1d6`, so this form is only ever a *quantity* - the number is how
# many dice. Reporting it as `1d6` would state a roll the file never wrote.
#
# The lookbehinds are the whole reason this cannot be a bare `\b(\d+)`.
#
# `[+\-]` excludes a dice roll's flat bonus: Disintegrate is `10d6 + 40 Force damage` and
# Finger of Death is `7d8 + 30 Necrotic damage`, so without it the card would show a second
# entry of `40x Force` for a number that is part of the first roll.
#
# `at least` excludes a threshold. Prismatic Wall says a layer "is destroyed if it takes at
# least 60 Force damage", which is a condition on damage the layer receives - not damage the
# spell deals - and the card would otherwise list 60 Force among the spell's own effects.
_FIXED_DAMAGE = re.compile(
    rf"(?<![+\-][ \t])(?<![+\-])(?<!at least )(?<!at least)\b(\d+)[ \t]+"
    rf"({_TYPE_LIST})[ \t]+damage\b",
    re.IGNORECASE,
)

# The parenthetical that says what the M component is: `M (a ball of bat guano and sulfur)`.
_MATERIAL = re.compile(r"\(([^)]*)\)")

# The letters before the parenthetical, so a material that happens to contain a capital V,
# S or M cannot be read as a component. "a Mix of vinegar" would otherwise yield an extra M.
_COMPONENT_LETTER = re.compile(r"\b([VSM])\b")


def components(raw: str) -> dict | None:
    """A components line, expanded. ``None`` if the line names no letters.

    `V, S, M (a bit of fleece)` is shorthand that assumes the reader knows the rule. The
    letters are expanded here because that is the whole ask - but the material is left
    exactly as the file wrote it, because *which* material is the part a component pouch
    decides, and "a bit of fleece" is not something to summarise.

    Only the part before the parenthetical is scanned for letters, so a material can never
    contribute one by accident.
    """
    material = _MATERIAL.search(raw)
    letters_part = raw[: material.start()] if material else raw

    letters: list[str] = []
    for match in _COMPONENT_LETTER.finditer(letters_part):
        letter = match.group(1)
        if letter not in letters:
            letters.append(letter)
    if not letters:
        return None

    extracted = material.group(1).strip() if material else ""
    return {
        "letters": letters,
        # `V (Verbal), S (Somatic)`. Keyed off :data:`COMPONENT_MEANINGS` so the two cannot
        # disagree about what a letter means.
        "expanded": ", ".join(f"{letter} ({COMPONENT_MEANINGS[letter]})" for letter in letters),
        "material": extracted or None,
        # Worth calling out: a consumed component with a GP cost is the reason a spell can
        # cost money to cast, which is a material fact a recommendation should respect.
        "consumed": "consumes" in extracted.lower(),
    }


def damage(text: str) -> list[dict]:
    """Every damage amount the spell states, in the order it states them.

    Two forms are read, and both require the word "damage":

    - ``8d6 Fire damage`` - a dice roll, with or without a type and with or without a
      modifier. The great majority of spells.
    - ``3d8 damage of the chosen type``, ``1 Fire damage`` - a roll whose type the caster
      chooses, or a count of separate instances. The type is left absent rather than
      guessed, because which one it is depends on a choice the file does not make.

    Requiring "damage" is what keeps the other dice a spell rolls out of this list. They are
    common and they mean something else: an amount of healing (`2d8` in Cure Wounds), a
    saving throw's duration, a `d20` on a table, `1d6` for a random direction in Blink.
    Reading any of those as damage would put a number on the card that is not the spell's
    damage, which is worse than the field being empty.

    Duplicates collapse, and that is a correctness fix rather than tidying: Searing Smite
    states `1d6 Fire` twice - once for the hit and once for the repeat - and a reader shown
    both would reasonably conclude 2d6.

    A multi-type roll is one entry naming all of its types, not one per type. Glyph of
    Warding deals ``5d8 Acid, Cold, Fire, Lightning, or Thunder`` and deals one of them, so
    five entries would claim five times the damage.
    """
    found: dict[tuple[str, str], dict] = {}

    for match in _DAMAGE.finditer(text):
        dice, types = match.group(1), match.group(2)
        # A roll with no type word at all may still be the first half of a roll whose type
        # the caster picks later in the sentence: "3d8 damage of the chosen type", "1d8
        # damage of a type you choose", "1d6 damage of the type in parentheses". All three
        # read `damage of ...`, which is the shape to match on - the phrasings differ, and a
        # list of them would go stale. Recording it is the difference between "the type is a
        # choice" and "the type is unknown", and those are not the same answer.
        chosen = not types and bool(re.match(r"\s*of\b", text[match.end():]))
        key = (dice.replace(" ", ""), types or "")
        found.setdefault(key, {
            "dice": dice.replace(" ", ""),
            "types": _split_types(types) if types else [],
            "chosen_type": chosen,
        })

    for match in _FIXED_DAMAGE.finditer(text):
        count, types = match.group(1), match.group(2)
        key = (f"{count}x", types)
        found.setdefault(key, {
            # `2x` reads as "two instances", which is what the file states - as opposed to
            # `2d6`, which is a roll of two dice that the file does not state.
            "dice": f"{count}x",
            "types": _split_types(types),
            "chosen_type": False,
        })

    return list(found.values())


def _split_types(raw: str) -> list[str]:
    """`Acid, Cold, Fire, Lightning, or Thunder` -> the five names.

    Split on the separators rather than on the commas: the last pair in a list is joined by
    "or" or "and" and may have no comma between them at all,
    so a comma split would leave "or Thunder" as a type.
    """
    return [part for part in re.split(r"[ \t]*(?:,[ \t]*|(?:and|or)[ \t]+)", raw) if part]


def attach(spell: dict | None) -> dict | None:
    """``spell`` with its stat block added under ``stats``.

    The caller has already read the text out of a file; this adds the reading of it. Kept
    here rather than in the route so the HTTP layer stays a transport, and kept separate
    from :func:`parse` so the parser can be tested on a string alone.
    """
    if spell is None:
        return None
    return {**spell, "stats": parse(spell.get("text", ""))}


def parse(text: str) -> dict | None:
    """The stat block in ``text``, or ``None`` if it does not have one.

    ``None`` for anything that is not a spell - an invocation, most importantly, which is
    quoted through the same card. The gate is Casting Time, which all 339 SRD spells have
    and which nothing else writes in this format.
    """
    fields: dict[str, str] = {}
    for match in _STAT_LINE.finditer(text):
        # Several spells write `**Component:**` (singular). Folding the two here keeps the
        # rest of the function reading one name.
        name = "Components" if match.group(1).strip().lower().startswith("component") else match.group(1).strip()
        fields.setdefault(name, match.group(2).strip())

    casting_time = fields.get("Casting Time")
    if not casting_time:
        return None

    duration = fields.get("Duration", "")
    return {
        "casting_time": casting_time,
        # A ritual takes 10 minutes longer to cast, which is a decision at the table rather
        # than a footnote, so it is a flag and not something to re-parse out of the string.
        "ritual": "ritual" in casting_time.lower(),
        "range": fields.get("Range"),
        "components": components(fields["Components"]) if fields.get("Components") else None,
        "duration": duration or None,
        # Concentration is the single most consequential thing about a spell for a caster
        # who can only hold one, so it is stated rather than left inside the duration text.
        "concentration": duration.lower().startswith("concentration"),
        "damage": damage(text),
    }
