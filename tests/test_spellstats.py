"""Reading a spell's stats back out of its own text.

The point of this module is that it never decides anything - every value it returns is one
the vendored file already wrote. So the tests are mostly about *not* inventing values:
a field the file omits stays absent, dice that are not damage stay out of the damage list,
and a flat bonus belonging to a roll is not reported as a roll of its own.

That last one is a real bug this file caught. Disintegrate is `10d6 + 40 Force damage`, and
a bare "number followed by a type and the word damage" pattern reads the `40` as five
damage dice - a second entry on the card for a number that is part of the first.
"""

from __future__ import annotations

import re

from backend.libs import rules, spellstats


def stat_block(**fields: str) -> str:
    """A minimal spell body with only the fields given, in the vendored file's shape."""
    return "\n".join(f"**{name}:** {value}" for name, value in fields.items())


# --- components -----------------------------------------------------------------


def test_component_letters_are_expanded():
    parsed = spellstats.components("V, S, M (a bit of fleece)")
    assert parsed["letters"] == ["V", "S", "M"]
    assert parsed["expanded"] == "V (Verbal), S (Somatic), M (Material)"
    assert parsed["material"] == "a bit of fleece"


def test_the_material_is_kept_verbatim():
    """Which material decides whether a pouch covers the spell, so it is not summarised."""
    material = "diamond dust worth 100+ GP, which the spell consumes"
    parsed = spellstats.components(f"V, S, M ({material})")
    assert parsed["material"] == material
    assert parsed["consumed"] is True


def test_a_material_cannot_contribute_a_component_letter():
    """Only the part before the parenthetical is scanned - a material is prose, not markup.

    "a Mix of vinegar" starts with the letter M, and reading that as Material would put a
    component on the card that the spell does not have.
    """
    parsed = spellstats.components("V, S, M (a Mix of vinegar and honey)")
    assert parsed["letters"] == ["V", "S", "M"]


def test_a_purely_material_spell_reports_material_only():
    parsed = spellstats.components("M (a pinch of sand)")
    assert parsed["letters"] == ["M"]
    assert parsed["material"] == "a pinch of sand"


def test_a_line_naming_no_letters_is_none():
    assert spellstats.components("") is None


def test_letters_are_not_repeated():
    parsed = spellstats.components("V, V, S")
    assert parsed["letters"] == ["V", "S"]


# --- damage ---------------------------------------------------------------------


def test_a_typed_roll_is_read():
    assert spellstats.damage("takes 8d6 Fire damage") == [
        {"dice": "8d6", "types": ["Fire"], "chosen_type": False}
    ]


def test_a_flat_bonus_belongs_to_its_roll_and_is_not_a_second_one():
    """Disintegrate's `10d6 + 40 Force damage` is one roll, not a roll and a flat 40."""
    found = spellstats.damage("the target takes 10d6 + 40 Force damage.")
    assert len(found) == 1
    assert found[0]["dice"] == "10d6+40"
    assert found[0]["types"] == ["Force"]


def test_dice_without_the_word_damage_are_not_damage():
    """A save's dice, healing and a random table all look like a roll and are not one.

    Cure Wounds rolls `2d8` and deals no damage at all, so reporting it would put a damage
    number on a healing spell - worse than the field being empty.
    """
    assert spellstats.damage("regains a number of Hit Points equal to 2d8 plus your modifier") == []
    assert spellstats.damage("Roll 1d6 at the end of each of your turns") == []
    assert spellstats.damage("must make a Charisma saving throw, rolling 1d4") == []


def test_a_multi_type_roll_is_one_entry_naming_every_type():
    """Glyph of Warding deals one of five types, not all five - so not five entries."""
    found = spellstats.damage("takes 5d8 Acid, Cold, Fire, Lightning, or Thunder damage")
    assert len(found) == 1
    assert found[0]["types"] == ["Acid", "Cold", "Fire", "Lightning", "Thunder"]


def test_a_chosen_type_is_marked_rather_than_left_empty():
    """Empty and "the caster picks" are different answers, and the card must say which."""
    for phrasing in (
        "takes 3d8 damage of the chosen type",
        "takes 1d8 damage of a type you choose: Acid, Cold, Fire",
        "it deals 1d6 damage of the type in parentheses",
    ):
        found = spellstats.damage(phrasing)
        assert len(found) == 1, phrasing
        assert found[0]["chosen_type"] is True, phrasing
        assert found[0]["types"] == []


def test_a_bare_roll_without_a_type_is_not_marked_as_chosen():
    """The reader must not be told a decision awaits when the text made none."""
    found = spellstats.damage("the target takes 1d8 damage.")
    assert found[0]["chosen_type"] is False


def test_a_count_of_instances_is_not_written_as_a_roll():
    """`takes 5 Cold damage` from five beams is 5 instances, not the roll `5d6`."""
    found = spellstats.damage("the creature takes 5 Cold damage")
    assert found == [{"dice": "5x", "types": ["Cold"], "chosen_type": False}]


def test_a_repeated_roll_is_reported_once():
    """Searing Smite states `1d6 Fire` twice, and showing both reads as 2d6."""
    found = spellstats.damage("takes 1d6 Fire damage ... and 1d6 Fire damage again")
    assert found == [{"dice": "1d6", "types": ["Fire"], "chosen_type": False}]


def test_two_different_rolls_are_both_reported():
    """Ice Storm deals both, and one is not a repeat of the other."""
    found = spellstats.damage("takes 2d10 Bludgeoning damage and 4d6 Cold damage")
    assert [entry["dice"] for entry in found] == ["2d10", "4d6"]


# --- the stat block -------------------------------------------------------------


def test_a_stat_block_is_parsed():
    parsed = spellstats.parse(stat_block(**{
        "Casting Time": "Action",
        "Range": "150 feet",
        "Components": "V, S",
        "Duration": "Instantaneous",
    }))
    assert parsed["casting_time"] == "Action"
    assert parsed["range"] == "150 feet"
    assert parsed["duration"] == "Instantaneous"
    assert parsed["ritual"] is False
    assert parsed["concentration"] is False


def test_text_with_no_casting_time_is_not_a_spell():
    """The card is shared with invocations, and a class feature must get no stat block.

    Casting Time is the gate because all 339 SRD spells have one and nothing else writes
    that line in this format.
    """
    assert spellstats.parse("_Prerequisite: Level 2+ Warlock_") is None
    assert spellstats.parse("") is None


def test_the_singular_component_spelling_is_read():
    """12 spells write `**Component:**` and mean the same field."""
    parsed = spellstats.parse(stat_block(**{"Casting Time": "Action", "Component": "V, S"}))
    assert parsed["components"]["letters"] == ["V", "S"]


def test_ritual_and_concentration_are_flags_not_prose():
    parsed = spellstats.parse(stat_block(**{
        "Casting Time": "Action or Ritual",
        "Duration": "Concentration, up to 1 minute",
    }))
    assert parsed["ritual"] is True
    assert parsed["concentration"] is True


def test_a_ritual_casting_time_keeps_its_condition():
    """`Bonus Action, which you take immediately after hitting...` is the whole rule."""
    long_form = "Bonus Action, which you take immediately after hitting a target with a Melee weapon"
    parsed = spellstats.parse(stat_block(**{"Casting Time": long_form, "Duration": "1 minute"}))
    assert parsed["casting_time"] == long_form
    assert parsed["ritual"] is False


def test_attach_leaves_a_missing_spell_alone():
    assert spellstats.attach(None) is None


def test_attach_does_not_mutate_its_input():
    spell = {"name": "X", "text": stat_block(**{"Casting Time": "Action"})}
    spellstats.attach(spell)
    assert "stats" not in spell


# --- against the real corpus -----------------------------------------------------


def test_every_spell_in_the_corpus_parses():
    """A stat line this file cannot read is a card that renders without its stats.

    The vendored corpus is the input this is written for, so every spell in it is checked
    rather than a sample: a pattern that handles the common case and silently drops the
    rest is exactly the failure that is invisible from the outside.
    """
    spells = _corpus_spells()
    assert len(spells) > 500

    unparsed, missing = [], []
    for name in spells:
        found = rules.find_spell(name)
        parsed = spellstats.parse(found["text"])
        if parsed is None:
            unparsed.append(name)
            continue
        for field in ("casting_time", "range", "duration"):
            if not parsed[field]:
                missing.append(f"{name}: {field}")

    assert unparsed == []
    assert missing == []


def test_the_flat_bonus_of_a_roll_is_never_its_own_entry():
    """The regression guard for the `10d6 + 40` bug, over the whole corpus.

    The signature is exact rather than a heuristic: every flat amount is preceded by `+` or
    `-` in the text it came from. Checking that is stronger than counting the entries, which
    would have failed on Earthquake - it genuinely deals a flat 50 Bludgeoning damage to a
    structure, so a threshold on the number would have flagged a real rule as a bug.
    """
    leaked = []
    for name in _corpus_spells():
        text = rules.find_spell(name)["text"]
        for entry in spellstats.damage(text):
            if entry["dice"].endswith("x"):
                amount = entry["dice"][:-1]
                if re.search(rf"[+\-][ \t]*{amount}\b", text):
                    leaked.append((name, entry["dice"]))
    assert leaked == [], leaked


def test_a_damage_threshold_is_not_reported_as_damage_dealt():
    """Prismatic Wall's layers break "if it takes at least 60 Force damage".

    That is a condition on damage the layer receives, not damage the spell deals, and the
    card would otherwise list it among the spell's own effects.
    """
    found = spellstats.damage("The layer is destroyed if it takes at least 60 Force damage.")
    assert found == []


def test_a_real_spell_reads_as_the_srd_writes_it():
    """Fireball end to end, since it is the case a reader will check by eye."""
    parsed = spellstats.parse(rules.find_spell("Fireball")["text"])
    assert parsed["casting_time"] == "Action"
    assert parsed["range"] == "150 feet"
    assert parsed["components"]["expanded"] == "V (Verbal), S (Somatic), M (Material)"
    assert parsed["components"]["material"] == "a ball of bat guano and sulfur"
    assert parsed["damage"] == [{"dice": "8d6", "types": ["Fire"], "chosen_type": False}]


def test_an_invocation_gets_no_stat_block():
    """It is quoted through the spell card, so this is the case that would look plausible.

    An invocation has a Prerequisite line and no Casting Time, and rendering an empty strip
    of tiles for it would imply a casting time the rules say it does not have.
    """
    invocation = rules.find_invocation("Agonizing Blast")
    assert invocation is not None
    assert spellstats.parse(invocation["text"]) is None


def _corpus_spells() -> list[str]:
    """Every spell name the card can be opened for, from both vendored sources.

    Built from the app's own indexes rather than by scanning the files for `####`, because
    `spells.md` also holds the *casting rules* as same-shaped headings - "Actions", "Bonus
    Actions", "Spell Slots", "Using a Higher-Level Spell Slot". Splitting on the heading
    alone collects those as spells, which is what `_is_spell_body` exists to prevent and
    what `find_spell` then refuses. Going through the index means this file tests the same
    546 names a link in the UI can actually resolve.
    """
    from backend.libs import spells as spells_module

    names = {name for name, _body in rules._spells_index().values()}
    for path in rules._corpus_spell_paths().values():
        head = path.read_text(encoding="utf-8")[:400]
        name = spells_module.spell_title(head) or spells_module.prettify_name(path.stem)
        if name:
            names.add(name)
    return sorted(names)
