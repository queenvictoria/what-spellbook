"""Tests for character sheet loading from data/characters/<name>.yaml."""

import pytest

from backend import cache  # noqa: F401
from backend.characters import CharacterNotFound
import main


def _write(directory, name, text):
    path = directory / f"{name}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_yaml_and_renders_prompt_text(character_dir):
    _write(
        character_dir,
        "lois",
        "Class: Warlock\n"
        "Subclass: Celestial Patron\n"
        "Pact: Tome\n"
        "Current Level: 5\n",
    )
    assert main.load_character("lois") == (
        "Class: Warlock\n"
        "Subclass: Celestial Patron\n"
        "Pact: Tome\n"
        "Current Level: 5"
    )


def test_strips_yaml_mapping_syntax(character_dir):
    """Lists become comma text, never brackets or braces, inside the prompt."""
    _write(character_dir, "lois", "Party: [Barbarian, Fighter, Druid]\n")
    rendered = main.load_character("lois")
    assert rendered == "Party: Barbarian, Fighter, Druid"
    assert "[" not in rendered and "{" not in rendered


def test_renders_block_sequence_lists(character_dir):
    _write(character_dir, "lois", "Party:\n  - Barbarian\n  - Fighter\n")
    assert main.load_character("lois") == "Party: Barbarian, Fighter"


def test_multiword_keys_are_title_cased(character_dir):
    _write(character_dir, "lois", "known_prepared_base_spells: Hex\n")
    assert main.load_character("lois") == "Known Prepared Base Spells: Hex"


def test_underscores_become_spaces_in_keys(character_dir):
    _write(character_dir, "lois", "pact_slots: Two 3rd-level slots\n")
    assert main.load_character("lois") == "Pact Slots: Two 3rd-level slots"


@pytest.mark.parametrize("reference", ["lois", "lois.yaml", "data/characters/lois.yaml"])
def test_accepts_stem_suffix_or_path(character_dir, reference):
    _write(character_dir, "lois", "Class: Warlock\n")
    assert main.load_character(reference) == "Class: Warlock"


def test_preserves_key_order_from_file(character_dir):
    _write(character_dir, "lois", "Zeta: 1\nAlpha: 2\n")
    assert main.load_character("lois") == "Zeta: 1\nAlpha: 2"


def test_integers_render_without_yaml_artifacts(character_dir):
    _write(character_dir, "lois", "Current Level: 5\n")
    assert main.load_character("lois") == "Current Level: 5"


# --- failure modes ---


def test_missing_sheet_raises_a_typed_error(character_dir):
    """The loader raises; only the CLI decides to turn that into an exit code."""
    with pytest.raises(CharacterNotFound):
        main.load_character("nobody")


def test_missing_sheet_lists_available_names(character_dir):
    _write(character_dir, "lois", "Class: Warlock\n")
    with pytest.raises(CharacterNotFound) as exc:
        main.load_character("nobody")
    assert "lois" in str(exc.value)


def test_missing_sheet_on_empty_directory_says_none(character_dir):
    with pytest.raises(CharacterNotFound) as exc:
        main.load_character("nobody")
    assert "none" in str(exc.value)


def test_malformed_yaml_raises_rather_than_crashing(character_dir):
    """A broken sheet is reported with its cause, not a raw yaml traceback."""
    _write(character_dir, "broken", "Class: [unclosed\n")
    with pytest.raises(CharacterNotFound) as exc:
        main.load_character("broken")
    assert "Could not parse" in str(exc.value)


@pytest.mark.parametrize("content", ["", "   \n", "just a string\n", "- a\n- b\n"])
def test_non_mapping_sheet_raises(character_dir, content):
    """A sheet that is not a key/value mapping cannot render a profile block."""
    _write(character_dir, "weird", content)
    with pytest.raises(CharacterNotFound) as exc:
        main.load_character("weird")
    assert "must contain a mapping" in str(exc.value)


def test_cli_reports_a_missing_character_as_an_exit_code(character_dir, capsys, fake_db):
    """The exit code lives at the CLI boundary, which is where main() runs."""
    from cli import app

    assert app.main(["--character", "nobody"]) == 1
    assert "nobody" in capsys.readouterr().err


# --- real shipped sheet ---


def test_repo_lois_sheet_loads_if_present():
    """The working sheet is gitignored, so only assert when it exists."""
    from pathlib import Path

    path = Path(main.CHARACTERS_DIR) / "lois.yaml"
    if not path.exists():
        pytest.skip("data/characters/lois.yaml not present in this checkout")

    rendered = main.load_character("lois")
    assert "Class:" in rendered
    assert "{" not in rendered and "[" not in rendered
