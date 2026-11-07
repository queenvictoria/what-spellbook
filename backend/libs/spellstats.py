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

# --- scaling to the character's level ---

# The run-in label that states how a cantrip changes as its caster levels up. It is
# italicised, and the corpus bolds its italics, so the emphasis is optional on both sides.
_UPGRADE_LABEL = re.compile(r"Cantrip Upgrade\.?[\*_]*\s*(.+?)(?:\n\s*\n|\Z)", re.S)

# The corpus writes the same sentence as a bare paragraph with no label, so the label
# cannot be the only way in. A paragraph qualifies when it states a level and a value *and*
# says something increases - which is what separates a scaling sentence from any other
# sentence that happens to mention a level.
_SCALING_VERB = re.compile(
    r"\b(increases?|changes?|doubles?|deals?[ \t]+extra|additional)\b", re.IGNORECASE
)

# A slot-scaled paragraph is not a level-scaled one, and the corpus writes it without a
# label too. Excluded by name rather than by shape, because the two are otherwise alike.
_SLOT_PHRASE = re.compile(r"spell[ \t]+slot", re.IGNORECASE)

# The first entry of a scaling list, which is the only one that names the level:
# `levels 5 (2d10)` in the SRD, `5th level (2d6)` in the corpus. The rest of the list is
# bare numbers - `, 11 (3d10), and 17 (4d10)` - so it is read separately, from the text
# after this match. Reading only this pattern is the bug that made every cantrip report
# its level 5 value at every level.
_LEVEL_HEAD = re.compile(r"levels?\s+(\d+)\s*\(([^)]+)\)", re.IGNORECASE)

# The remaining entries of the list: `11 (3d10)`, `and 17 (4d10)`. The value is whatever
# the file put in the parentheses, so a die, a die count, a distance and a duration all
# read the same way - and the inner `or` of "2d8 or 2d12" is kept, because a spell that
# deals one of two amounts deals one of two amounts.
_LEVEL_TAIL = re.compile(r"(\d+)\s*\(([^)]+)\)")

# `5th level` -> `level 5`, so the corpus's ordinal phrasing reads as the SRD's.
_ORDINAL_LEVEL = re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+levels?\b", re.IGNORECASE)

# A level named together with the value it grants: `levels 5 (2d10)`, `5th level (2d6)`.
# The parenthetical is what makes this a scaling sentence rather than any other sentence
# that mentions a level - "regains hit points from a spell of 1st level or higher" names a
# level and grants nothing at it, and reading that as scaling would put a note on a spell
# that does not scale.
_LEVEL_VALUE = re.compile(
    r"(?:levels?\s+\d+|\d+(?:st|nd|rd|th)\s+levels?)\s*\([^)]+\)",
    re.IGNORECASE,
)

# `at 5th level` - the corpus's prose form, which states a level and no value in
# parentheses. It is a scaling sentence when something also increases, and the two
# together are what the gate below requires.
_AT_ORDINAL_LEVEL = re.compile(r"\bat\s+(\d+)(?:st|nd|rd|th)\s+levels?\b", re.IGNORECASE)

# `two beams at level 5, three beams at level 11` - Eldritch Blast's shape, and the only
# spell that uses it. The value is the phrase before "at level", kept whole rather than
# reduced to a number: "two beams" is what the reader wants to see. At most two words, so
# the sentence's verb ("The spell creates two beams") is not swept into the value.
_AT_LEVEL = re.compile(
    r"([A-Za-z][A-Za-z'\u2019-]*(?:[ \t]+[A-Za-z][A-Za-z'\u2019-]*)?)"
    r"[ \t]+at[ \t]+level[ \t]+(\d+)",
    re.IGNORECASE,
)

# What the scaling is *of*, longest first so "damage die" is not read as "damage". The
# subject is taken from the sentence rather than assumed, because the same shape states a
# die, a range and a duration - and "30 feet damage" would be nonsense.
_SCALING_SUBJECTS = (
    "damage die",
    "damage",
    "range",
    "duration",
    "hit points",
    "beams",
    "targets",
    "creatures",
)

# The number words the SRD spells out. Only the ones a scaling sentence uses.
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}

# A leading conjunction or article left over from the sentence's list: "and four beams".
_LEADING_FILLER = re.compile(r"^(?:and|or|the|an|a)\s+", re.IGNORECASE)

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


def scaling(text: str, level: int | None) -> str | None:
    """What ``text`` says the spell does at ``level``, or ``None`` if it says nothing.

    A spell's text states its scaling at fixed levels - "two beams at level 5", "the
    damage increases by 1d8 when you reach levels 5 (2d8), 11 (3d8), and 17 (4d8)" - and
    a reader at the table wants the row that applies to *them*, not the table. So this
    reads the value for the character's own level back out of the sentence.

    Deterministic, and deliberately so: every value returned is one the file already
    wrote, and a level the file does not mention returns ``None`` rather than the nearest
    one. A cantrip at level 3 has no upgrade, and showing it the level 5 row would state
    a number the character cannot cast yet.

    The label is the *character's* level, not the level the value was stated at, because
    the note answers "what does this do for me". A level 10 caster is shown the level 5
    row labelled ``(L10)``, which is what they deal - labelling it ``(L5)`` would read as
    a level they are not.

    ``None`` also for a spell that scales by *slot* rather than by level. A Warlock's
    slots are all one level, so "for each slot level above 3rd" has a single answer for
    them and it is the spell's own text - there is nothing to contextualise.
    """
    if level is None:
        return None

    sentence = _scaling_sentence(text)
    if sentence is None:
        return None

    pairs = _level_pairs(sentence)
    if pairs:
        value = _value_at(pairs, level)
        if value:
            subject = _scaling_subject(sentence)
            # "range 30 feet" reads as a range; "2d8 damage" reads as damage. The subject
            # is the file's own word, so neither is invented.
            if subject == "range":
                return f"range {_digits(value)} (L{level})"
            return f"{_digits(value)} {subject} (L{level})"

    # Eldritch Blast's shape: the value is the phrase before "at level", kept whole
    # because "two beams" is the answer and "2" is not.
    at_level = [(int(n), value.strip()) for value, n in _AT_LEVEL.findall(sentence)]
    if at_level:
        value = _value_at(at_level, level)
        if value:
            return f"{_digits(_LEADING_FILLER.sub('', value))} (L{level})"

    return None


def scaling_needs_reading(text: str, level: int | None) -> bool:
    """Whether ``text`` states a level-based change this module could not read.

    The gate for asking a model instead, and it is deliberately narrow. A spell that never
    mentions a level cannot scale with one, and a spell whose scaling this module *did*
    read needs no help - so only the gap between the two costs a model call. Gating on
    "mentions a level" alone would spend one on every levelled spell in the corpus, since
    the header line names the spell's own level.
    """
    if level is None:
        return False
    sentence = _scaling_sentence(text)
    if sentence is None:
        return False
    # Below the first level the sentence states there is nothing to state, so there is
    # nothing to ask about either - a level 3 caster's Booming Blade has not changed.
    stated = _stated_levels(sentence)
    if stated and level < min(stated):
        return False
    return scaling(text, level) is None


def _stated_levels(sentence: str) -> list[int]:
    """Every level a scaling sentence names, in any of the three phrasings."""
    levels = [int(n) for n, _value in _LEVEL_HEAD.findall(sentence)]
    levels += [int(n) for n, _value in _LEVEL_TAIL.findall(sentence)]
    levels += [int(n) for n in _ORDINAL_LEVEL.findall(sentence)]
    levels += [int(n) for n in _AT_ORDINAL_LEVEL.findall(sentence)]
    levels += [int(n) for _value, n in _AT_LEVEL.findall(sentence)]
    return levels


def _scaling_sentence(text: str) -> str | None:
    """The paragraph stating how the spell scales with level, or ``None``.

    The labelled paragraph is preferred, because it is unambiguous. The corpus omits the
    label on 4 of its cantrips, so a bare paragraph is accepted too - but only when it
    states a level and a value and says something increases, which is what keeps an
    ordinary sentence that mentions a level out of this.
    """
    labelled = _UPGRADE_LABEL.search(text)
    if labelled:
        return labelled.group(1)

    for paragraph in re.split(r"\n\s*\n", text):
        if _SLOT_PHRASE.search(paragraph):
            continue
        if not _SCALING_VERB.search(paragraph):
            continue
        if _LEVEL_VALUE.search(paragraph) or _AT_ORDINAL_LEVEL.search(paragraph):
            return paragraph
    return None


def _level_pairs(sentence: str) -> list[tuple[int, str]]:
    """Every ``(level, value)`` a scaling sentence states, in the order it states them.

    The list is written with the level named once and then implied - "levels 5 (2d10),
    11 (3d10), and 17 (4d10)" - so the first entry is read with its label and the rest are
    read as bare numbers from the text that follows. Reading only the labelled form is what
    made every cantrip report its level 5 value at level 11 and 17 as well.
    """
    head = _LEVEL_HEAD.search(sentence)
    if head:
        pairs = [(int(head.group(1)), head.group(2).strip())]
        pairs += [
            (int(level), value.strip())
            for level, value in _LEVEL_TAIL.findall(sentence[head.end():])
        ]
        return pairs

    # The corpus's ordinal phrasing, `5th level (2d6), 11th level (3d6)`, names every
    # level, so each entry is read with its own label.
    normalised = _ORDINAL_LEVEL.sub(r"level \1", sentence)
    return [
        (int(level), value.strip())
        for level, value in _LEVEL_HEAD.findall(normalised)
    ]


def _value_at(pairs: list[tuple[int, str]], level: int) -> str | None:
    """The value for the highest stated level at or below ``level``.

    ``None`` when the character is below the first stated level, which is the honest
    answer for a cantrip that has not upgraded yet.
    """
    applicable = [value for stated, value in sorted(pairs) if stated <= level]
    return applicable[-1] if applicable else None


def _scaling_subject(sentence: str) -> str:
    """What the scaling sentence is about, in the file's own words."""
    lowered = sentence.lower()
    for subject in _SCALING_SUBJECTS:
        if subject in lowered:
            return subject
    return "damage"


def _digits(value: str) -> str:
    """``two beams`` -> ``2 beams``. A value already in digits is left alone."""
    head, _, rest = value.partition(" ")
    return f"{_NUMBER_WORDS.get(head.lower(), head)}{' ' + rest if rest else ''}"


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
