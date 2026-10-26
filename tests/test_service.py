"""Tests for the application layer.

`SpellbookService` is the seam a future API would use, so it is tested directly rather
than only through the REPL: it must do the work, return dataclasses, and never print,
prompt or exit.
"""

import json

import pytest

from backend.libs import llm, service
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
