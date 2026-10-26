"""Tests for the caching wiring inside the shell.

`cache.py` covers the store itself; these tests cover the contract the shell has
to honour: every generated answer is written before the user can rate it, and
`/rate` and `/history` read back exactly what was written.
"""

import json
from pathlib import Path

import pytest

import cache
import main


# --- writing on generation ---

def test_scenario_caches_every_book(loaded_shell, cache_dir):
    files = sorted(cache_dir.rglob("*.json"))
    assert len(files) == 2
    assert {p.stem for p in files} == {"1-ambush-and-control", "2-denial-and-escape"}


def test_cache_is_keyed_by_character_level_party_dbversion_and_scenario(loaded_shell, cache_dir):
    key_dir = next(p for p in cache_dir.rglob("*.json")).parent
    assert key_dir.parent.name == "lois"
    assert key_dir.name.startswith("5-barbarian-fighter-druid-")
    assert key_dir.name.endswith(cache.scenario_fingerprint("We are ambushed on a narrow stone bridge."))


def test_cached_entry_holds_the_prompt_and_response(loaded_shell, cache_dir):
    entry = json.loads(sorted(cache_dir.rglob("*.json"))[0].read_text(encoding="utf-8"))
    assert entry["prompt"]["prompt"] == loaded_shell.last_prompt
    assert entry["response"] == loaded_shell.last_response
    assert "We are ambushed" in entry["prompt"]["prompt"]


def test_cached_entry_records_the_eligible_pool(loaded_shell, cache_dir):
    """The pool is the evidence for why only these books were possible."""
    entry = json.loads(sorted(cache_dir.rglob("*.json"))[0].read_text(encoding="utf-8"))
    assert "pool_cantrips" in entry["context"]
    assert "pool_rituals" in entry["context"]
    assert entry["context"]["database_version"] == main.INDEX_VERSION


def test_cached_entry_records_the_sibling_picks_for_context(loaded_shell, cache_dir):
    entry = json.loads(sorted(cache_dir.rglob("*.json"))[0].read_text(encoding="utf-8"))
    assert entry["output"]["picks"]["cantrips"] == ["Light", "Sacred Flame", "Friends"]


def test_shell_tracks_the_book_files_for_the_current_answer(loaded_shell):
    assert set(loaded_shell.book_files) == {"1-ambush-and-control", "2-denial-and-escape"}


def test_no_character_means_no_cache_write(shell, cache_dir, fake_llm):
    """Without a sheet there is no key to file the answer under."""
    fake_llm.response = "### Book 1: X\n\n**Cantrips:**\n1. **Light** - bright.\n"
    shell.onecmd("/scenario anything")
    assert shell.last_response
    assert not list(cache_dir.rglob("*.json"))


def test_a_second_identical_scenario_overwrites_the_same_entry(loaded_shell, cache_dir):
    loaded_shell.onecmd("/scenario We are ambushed on a narrow stone bridge.")
    assert len(list(cache_dir.rglob("*.json"))) == 2


def test_a_different_scenario_gets_its_own_directory(loaded_shell, cache_dir):
    loaded_shell.onecmd("/scenario A chase through the sewers.")
    assert len(list((cache_dir / "lois").iterdir())) == 2
    assert len(list(cache_dir.rglob("*.json"))) == 4


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
    assert "No cached books yet" in capsys.readouterr().out


def test_history_finds_entries_written_by_a_previous_session(loaded_shell, cache_dir, fake_db, fake_llm, monkeypatch):
    """The point of the cache: a new process can rate an old book."""
    monkeypatch.setattr(main, "build_llm", lambda: fake_llm)
    fresh = main.SpellbookShell(vector_db=fake_db, character_context="x", character={"Name": "Lois"})
    fresh.llm = fake_llm
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
    assert "rate" in main.SpellbookShell.COMMANDS
    assert "history" in main.SpellbookShell.COMMANDS
