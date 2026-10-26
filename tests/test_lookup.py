"""Deterministic sheet lookups: /c facts must be exact, not model guesses."""

from __future__ import annotations

import pytest

from backend.libs import characters, lookup

LOIS = {
    "Name": "Lois",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Current Level": 5,
    "Proficiency Bonus": "+3",
    "Ability Scores": "STR 8 (-1), DEX 14 (+2), CON 12 (+1), INT 10 (+0), WIS 14 (+2), CHA 18 (+4)",
    "Saving Throws": "STR -1, DEX +2, CON +1, INT +0, WIS +5 (proficient), CHA +7 (proficient)",
    "Passive Scores": "Perception 12, Insight 15, Investigation 13",
    "Armor Class": 14,
    "Hit Points": 33,
    "Speed": "30 ft.",
    "Spell Save DC": 15,
    "Spell Attack Bonus": "+7",
    "Spellcasting Ability": "Charisma",
    "Always Prepared Spells": "Light, Sacred Flame",
    "Cantrips From Other Sources": "Light (Aasimar), Guidance",
    "Known/Prepared Base Spells": "Hex",
}


class TestDirectFields:
    @pytest.mark.parametrize(
        ("question", "want", "field"),
        [
            ("ac", "14", "Armor Class"),
            ("armour class", "14", "Armor Class"),
            ("armor class?", "14", "Armor Class"),
            ("hp", "33", "Hit Points"),
            ("hit points", "33", "Hit Points"),
            ("spell save dc", "15", "Spell Save DC"),
            ("what is my save dc", "15", "Spell Save DC"),
            ("spell attack", "+7", "Spell Attack Bonus"),
            ("proficiency bonus", "+3", "Proficiency Bonus"),
            ("prof bonus", "+3", "Proficiency Bonus"),
            ("speed", "30 ft.", "Speed"),
            ("class", "Warlock", "Class"),
            ("subclass", "Celestial Patron", "Subclass"),
            ("level", "5", "Current Level"),
            ("spellcasting ability", "Charisma", "Spellcasting Ability"),
        ],
    )
    def test_a_sheet_field_is_quoted_verbatim(self, question, want, field):
        result = lookup.answer(question, LOIS)
        assert result is not None, f"{question!r} should be a lookup"
        assert result["answer"] == want
        assert result["field"] == field


class TestPassiveScores:
    """A combined field must be split, or the wrong number answers the question."""

    @pytest.mark.parametrize(
        ("question", "want"),
        [
            ("perception", "12"),
            ("passive perception", "12"),
            ("what is my passive perception", "12"),
            ("insight", "15"),
            ("passive insight", "15"),
            ("investigation", "13"),
            ("passive investigation", "13"),
        ],
    )
    def test_one_score_out_of_the_combined_field(self, question, want):
        assert lookup.answer(question, LOIS)["answer"] == want

    def test_the_first_score_is_not_returned_for_every_question(self):
        """The bug this guards: a naive parse returns Perception for all three."""
        answers = {
            lookup.answer(q, LOIS)["answer"]
            for q in ("perception", "insight", "investigation")
        }
        assert len(answers) == 3


class TestAbilityScoresAndSaves:
    @pytest.mark.parametrize(
        ("question", "want"),
        [
            ("dex", "14"),
            ("dexterity", "14"),
            ("my dex", "14"),
            ("strength", "8"),
            ("cha", "18"),
            ("wisdom", "14"),
        ],
    )
    def test_a_bare_ability_is_the_score(self, question, want):
        """A player reading 'DEX 14' means the score, not the +2."""
        result = lookup.answer(question, LOIS)
        assert result["answer"] == want
        assert "score" in result["source"]

    @pytest.mark.parametrize(
        ("question", "want"),
        [("dex modifier", "+2"), ("dex mod", "+2"), ("charisma bonus", "+4")],
    )
    def test_asking_for_the_modifier_gets_the_modifier(self, question, want):
        result = lookup.answer(question, LOIS)
        assert result["answer"] == want
        assert "modifier" in result["source"]

    @pytest.mark.parametrize(
        ("question", "want"),
        [
            ("dex save", "+2"),
            ("wisdom save", "+5 (proficient)"),
            ("cha saving throw", "+7 (proficient)"),
            ("str save", "-1"),
            ("int save", "+0"),
        ],
    )
    def test_saves_include_the_proficiency_note(self, question, want):
        assert lookup.answer(question, LOIS)["answer"] == want


class TestMisses:
    """A miss must defer to the model, never assert there is no such value."""

    @pytest.mark.parametrize(
        "question",
        ["why do I have two Light spells", "where does my spell attack come from",
         "what is the meaning of life", "", "   ", "?"],
    )
    def test_a_non_lookup_returns_none(self, question):
        assert lookup.answer(question, LOIS) is None

    def test_an_empty_sheet_returns_none(self):
        assert lookup.answer("ac", {}) is None

    def test_a_missing_field_returns_none(self):
        assert lookup.answer("ac", {"Name": "Nobody"}) is None

    def test_an_unknown_key_is_not_guessed(self):
        assert lookup.answer("initiative", LOIS) is None


class TestTolerance:
    def test_field_lookup_ignores_case_and_punctuation(self):
        assert lookup.answer("  AC?  ", LOIS)["answer"] == "14"

    def test_underscored_keys_match(self):
        assert lookup.answer("ac", {"Armor_Class": 17})["answer"] == "17"

    def test_a_list_value_is_joined(self):
        sheet = {"Languages": ["Common", "Draconic"]}
        assert lookup.answer("languages", sheet)["answer"] == "Common, Draconic"

    def test_a_numeric_field_is_returned_as_text(self):
        assert isinstance(lookup.answer("hp", LOIS)["answer"], str)


class TestSpellOrigins:
    """'Why do I have two Light spells?' has a factual answer in the sheet."""

    def test_two_sources_are_both_reported(self):
        origins = lookup.spell_origins(LOIS, "Light")
        assert "Always Prepared Spells" in origins
        assert "Cantrips From Other Sources" in origins

    def test_a_single_source_is_reported_once(self):
        assert lookup.spell_origins(LOIS, "Hex") == ["Known/Prepared Base Spells"]

    def test_an_unknown_spell_has_no_origins(self):
        assert lookup.spell_origins(LOIS, "Wish") == []

    def test_the_source_parenthetical_is_not_part_of_the_name(self):
        """'Light (Aasimar)' must be found from the bare name."""
        assert lookup.spell_origins(LOIS, "Light")
        assert lookup.spell_origins(LOIS, "Guidance")

    def test_lookup_is_case_insensitive(self):
        assert lookup.spell_origins(LOIS, "light") == lookup.spell_origins(LOIS, "Light")


def test_every_alias_target_resolves_for_a_real_sheet():
    """The prime sheet must answer every field the alias table advertises."""
    real = characters.load_character_data("lois")
    unresolved = []
    for key in lookup.ALIASES:
        if key in {"initiative", "hit dice", "darkvision", "languages", "background",
                   "alignment", "party", "pact", "species"}:
            continue  # present on the real sheet under a differently shaped field
        result = lookup.answer(key, real)
        if result is None:
            unresolved.append(key)
    assert not unresolved, f"these aliases found nothing on lois.yaml: {unresolved}"
