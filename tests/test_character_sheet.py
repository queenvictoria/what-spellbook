"""Tests for reading a real, fully-populated character sheet.

A sheet is not one field per concept. 'What the character already has' arrives spread
across the Warlock picks, the patron's always-prepared list, species and feat grants,
and free casts - so these tests pin the union, and pin the fact that the Book of
Shadows' *current* loadout is deliberately still eligible.
"""

import pytest
import yaml

import main

# Mirrors the shape of data/characters/lois.yaml: every field populated.
FULL_SHEET = {
    "Name": "Lois",
    "Species": "Aasimar",
    "Background": "Seer Apprentice",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Pact": "Tome",
    "Current Level": 5,
    "Feats": "Fey Touched (Charisma), Arcane Omens (Charisma)",
    "Known/Prepared Base Spells": "Eldritch Blast, Mage Hand, Minor Illusion, Hex",
    "Book of Shadows Cantrips": "Word of Radiance, Shillelagh, Friends",
    "Book of Shadows Rituals": "Identify, Find Familiar",
    "Always Prepared Spells": "Light, Sacred Flame, Cure Wounds, Guiding Bolt",
    "Free Casts Per Long Rest": "Dissonant Whispers, Misty Step",
    "Cantrips From Other Sources": "Guidance (Arcane Omens), Light (Aasimar)",
    "Party": "Barbarian, Fighter, Druid",
}


# --- the union of everything the character already has ---

def test_known_spells_covers_every_granting_field():
    known = main.known_spells(FULL_SHEET)
    for name in (
        "Eldritch Blast",       # Warlock picks
        "Light",                # always prepared / species
        "Sacred Flame",         # always prepared
        "Guiding Bolt",         # always prepared
        "Misty Step",           # free cast
        "Guidance",             # from a feat
    ):
        assert name in known, f"{name} must be excluded from the pool"


def test_known_spells_does_not_include_the_current_book():
    """The book is conjured fresh each rest, so its picks stay eligible.

    Excluding them would also let this tool's previous answer permanently constrain
    the next one, which is the opposite of the pact's purpose.
    """
    known = main.known_spells(FULL_SHEET)
    assert "Word of Radiance" not in known
    assert "Identify" not in known


def test_current_book_spells_are_reported_separately():
    assert main.current_book_spells(FULL_SHEET) == [
        "Word of Radiance", "Shillelagh", "Friends", "Identify", "Find Familiar",
    ]


def test_known_spells_dedupes_across_fields():
    """'Light' appears as an always-prepared spell and as an Aasimar cantrip."""
    assert main.known_spells(FULL_SHEET).count("Light") == 1


def test_known_spells_keeps_sheet_order():
    assert main.known_spells(FULL_SHEET)[:4] == [
        "Eldritch Blast", "Mage Hand", "Minor Illusion", "Hex",
    ]


# --- provenance in the sheet ---

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Guidance (Arcane Omens), Light (Aasimar)", ["Guidance", "Light"]),
        ("Light(Aasimar)", ["Light"]),
        ("Hex, Shield", ["Hex", "Shield"]),
        ("Hex, , Shield", ["Hex", "Shield"]),
        ("", []),
        (None, []),
        (["Hex", "Shield"], ["Hex", "Shield"]),
    ],
)
def test_split_names_drops_the_source_note(value, expected):
    """Sheets record provenance in a trailing parenthetical, which is not the name."""
    assert main._split_names(value) == expected


def test_a_parenthetical_name_is_not_truncated():
    """Only a trailing parenthetical is a source note."""
    assert main._split_names("Dissonant Whispers, Tasha's Hideous Laughter") == [
        "Dissonant Whispers", "Tasha's Hideous Laughter",
    ]


# --- the pool tells the model what not to pick ---

def test_already_have_block_names_the_existing_spells():
    block = main._format_already_have(FULL_SHEET)
    assert "do NOT choose these as book picks" in block
    assert "Guiding Bolt" in block
    assert "Guidance" in block


def test_already_have_block_explains_the_current_book_is_still_legal():
    block = main._format_already_have(FULL_SHEET)
    assert "CURRENTLY holds" in block
    assert "conjured fresh" in block


def test_already_have_block_attributes_the_source():
    """The model should see that these come from species and feats, not just the class."""
    block = main._format_already_have(FULL_SHEET)
    assert "always prepared" in block
    assert "from species, background or feats" in block


def test_already_have_block_is_empty_without_a_sheet():
    assert main._format_already_have(None) == ""
    assert main._format_already_have({}) == ""


def test_pool_includes_the_already_have_block():
    bucket = _bucket()
    assert "do NOT choose these" in main._format_pool(bucket, 3, character=FULL_SHEET)


def _bucket():
    """A minimal non-empty pool, since an empty pool short-circuits the render."""
    from spells import Spell

    spell = Spell(
        name="Light", filename="Light.md", level=0, school="Evocation",
        classes=("Bard",), is_ritual=False, is_spell=True,
    )
    return {"cantrips": [spell], "rituals": [], "ranked": []}


def test_pool_without_a_character_still_renders():
    assert "do NOT choose these" not in main._format_pool(_bucket(), 3)


# --- the real sheet on disk ---

def test_the_repo_character_sheet_parses(character_dir):
    """Guard the untracked sheet's shape, since it drives every real run."""
    source = main.Path(main.__file__).resolve().parent / "data" / "characters" / "lois.yaml"
    if not source.exists():
        pytest.skip("lois.yaml is untracked user data and not present")

    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    assert main.character_level(data) == 5
    assert main.max_spell_level(data) == 3
    assert "Light" in main.known_spells(data)
    assert "Eldritch Blast" in main.known_spells(data)
    assert main.current_book_spells(data)


def test_the_repo_sheet_resolves_the_expected_context_files():
    data = dict(FULL_SHEET)
    from prompts import context_files_for

    assert context_files_for(data) == [
        "spells.md",
        "classes/warlock/base.md",
        "classes/warlock/pact/tome.md",
        "classes/warlock/subclass/celestial.md",
    ]


def test_the_repo_sheet_is_cached_under_its_species_agnostic_key():
    """Species/background do not key the cache; they are already in the sheet snapshot."""
    from cache import key_parts

    key = key_parts(character="Lois", level=5, party="Barbarian, Fighter, Druid",
                    db_version=3, scenario="x")
    assert key["character"] == "lois"
    assert key["level"] == 5
    assert key["party"] == "barbarian-fighter-druid"


def test_split_names_normalises_typographic_apostrophes():
    """A hand-written sheet may use a curly apostrophe; the corpus does not."""
    assert main._split_names("Tenser\u2019s Floating Disk, Hex") == [
        "Tenser's Floating Disk", "Hex",
    ]


def test_known_spells_matches_the_corpus_across_apostrophe_styles():
    sheet = {"Always Prepared Spells": "Tasha\u2019s Hideous Laughter"}
    assert "Tasha's Hideous Laughter" in main.known_spells(sheet)
