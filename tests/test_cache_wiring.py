"""Tests for the caching wiring inside the shell.

`cache.py` covers the store itself; these tests cover the contract the shell has
to honour: every generated answer is written before the user can rate it, and
`/rate` and `/history` read back exactly what was written.
"""

import json
from pathlib import Path

import pytest

from backend.cli.shell import SpellbookShell
from backend.libs import cache, config, service


# --- writing on generation ---

def test_scenario_caches_every_book(loaded_shell, cache_dir):
    files = sorted(cache_dir.rglob("*.json"))
    assert len(files) == 3, "one shared run file plus one file per book"
    assert {p.stem for p in files} == {"run", "1-ambush-and-control", "2-denial-and-escape"}


def test_cache_is_keyed_by_character_level_party_dbversion_and_scenario(loaded_shell, cache_dir):
    key_dir = next(cache_dir.rglob(cache.RUN_FILENAME)).parent
    assert key_dir.parent.name == "lois"
    assert key_dir.name.startswith("5-barbarian-fighter-druid-")
    assert key_dir.name.endswith(cache.scenario_fingerprint("We are ambushed on a narrow stone bridge."))


def test_cached_run_holds_the_prompt_and_response(loaded_shell, cache_dir):
    """The prompt is run-wide, so it is stored once in run.json, not per book."""
    run = json.loads(next(cache_dir.rglob(cache.RUN_FILENAME)).read_text(encoding="utf-8"))
    assert run["prompt"]["prompt"] == loaded_shell.last_prompt
    assert run["response"] == loaded_shell.last_response
    assert "We are ambushed" in run["prompt"]["prompt"]


def test_cached_run_records_the_eligible_pool(loaded_shell, cache_dir):
    """The pool is the evidence for why only these books were possible."""
    run = json.loads(next(cache_dir.rglob(cache.RUN_FILENAME)).read_text(encoding="utf-8"))
    assert "pool_cantrips" in run["context"]
    assert "pool_rituals" in run["context"]
    assert run["context"]["database_version"] == config.INDEX_VERSION


def test_cached_book_records_its_own_picks(loaded_shell, cache_dir):
    book = json.loads(
        (cache_dir.rglob("1-*.json")).__next__().read_text(encoding="utf-8")
    )
    assert book["output"]["picks"]["cantrips"] == ["Light", "Sacred Flame", "Friends"]


def test_shell_tracks_the_book_files_for_the_current_answer(loaded_shell):
    assert set(loaded_shell.book_files) == {"1-ambush-and-control", "2-denial-and-escape"}


def test_no_character_means_no_cache_write(shell, cache_dir, fake_llm):
    """Without a sheet there is no key to file the answer under."""
    fake_llm.response = "### Book 1: X\n\n**Cantrips:**\n1. **Light** - bright.\n"
    shell.onecmd("/scenario anything")
    assert shell.last_response
    assert not list(cache_dir.rglob("*.json"))


def test_a_second_identical_scenario_is_served_from_the_cache(loaded_shell, cache_dir, fake_llm):
    """The whole point: a repeat must not reach the model."""
    before = len(fake_llm.prompts)
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(fake_llm.prompts) == before, "no second model call"
    assert len(list(cache_dir.rglob("*.json"))) == 3


def test_a_different_scenario_gets_its_own_directory(loaded_shell, cache_dir):
    loaded_shell.onecmd("/scenario A chase through the sewers.")
    assert len(list((cache_dir / "lois").iterdir())) == 2
    assert len(list(cache_dir.rglob("*.json"))) == 6


def test_a_failed_llm_call_writes_nothing(shell, cache_dir):
    shell.character = {"Name": "Lois", "Current Level": 5}
    shell.llm.response = ""
    shell.onecmd("/scenario anything")
    assert not list(cache_dir.rglob("*.json"))


def test_scenario_reassigns_book_files_each_run(loaded_shell, cache_dir):
    loaded_shell.llm.response = "### Book 1: Solo\n\n**Cantrips:**\n1. **Light** - bright.\n"
    loaded_shell.onecmd("/scenario A chase through the sewers.")
    assert set(loaded_shell.book_files) == {"1-solo"}


# --- /rate ---

def test_rate_all_books(loaded_shell, capsys):
    loaded_shell.onecmd("/rate 4")
    out = capsys.readouterr().out
    assert "Ambush and Control" in out
    assert "Denial and Escape" in out
    scores = [json.loads(p.read_text(encoding="utf-8"))["rating"]["score"]
              for p in map(Path, loaded_shell.book_files.values())]
    assert scores == [4, 4]


def test_rate_one_book_by_name(loaded_shell):
    loaded_shell.onecmd("/rate 5 ambush")
    entries = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in map(Path, loaded_shell.book_files.values())}
    assert entries["1-ambush-and-control"]["rating"]["score"] == 5
    assert entries["2-denial-and-escape"]["rating"]["score"] is None


def test_rate_one_book_by_number(loaded_shell):
    loaded_shell.onecmd("/rate 2 2")
    entries = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in map(Path, loaded_shell.book_files.values())}
    assert entries["2-denial-and-escape"]["rating"]["score"] == 2
    assert entries["1-ambush-and-control"]["rating"]["score"] is None


def test_rate_rejects_a_score_outside_one_to_five(loaded_shell, caplog):
    with caplog.at_level("ERROR"):
        loaded_shell.onecmd("/rate 9")
    assert "Usage" in caplog.text
    assert all(json.loads(Path(p).read_text(encoding="utf-8"))["rating"]["score"] is None
               for p in loaded_shell.book_files.values())


def test_rate_with_no_argument_explains_usage(loaded_shell, caplog):
    with caplog.at_level("ERROR"):
        loaded_shell.onecmd("/rate")
    assert "Usage" in caplog.text


def test_rate_unknown_book_reports_the_available_ones(loaded_shell, caplog):
    with caplog.at_level("ERROR"):
        loaded_shell.onecmd("/rate 3 nonexistent")
    assert "Available" in caplog.text


def test_rate_before_any_scenario_explains_what_to_do(shell, caplog):
    with caplog.at_level("ERROR"):
        shell.onecmd("/rate 5")
    assert "Nothing to rate" in caplog.text


def test_rate_survives_a_missing_cache_file(loaded_shell, caplog):
    """A hand-deleted file must not take down the REPL."""
    loaded_shell.book_files = {"1-gone": "/nonexistent/1-gone.json"}
    with caplog.at_level("ERROR"):
        loaded_shell.onecmd("/rate 3")
    assert "Could not rate" in caplog.text


# --- /history ---

def test_history_lists_cached_books(loaded_shell, capsys):
    loaded_shell.onecmd("/history")
    out = capsys.readouterr().out
    assert "Ambush and Control" in out
    assert "Denial and Escape" in out
    assert "unrated" in out


def test_history_shows_a_recorded_rating(loaded_shell, capsys):
    loaded_shell.onecmd("/rate 5 ambush")
    loaded_shell.onecmd("/history")
    assert "5/5" in capsys.readouterr().out


def test_history_is_empty_before_any_scenario(shell, cache_dir, capsys):
    shell.onecmd("/history")
    assert "No runs cached yet" in capsys.readouterr().out


def test_history_finds_entries_written_by_a_previous_session(
    loaded_shell, cache_dir, fake_db, fake_llm
):
    """The point of the cache: a new process can rate an old book."""
    fresh = SpellbookShell(
        service.SpellbookService(fake_db, {"Name": "Lois"}, backend=fake_llm,
                                 cache_dir=str(cache_dir)),
        show_progress=False,
    )
    fresh.onecmd("/history")
    assert not fresh.book_files, "a new session should not inherit ratings targets"
    assert cache.load_entries(cache_dir), "but the old books must still be on disk"


# --- help ---

def test_help_documents_the_new_commands(shell, capsys):
    shell.onecmd("/help")
    out = capsys.readouterr().out
    assert "/rate" in out
    assert "/history" in out


def test_commands_include_rate_and_history():
    assert "rate" in SpellbookShell.COMMANDS
    assert "history" in SpellbookShell.COMMANDS


# --- serving from the cache ---

def test_a_repeat_scenario_makes_no_model_call(loaded_shell, cache_dir):
    """The headline behaviour: same character and scenario, no regeneration."""
    before = len(loaded_shell.llm.prompts)
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(loaded_shell.llm.prompts) == before


def test_a_cache_hit_skips_retrieval_entirely(loaded_shell, fake_db):
    """Not just the model: no embedding call for the ranking lane either."""
    before = len(fake_db.as_retriever_calls)
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(fake_db.as_retriever_calls) == before
    assert len(fake_db.get_calls) == 2, "the pool lanes were only built once"


def test_a_cache_hit_replays_the_original_answer(loaded_shell, capsys):
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    out = capsys.readouterr().out
    assert "Reusing the cached books" in out
    assert "Ambush and Control" in out


def test_a_cache_hit_repoints_rate_at_the_cached_files(loaded_shell, cache_dir, capsys):
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    capsys.readouterr()
    loaded_shell.onecmd("/rate 3")
    assert "Rated 'Ambush and Control' 3/5." in capsys.readouterr().out
    book = json.loads((cache_dir.rglob("1-*.json")).__next__().read_text(encoding="utf-8"))
    assert book["rating"]["score"] == 3


def test_a_whitespace_only_change_still_hits_the_cache(loaded_shell):
    before = len(loaded_shell.llm.prompts)
    loaded_shell.onecmd("/scenario   We are ambushed on a narrow stone bridge.  ")
    assert len(loaded_shell.llm.prompts) == before


def test_a_different_scenario_regenerates(loaded_shell):
    before = len(loaded_shell.llm.prompts)
    loaded_shell.onecmd("/scenario A chase through the sewers.")
    assert len(loaded_shell.llm.prompts) == before + 1


def test_an_edited_sheet_regenerates(loaded_shell):
    """A changed sheet invalidates the cached advice, which was for the old build."""
    before = len(loaded_shell.llm.prompts)
    loaded_shell.character["Known/Prepared Base Spells"] = "Eldritch Blast, Hex"
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(loaded_shell.llm.prompts) == before + 1


def test_a_cache_hit_revalidates_the_picks(loaded_shell, cache_dir, caplog):
    """A cached answer is re-checked, not trusted: it may predate a rules change."""
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    with caplog.at_level("WARNING"):
        loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert "not an eligible" in caplog.text


def test_refresh_ignores_the_cache(loaded_shell, cache_dir):
    loaded_shell.spellbook.refresh = True
    before = len(loaded_shell.llm.prompts)
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(loaded_shell.llm.prompts) == before + 1


def test_a_broken_cache_file_falls_back_to_regenerating(loaded_shell, cache_dir, caplog):
    (cache_dir.rglob(cache.RUN_FILENAME)).__next__().write_text("{not json")
    before = len(loaded_shell.llm.prompts)
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(loaded_shell.llm.prompts) == before + 1


def test_no_character_means_no_cache_read(shell, cache_dir):
    """Without a sheet there is no key, so the model is always called."""
    before = len(shell.llm.prompts)
    shell.onecmd("/scenario anything")
    assert len(shell.llm.prompts) == before + 1
