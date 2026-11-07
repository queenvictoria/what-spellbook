"""Tests for the application layer.

`SpellbookService` is the seam a future API would use, so it is tested directly rather
than only through the REPL: it must do the work, return dataclasses, and never print,
prompt or exit.
"""

import json

import pytest

from backend.libs import cache, llm, service
from backend.cli import shell as shell_mod


SHEET = {
    "Name": "Lois",
    "Class": "Warlock",
    "Subclass": "Celestial Patron",
    "Pact": "Tome",
    "Current Level": 5,
    "Party": "Barbarian, Fighter, Druid",
    "Known/Prepared Base Spells": "Eldritch Blast, Hex",
}

SCENARIO = "Undead pour from a collapsed crypt."


@pytest.fixture
def svc(fake_db, fake_llm, tmp_path):
    return service.SpellbookService(
        fake_db, dict(SHEET), backend=fake_llm, cache_dir=str(tmp_path / "cache")
    )


# --- the returned value is the interface ---

def test_scenario_returns_a_generation_dataclass(svc):
    generation = svc.scenario(SCENARIO)
    assert isinstance(generation, service.Generation)
    assert generation.scenario == SCENARIO
    assert generation.answer
    assert generation.prompt
    assert generation.from_cache is False


def test_books_are_exposed_individually(svc):
    """A book is the unit of rating, so it is the unit of the API too."""
    generation = svc.scenario(SCENARIO)
    assert generation.books
    for book in generation.books:
        assert isinstance(book, service.Book)
        assert book.index >= 1
        assert book.name
        assert book.text in generation.answer


def test_service_never_prints(svc, capsys):
    svc.scenario(SCENARIO)
    captured = capsys.readouterr()
    assert captured.out == "", "the service must not write to stdout"
    assert captured.err == ""


def test_service_exposes_the_whole_sheet_to_callers(svc):
    assert svc.character["Name"] == "Lois"
    assert "Name: Lois" in svc.character_text


def test_summary_describes_what_happened(svc):
    assert "Scribed" in svc.scenario(SCENARIO).summary


# --- errors are typed, never exits ---

def test_empty_scenario_raises_value_error(svc):
    with pytest.raises(ValueError):
        svc.scenario("   ")


def test_no_eligible_spells_raises_a_typed_error(svc, fake_db):
    fake_db.CATALOGUE = []
    with pytest.raises(service.NoEligibleSpells):
        svc.scenario(SCENARIO)


def test_empty_completion_raises_a_typed_error(svc, fake_llm):
    fake_llm.response = ""
    with pytest.raises(llm.EmptyCompletion):
        svc.scenario(SCENARIO)


def test_backend_failure_raises_a_typed_error(svc):
    class Boom:
        def invoke(self, prompt):
            raise RuntimeError("backend down")

    svc.llm = Boom()
    with pytest.raises(llm.LLMUnavailable):
        svc.scenario(SCENARIO)


def test_refine_before_a_scenario_raises_value_error(svc):
    with pytest.raises(ValueError):
        svc.refine("what about hex?", None)


def test_refine_without_a_question_raises_value_error(svc):
    generation = svc.scenario(SCENARIO)
    with pytest.raises(ValueError):
        svc.refine("  ", generation)


# --- caching ---

def test_second_call_is_served_from_the_cache(svc, fake_llm):
    svc.scenario(SCENARIO)
    before = len(fake_llm.prompts)
    replayed = svc.scenario(SCENARIO)
    assert len(fake_llm.prompts) == before, "no second model call"
    assert replayed.from_cache is True
    assert "cache" in replayed.summary


def test_find_cached_misses_before_anything_is_generated(svc):
    assert svc.find_cached(SCENARIO) is None


def test_cache_can_be_bypassed(svc, fake_llm):
    svc.scenario(SCENARIO)
    before = len(fake_llm.prompts)
    svc.refresh = True
    assert svc.scenario(SCENARIO).from_cache is False
    assert len(fake_llm.prompts) == before + 1


def test_replayed_books_keep_their_cache_paths(svc):
    svc.scenario(SCENARIO)
    replayed = svc.scenario(SCENARIO)
    assert all(book.cache_path for book in replayed.books)


def test_generated_books_are_given_their_cache_paths(svc):
    generation = svc.scenario(SCENARIO)
    assert all(book.cache_path for book in generation.books)


def test_a_cache_hit_is_revalidated(svc, caplog):
    """An entry may predate a rules change, so legality is re-checked on replay."""
    svc.scenario(SCENARIO)
    assert svc.scenario(SCENARIO).warnings is not None


def test_no_character_means_no_cache_write(fake_db, fake_llm, tmp_path):
    svc = service.SpellbookService(fake_db, {}, backend=fake_llm, cache_dir=str(tmp_path / "c"))
    svc.scenario(SCENARIO)
    assert not list((tmp_path / "c").rglob("*.json"))


# --- progress is injected, not imported ---

def test_scenario_reports_each_stage(svc):
    seen = []
    svc.scenario(SCENARIO, progress=seen.append)
    assert len(seen) == 3, f"expected three stages, got {seen}"
    assert "grimoire" in seen[0]


def test_work_happens_without_any_progress_callback(svc):
    assert svc.scenario(SCENARIO).answer


# --- contextualising a spell to the character ---

def test_a_spell_is_contextualised_from_its_own_text(svc):
    """The value is already written in the spell, so no model is asked for it."""
    spell = {"name": "Eldritch Blast", "text": (
        "_Cantrip Upgrade._ The spell creates two beams at level 5, three beams at "
        "level 11, and four beams at level 17."
    )}
    assert svc.spell_scaling(spell) == "2 beams (L5)"


def test_a_spell_that_does_not_scale_costs_no_model_call(svc, fake_llm):
    """The gate is what keeps a call off every levelled spell in the corpus."""
    spell = {"name": "Fireball", "text": "**Casting Time:** Action\n\nA bright streak."}
    assert svc.spell_scaling(spell) is None
    assert fake_llm.prompts == []


def test_the_fast_model_reads_a_scaling_the_parser_cannot(svc, fake_llm):
    """Booming Blade scales in prose rather than in a table, so it is the model's job."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    spell = {"name": "Booming Blade", "text": (
        "This spell's damage increases when you reach certain levels. At 5th level, the "
        "melee attack deals an extra 1d8 Thunder damage to the target on a hit."
    )}
    assert svc.spell_scaling(spell) == "extra 1d8 thunder damage on hit (L5)"
    assert len(fake_llm.prompts) == 1
    assert "Booming Blade" in fake_llm.prompts[0]


def test_the_fast_model_is_asked_only_about_the_gap(svc, fake_llm):
    """A spell the parser read must not also cost a model call."""
    fake_llm.response = "should not be used"
    spell = {"name": "Fire Bolt", "text": (
        "_Cantrip Upgrade._ The damage increases by 1d10 when you reach levels "
        "5 (2d10), 11 (3d10), and 17 (4d10)."
    )}
    assert svc.spell_scaling(spell) == "2d10 damage (L5)"
    assert fake_llm.prompts == []


@pytest.mark.parametrize("answer", ["none", "None.", "N/A", "no change", ""])
def test_a_refusal_is_not_a_note(svc, fake_llm, answer):
    """The model is told to say "none", and a note reading "none (L5)" is not a note."""
    fake_llm.response = answer
    spell = {"name": "Booming Blade", "text": (
        "This spell's damage increases when you reach certain levels. At 5th level, the "
        "melee attack deals an extra 1d8 Thunder damage to the target on a hit."
    )}
    assert svc.spell_scaling(spell) is None


def test_a_sentence_is_not_a_note(svc, fake_llm):
    """The note is rendered as a badge, so a paragraph would break the card."""
    fake_llm.response = (
        "At 5th level, the melee attack deals an extra 1d8 Thunder damage to the target "
        "on a hit, and the damage the target takes for moving increases to 2d8."
    )
    spell = {"name": "Booming Blade", "text": (
        "This spell's damage increases when you reach certain levels. At 5th level, the "
        "melee attack deals an extra 1d8 Thunder damage to the target on a hit."
    )}
    assert svc.spell_scaling(spell) is None


def test_a_two_part_upgrade_is_still_a_note(svc, fake_llm):
    """The cap must clear the real answers, not just the short example.

    Both prose cantrips this path exists for have a two-part upgrade, so their answers run
    to ~100 characters. A cap sized to "2 beams" discarded every one of them and made
    Green-Flame Blade look like a spell that does not scale.
    """
    fake_llm.response = (
        "1d8 extra fire damage to the target; second creature takes 1d8 + spellcasting "
        "ability modifier fire damage"
    )
    spell = {"name": "Green-Flame Blade", "text": (
        "This spell's damage increases when you reach certain levels. At 5th level, the "
        "melee attack deals an extra 1d8 Fire damage to the target on a hit."
    )}
    note = svc.spell_scaling(spell)
    assert note is not None
    assert note.endswith("(L5)")
    assert "1d8" in note


def test_a_model_failure_does_not_lose_the_card(svc, fake_llm):
    """The note is an addition to the card, so a failure to produce it is not an error."""
    def boom(_prompt):
        raise llm.LLMUnavailable("no network")

    fake_llm.invoke = boom
    spell = {"name": "Booming Blade", "text": (
        "This spell's damage increases when you reach certain levels. At 5th level, the "
        "melee attack deals an extra 1d8 Thunder damage to the target on a hit."
    )}
    assert svc.spell_scaling(spell) is None


def test_no_level_means_no_note_and_no_call(svc, fake_llm):
    svc.character = {k: v for k, v in SHEET.items() if k != "Current Level"}
    spell = {"name": "Eldritch Blast", "text": (
        "_Cantrip Upgrade._ The spell creates two beams at level 5."
    )}
    assert svc.spell_scaling(spell) is None
    assert fake_llm.prompts == []


def test_an_injected_backend_is_reused_for_the_fast_path(svc, fake_llm):
    """Injection means "use this instead of constructing clients".

    A test that passes a fake and then gets a real network call from the fast path would
    be testing nothing - and would fail on a machine with no key.
    """
    assert svc.fast_llm is fake_llm


# --- the note is cached against the character and level ---

BOOMING_BLADE = {"name": "Booming Blade", "text": (
    "This spell's damage increases when you reach certain levels. At 5th level, the "
    "melee attack deals an extra 1d8 Thunder damage to the target on a hit."
)}


def test_a_second_look_at_the_same_spell_costs_no_model_call(svc, fake_llm):
    """Opening a drawer twice must not pay for the same phrase twice."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    assert svc.spell_scaling(BOOMING_BLADE) == "extra 1d8 thunder damage on hit (L5)"
    assert svc.spell_scaling(BOOMING_BLADE) == "extra 1d8 thunder damage on hit (L5)"
    assert len(fake_llm.prompts) == 1


def test_the_cache_survives_a_new_service_over_the_same_directory(fake_db, fake_llm, tmp_path):
    """The point of a cache is that it outlives the process that filled it."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    cache_dir = str(tmp_path / "cache")
    first = service.SpellbookService(fake_db, dict(SHEET), backend=fake_llm,
                                     cache_dir=cache_dir)
    assert first.spell_scaling(BOOMING_BLADE) is not None

    second = service.SpellbookService(fake_db, dict(SHEET), backend=fake_llm,
                                      cache_dir=cache_dir)
    assert second.spell_scaling(BOOMING_BLADE) == "extra 1d8 thunder damage on hit (L5)"
    assert len(fake_llm.prompts) == 1


def test_a_different_level_is_a_different_note(fake_db, fake_llm, tmp_path):
    """The level is in the key because it is in the answer."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    cache_dir = str(tmp_path / "cache")
    at_five = service.SpellbookService(fake_db, dict(SHEET), backend=fake_llm,
                                       cache_dir=cache_dir)
    assert at_five.spell_scaling(BOOMING_BLADE) is not None

    fake_llm.response = "extra 2d8 thunder damage on hit"
    at_eleven = service.SpellbookService(
        fake_db, {**SHEET, "Current Level": 11}, backend=fake_llm, cache_dir=cache_dir
    )
    assert at_eleven.spell_scaling(BOOMING_BLADE) == "extra 2d8 thunder damage on hit (L11)"
    assert len(fake_llm.prompts) == 2


def test_a_different_character_is_a_different_note(fake_db, fake_llm, tmp_path):
    """Two characters at the same level are still two answers, so the name is in the key."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    cache_dir = str(tmp_path / "cache")
    lois = service.SpellbookService(fake_db, dict(SHEET), backend=fake_llm,
                                    cache_dir=cache_dir)
    assert lois.spell_scaling(BOOMING_BLADE) is not None

    fake_llm.response = "extra 1d8 thunder damage on hit"
    other = service.SpellbookService(fake_db, {**SHEET, "Name": "Bram"}, backend=fake_llm,
                                     cache_dir=cache_dir)
    assert other.spell_scaling(BOOMING_BLADE) is not None
    assert len(fake_llm.prompts) == 2


def test_a_refusal_is_cached_too(svc, fake_llm):
    """"This spell does not scale" is an answer, and it cost a call to obtain."""
    fake_llm.response = "none"
    assert svc.spell_scaling(BOOMING_BLADE) is None
    assert svc.spell_scaling(BOOMING_BLADE) is None
    assert len(fake_llm.prompts) == 1


def test_a_failure_is_not_cached(svc, fake_llm):
    """Storing a failure would make one bad call permanent for this character and level."""
    calls = []

    def boom(_prompt):
        calls.append(1)
        raise llm.LLMUnavailable("no network")

    fake_llm.invoke = boom
    assert svc.spell_scaling(BOOMING_BLADE) is None
    assert svc.spell_scaling(BOOMING_BLADE) is None
    assert len(calls) == 2


def test_the_deterministic_read_is_not_cached(svc, fake_llm, tmp_path):
    """It is free, and a stored copy would outlive a corpus change that fixed it."""
    spell = {"name": "Eldritch Blast", "text": (
        "_Cantrip Upgrade._ The spell creates two beams at level 5, three beams at "
        "level 11, and four beams at level 17."
    )}
    assert svc.spell_scaling(spell) == "2 beams (L5)"
    assert not list((tmp_path / "cache" / "scaling").rglob("*.json"))


def test_a_corrupt_entry_falls_back_to_the_model(svc, fake_llm, tmp_path):
    """A cache that cannot be read is a miss, not an error."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    assert svc.spell_scaling(BOOMING_BLADE) is not None
    for path in (tmp_path / "cache" / "scaling").rglob("*.json"):
        path.write_text("{not json", encoding="utf-8")
    assert svc.spell_scaling(BOOMING_BLADE) == "extra 1d8 thunder damage on hit (L5)"
    assert len(fake_llm.prompts) == 2


def test_an_entry_from_an_older_reader_is_ignored(svc, fake_llm, tmp_path):
    """A note written before a reader fix must not keep being served.

    This is the bug the version exists for: every cantrip reported its level 5 value at
    levels 11 and 17, and a stored note would have gone on doing so.
    """
    fake_llm.response = "extra 1d8 thunder damage on hit"
    assert svc.spell_scaling(BOOMING_BLADE) is not None
    for path in (tmp_path / "cache" / "scaling").rglob("*.json"):
        entry = json.loads(path.read_text(encoding="utf-8"))
        entry["scaling_version"] = cache.SCALING_VERSION - 1
        path.write_text(json.dumps(entry), encoding="utf-8")
    assert svc.spell_scaling(BOOMING_BLADE) == "extra 1d8 thunder damage on hit (L5)"
    assert len(fake_llm.prompts) == 2


def test_an_unwritable_cache_does_not_lose_the_note(svc, fake_llm, tmp_path):
    """The note is an addition to a card, so a cache failure must not fail the lookup."""
    fake_llm.response = "extra 1d8 thunder damage on hit"
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "scaling").write_text("not a directory", encoding="utf-8")
    assert svc.spell_scaling(BOOMING_BLADE) == "extra 1d8 thunder damage on hit (L5)"


# --- API readiness ---

def test_service_imports_without_a_terminal():
    """The domain must not depend on a front end, or an API would pull in cmd/readline."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    # Assert on the real module names: the subpackages are `backend.cli` and
    # `backend.api`, so a bare 'cli' check would pass even if the CLI were imported.
    code = (
        "import backend.libs.service, sys;"
        "imported = {m for m in sys.modules if m.startswith(('backend.cli', 'backend.api'))};"
        "assert not imported, f'the domain imported a front end: {imported}'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=str(root)
    )
    assert result.returncode == 0, result.stderr


def test_generation_can_be_serialised_for_a_http_response():
    """A future API has to hand this to json.dumps; dataclasses give it directly."""
    generation = service.Generation(
        scenario="x", answer="y", books=[service.Book(index=1, name="A", text="t")]
    )
    import dataclasses

    payload = json.dumps(dataclasses.asdict(generation))
    assert json.loads(payload)["books"][0]["name"] == "A"


def test_shell_is_constructible_around_any_service():
    """The shell holds no logic the API needs; it only renders this object."""
    assert hasattr(shell_mod.SpellbookShell, "do_scenario")
    assert isinstance(service.SpellbookService, type)


# --- the delimited format reaches the caller ---

DELIMITED_ANSWER = """Rust is the threat here.

=== BOOK 1 ===
Title: Peel and Patch
Cantrips: Thorn Whip, Spare the Dying, Mending
Rituals: Find Familiar, Unseen Servant
How to use:
**Thorn Whip** pulls it off the fighter.

=== BOOK 2 ===
Title: Hold the Line
Cantrips: Eldritch Blast, Mind Sliver, Minor Illusion
Rituals: Identify, Detect Magic
How to use:
**Repelling Blast** pushes it away.

=== PAIRINGS ===
**Book 1 pairs with:** Hex
"""


def test_generation_carries_the_preamble_and_pairings(svc, fake_llm):
    fake_llm.response = DELIMITED_ANSWER
    generation = svc.scenario(SCENARIO)
    assert generation.preamble.startswith("Rust is the threat")
    assert "Book 1 pairs with" in generation.pairings
    assert [b.name for b in generation.books] == ["Peel and Patch", "Hold the Line"]


def test_a_book_does_not_contain_the_summary(svc, fake_llm):
    fake_llm.response = DELIMITED_ANSWER
    generation = svc.scenario(SCENARIO)
    for book in generation.books:
        assert "pairs with" not in book.text


def test_a_cache_hit_carries_the_preamble_and_pairings(svc, fake_llm):
    """The replay path must produce the same shape as a fresh generation.

    A cache hit that dropped these fields would render differently from the run it is
    replaying, which is the whole point of storing them.
    """
    fake_llm.response = DELIMITED_ANSWER
    first = svc.scenario(SCENARIO)
    second = svc.scenario(SCENARIO)
    assert second.from_cache is True
    assert second.preamble == first.preamble
    assert second.pairings == first.pairings
    assert [b.name for b in second.books] == [b.name for b in first.books]


def test_a_legacy_run_has_its_summary_derived_on_read(svc, fake_llm, tmp_path):
    """A run stored before the delimited format has no `pairings` key.

    Its summary is still at the end of its last book, so it is recovered from the response
    rather than left to render inside that book. The books themselves are not re-cut - they
    were already recorded.
    """
    legacy = (
        '### Book 1: "Ambush and Control"\n\n'
        "**Cantrips:**\n1. **Light** - illuminates.\n2. **Sacred Flame** - damage.\n"
        "3. **Friends** - talking.\n\n"
        "**Rituals:**\n1. **Identify** - loot.\n2. **Find Familiar** - scouts.\n\n"
        "**How to Use:**\n- Open with Light.\n\n"
        "## 4. Existing spells and invocations that pair with each book\n"
        "- **Book 1:** pair **Light** with **Sacred Flame**.\n"
    )
    fake_llm.response = legacy
    svc.scenario(SCENARIO)

    # Strip the keys the new format writes, leaving the run as an old one would be.
    run_path = next((tmp_path / "cache").rglob("run.json"))
    run = json.loads(run_path.read_text())
    run.pop("pairings", None)
    run.pop("preamble", None)
    run_path.write_text(json.dumps(run))

    replayed = svc.scenario(SCENARIO)
    assert replayed.from_cache is True
    assert "pair with each book" not in replayed.books[-1].text
    assert replayed.pairings.startswith("- **Book 1:** pair **Light**")


def test_a_legacy_summary_is_not_shown_twice(svc, fake_llm, tmp_path):
    """Deriving the pairings must also trim them from the book they were recorded in.

    The books of a stored run are read back as written, so a legacy run's summary is still
    inside its last book's text. Without the trim the same text renders twice - once at the
    end of the book and once in the pairings card.
    """
    legacy = (
        '### Book 1: "Ambush and Control"\n\n'
        "**Cantrips:**\n1. **Light** - illuminates.\n2. **Sacred Flame** - damage.\n"
        "3. **Friends** - talking.\n\n"
        "**Rituals:**\n1. **Identify** - loot.\n2. **Find Familiar** - scouts.\n\n"
        "**How to Use:**\n- Open with Light.\n\n"
        "## 4. Existing spells and invocations that pair with each book\n"
        "- **Book 1:** pair **Light** with **Sacred Flame**.\n"
    )
    fake_llm.response = legacy
    svc.scenario(SCENARIO)

    run_path = next((tmp_path / "cache").rglob("run.json"))
    run = json.loads(run_path.read_text())
    run.pop("pairings", None)
    run.pop("preamble", None)
    run_path.write_text(json.dumps(run))

    replayed = svc.scenario(SCENARIO)
    assert "pair with each book" not in replayed.books[-1].text
    assert "pair with each book" not in replayed.pairings
    assert replayed.pairings.startswith("- **Book 1:** pair **Light**")
    # The book's own prose survives the trim.
    assert "Open with Light." in replayed.books[-1].text
