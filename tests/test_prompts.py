"""Tests for prompt assembly in prompts.py.

The key contract is the split of responsibilities: rule *content* lives in context/
while prompt *templates* live here, and the builder must pick the right context files
for a character without hard-coding a class.
"""

import pytest

import prompts


LOIS = {
    "Name": "Lois",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Pact": "Tome",
    "Current Level": 5,
}


# --- slugging ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Celestial Patron", "celestial"),
        ("The Fiend", "the_fiend"),
        ("Great Old One Patron", "great_old_one"),
        ("Pact of the Blade", "blade"),
        ("Pact of the Tome", "tome"),
        ("Pact of the Chain", "chain"),
        ("Archfey", "archfey"),
    ],
)
def test_slug_normalises_sheet_values(raw, expected):
    assert prompts._slug(raw) == expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_slug_of_empty_is_empty(value):
    assert prompts._slug(value) == ""


# --- context file selection ---


def test_context_files_for_full_warlock():
    assert prompts.context_files_for(LOIS) == [
        "spells.md",
        "classes/warlock/base.md",
        "classes/warlock/pact/tome.md",
        "classes/warlock/subclass/celestial.md",
    ]


def test_class_rules_apply_even_without_pact_or_subclass():
    """A sheet with only a class still gets the class-wide rules."""
    assert prompts.context_files_for({"Class": "Warlock"}) == [
        "spells.md",
        "classes/warlock/base.md",
    ]


def test_class_agnostic_file_always_first():
    assert prompts.context_files_for({"Class": "Warlock"})[0] == "spells.md"


def test_no_class_returns_only_class_agnostic_files():
    assert prompts.context_files_for({}) == ["spells.md"]


def test_pact_and_subclass_are_independent():
    files = prompts.context_files_for({"Class": "Warlock", "Pact": "Blade"})
    assert "classes/warlock/pact/blade.md" in files
    assert not any("subclass" in f for f in files)


def test_lowercase_sheet_keys_also_work():
    """Sheets are hand-written YAML, so key casing is not guaranteed."""
    assert prompts.context_files_for({"class": "warlock", "pact": "tome"}) == [
        "spells.md",
        "classes/warlock/base.md",
        "classes/warlock/pact/tome.md",
    ]


# --- loading ---


def test_load_rule_context_reads_every_applicable_file(tmp_path):
    (tmp_path / "classes/warlock/pact").mkdir(parents=True)
    (tmp_path / "classes/warlock/subclass").mkdir(parents=True)
    (tmp_path / "spells.md").write_text("CASTING ECONOMY", encoding="utf-8")
    (tmp_path / "classes/warlock/base.md").write_text("BASE RULES", encoding="utf-8")
    (tmp_path / "classes/warlock/pact/tome.md").write_text("TOME RULES", encoding="utf-8")
    (tmp_path / "classes/warlock/subclass/celestial.md").write_text("CELESTIAL", encoding="utf-8")

    context = prompts.load_rule_context(LOIS, tmp_path)

    for marker in ("CASTING ECONOMY", "BASE RULES", "TOME RULES", "CELESTIAL"):
        assert marker in context


def test_load_rule_context_skips_missing_files(tmp_path):
    (tmp_path / "spells.md").write_text("CASTING ECONOMY", encoding="utf-8")
    context = prompts.load_rule_context(LOIS, tmp_path)
    assert "CASTING ECONOMY" in context
    assert "TOME RULES" not in context


def test_load_rule_context_missing_directory_is_empty(tmp_path):
    assert prompts.load_rule_context(LOIS, tmp_path / "nope") == ""


def test_load_rule_context_annotates_sources(tmp_path):
    """The provenance comment makes it obvious which files were injected."""
    (tmp_path / "spells.md").write_text("X", encoding="utf-8")
    assert "<!-- spells.md -->" in prompts.load_rule_context(LOIS, tmp_path)


def test_repo_context_directory_resolves_for_lois():
    """Guard against the context/ layout drifting away from the templates."""
    context = prompts.load_rule_context(LOIS, "context")
    assert "Pact of the Tome" in context
    assert "Celestial" in context


def test_context_dir_with_classes_prefix_is_configurable(tmp_path):
    """The layout gained a classes/ level; the templates must follow it."""
    (tmp_path / "classes/warlock").mkdir(parents=True)
    (tmp_path / "classes/warlock/base.md").write_text("BASE", encoding="utf-8")
    assert "BASE" in prompts.load_rule_context({"Class": "Warlock"}, tmp_path)


# --- system prompt constraints ---


def test_system_prompt_pins_the_book_pick_counts():
    system = prompts.system_prompt()
    assert "3 cantrips" in system
    assert "2 level 1 rituals" in system


def test_system_prompt_forbids_inventing_spells():
    assert "ONLY legal source" in prompts.system_prompt()


def test_system_prompt_forbids_already_prepared_spells():
    assert "already has prepared" in prompts.system_prompt()


def test_system_prompt_warns_about_uniform_slot_level():
    """This is the single most common model error for Warlocks."""
    assert "same level" in prompts.system_prompt()


# --- full prompt ---


def _full(**overrides):
    kwargs = dict(
        character_text="Name: Lois",
        rule_context="RULES HERE",
        scenario="a duel on a bridge",
        pool_text="POOL HERE",
        spell_text="FULL TEXT HERE",
    )
    kwargs.update(overrides)
    return prompts.full_prompt(**kwargs)


def test_full_prompt_includes_every_section():
    prompt = _full()
    for marker in ("RULES HERE", "Name: Lois", "a duel on a bridge", "POOL HERE"):
        assert marker in prompt


def test_full_prompt_includes_shortlisted_spell_text():
    assert "FULL TEXT HERE" in _full()


def test_full_prompt_asks_for_three_labelled_books():
    prompt = _full()
    assert "EXACTLY 3" in prompt
    for book in ("Book 1", "Book 2", "Book 3"):
        assert book in prompt


def test_full_prompt_degrades_when_no_rules_found():
    prompt = _full(rule_context="")
    assert "no rule files found" in prompt


def test_full_prompt_handles_empty_pool():
    prompt = _full(pool_text="", spell_text="")
    assert "no spells matched" in prompt


def test_full_prompt_omits_shortlist_heading_when_no_spell_text():
    assert "FULL TEXT FOR SHORTLISTED" not in _full(spell_text="")


def test_full_prompt_places_rules_before_character():
    """Order matters: the rules should frame how the sheet is read."""
    prompt = _full()
    assert prompt.index("RULES HERE") < prompt.index("Name: Lois")


def test_full_prompt_asks_for_existing_spell_synergy():
    assert "existing prepared spells" in _full()


# --- refine prompt ---


def _refine(**overrides):
    kwargs = dict(
        question="what about healing?",
        previous_response="PREVIOUS BOOKS",
        scenario="a duel on a bridge",
        rule_context="RULES HERE",
        pool_text="POOL HERE",
    )
    kwargs.update(overrides)
    return prompts.refine_prompt(**kwargs)


def test_refine_prompt_carries_previous_answer_and_question():
    prompt = _refine()
    assert "PREVIOUS BOOKS" in prompt
    assert "what about healing?" in prompt


def test_refine_prompt_restates_scenario():
    assert "a duel on a bridge" in _refine()


def test_refine_prompt_restates_legality_constraints():
    """A follow-up must not quietly introduce an ineligible spell."""
    prompt = _refine()
    assert "ONLY legal source" in prompt
    assert "same level" in prompt


def test_refine_prompt_resupplies_the_pool():
    assert "POOL HERE" in _refine()


def test_refine_prompt_notes_when_pool_absent():
    assert "not re-supplied" in _refine(pool_text="")


def test_refine_prompt_tells_model_to_decline_illegal_requests():
    assert "cannot be satisfied legally" in _refine()


# --- character sheet ingest prompt ---


def _ingest(**overrides):
    kwargs = dict(pdf_text="RAW PDF TEXT HERE", name="lois")
    kwargs.update(overrides)
    return prompts.character_sheet_prompt(**kwargs)


def test_ingest_prompt_embeds_the_raw_pdf_text():
    assert "RAW PDF TEXT HERE" in _ingest()


def test_ingest_prompt_lists_every_sheet_key():
    prompt = _ingest()
    for key in prompts.CHARACTER_SHEET_KEYS:
        assert f"- {key}" in prompt


def test_ingest_prompt_asks_for_yaml_only():
    prompt = _ingest()
    assert "Return ONLY a YAML mapping" in prompt
    assert "no code fences" in prompt


def test_ingest_prompt_forbids_inventing_content():
    """A hallucinated spell on the sheet corrupts every later recommendation."""
    assert "Never invent a spell" in _ingest()


def test_ingest_prompt_forbids_carrying_over_old_values():
    assert "replaces" in _ingest()


def test_ingest_prompt_maps_spell_sources_to_keys():
    """The SOURCE column is what separates base spells from Book of Shadows picks."""
    prompt = _ingest()
    for source in ("Warlock", "Eldritch Invocations", "Celestial Spells (Always Prepared)"):
        assert source in prompt
    assert "Book of Shadows Rituals" in prompt


def test_ingest_prompt_pins_the_pact_slot_shape():
    assert "Two 3rd-level slots" in _ingest()


def test_ingest_prompt_warns_about_yaml_quoting():
    """Unquoted '+3' and leading-digit values are the common parse failures."""
    assert "must be quoted" in _ingest()


def test_ingest_prompt_mentions_the_layout_flag():
    """Without -layout the multi-column export interleaves into unusable text."""
    assert "pdftotext -layout" in _ingest()


def test_ingest_prompt_names_the_target_file():
    assert "data/characters/lois.yaml" in _ingest()


def test_ingest_prompt_falls_back_to_a_placeholder_target():
    assert "data/characters/<name>.yaml" in _ingest(name="")


def test_sheet_keys_are_unique():
    assert len(prompts.CHARACTER_SHEET_KEYS) == len(set(prompts.CHARACTER_SHEET_KEYS))


def test_repo_lois_sheet_uses_only_declared_keys():
    """Guard against the sheet and the ingest prompt drifting apart."""
    import yaml

    from pathlib import Path

    path = Path("data/characters/lois.yaml")
    if not path.is_file():
        pytest.skip("working sheet is gitignored")

    sheet = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(sheet) <= set(prompts.CHARACTER_SHEET_KEYS)


# --- prompt budget guard ---


def test_prompt_budget_warning_is_none_for_short_prompts():
    assert prompts.prompt_budget_warning("x" * 100) is None


def test_prompt_budget_warning_fires_for_oversized_prompts():
    """The context files plus pool can overflow a local model's window, which shows
    up as an empty completion rather than an error."""
    warning = prompts.prompt_budget_warning("x" * (prompts.PROMPT_CHAR_BUDGET + 1))
    assert warning is not None
    assert "context" in warning.lower()
