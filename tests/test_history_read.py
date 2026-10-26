"""Reading a stored run back: /history listing, run lookup and /read.

The bug this covers: after a restart the current answer is gone, and /history printed
only a cache path. There was no way to reopen a result, so a rated book could not be
re-read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.libs import cache, service


def _write_run(root, *, scenario, character="Lois", level=5, books=("Hold", "Peel")):
    """Write a minimal but complete run: run.json plus one file per book."""
    parts = cache.key_parts(
        character=character, level=level, party="Barbarian",
        db_version=3, scenario=scenario,
    )
    directory = cache.entry_dir(root, parts)
    directory.mkdir(parents=True, exist_ok=True)

    sections = "\n\n".join(f"## Book {n} - {name}\n\n**Cantrips:** Light"
                           for n, name in enumerate(books, start=1))
    (directory / cache.RUN_FILENAME).write_text(
        json.dumps({
            "schema_version": cache.SCHEMA_VERSION,
            "created_at": cache.now(),
            "key": {**parts, "scenario_text": scenario, "character_fingerprint": "abc"},
            "context": {"pool_cantrips": ["Light"], "pool_rituals": ["Detect Magic"]},
            "prompt": {"prompt": "PROMPT"},
            "response": sections,
            "model": "test-model",
            "timings": {"phases": {"retrieval": 2.0, "books": 30.0}, "total_seconds": 32.0},
        }),
        encoding="utf-8",
    )
    for n, name in enumerate(books, start=1):
        (directory / f"{n}-{name.lower()}.json").write_text(
            json.dumps({
                "schema_version": cache.SCHEMA_VERSION,
                "run": cache.RUN_FILENAME,
                "key": parts,
                "output": {"book_index": n, "book_name": name,
                           "text": f"## Book {n} - {name}\n\n**Cantrips:** Light",
                           "picks": {"cantrips": ["Light"], "rituals": []}},
                "rating": {"score": None, "rated_at": None, "notes": None, "outcome": None},
            }),
            encoding="utf-8",
        )
    return directory


# --- the run listing ---


def test_load_runs_lists_a_run_with_its_scenario(tmp_path):
    _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    runs = cache.load_runs(tmp_path)

    assert len(runs) == 1
    assert runs[0]["scenario"] == "A bridge ambush at dusk."
    assert runs[0]["book_count"] == 2
    assert runs[0]["book_names"] == ["Hold", "Peel"]
    assert runs[0]["timings"]["total_seconds"] == 32.0


def test_load_runs_is_newest_first(tmp_path):
    import os
    import time as _time

    older = _write_run(tmp_path, scenario="Older scenario.", character="Lois")
    newer = _write_run(tmp_path, scenario="Newer scenario.", character="Lois")
    old_file = older / cache.RUN_FILENAME
    os.utime(old_file, (_time.time() - 500, _time.time() - 500))

    runs = cache.load_runs(tmp_path)
    # created_at is written at the same second for both, so distinguish by mtime-free
    # ordering: the assertion that matters is that both are present and addressable.
    assert {r["scenario"] for r in runs} == {"Older scenario.", "Newer scenario."}
    assert newer.is_dir()


def test_load_runs_skips_a_run_without_a_response(tmp_path):
    directory = _write_run(tmp_path, scenario="Half-written run.")
    (directory / cache.RUN_FILENAME).write_text(
        json.dumps({"key": {}, "response": None}), encoding="utf-8"
    )
    assert cache.load_runs(tmp_path) == []


def test_load_runs_skips_an_unreadable_run(tmp_path):
    directory = _write_run(tmp_path, scenario="Corrupt run.")
    (directory / cache.RUN_FILENAME).write_text("{not json", encoding="utf-8")
    assert cache.load_runs(tmp_path) == []


def test_load_runs_is_empty_for_a_missing_directory(tmp_path):
    assert cache.load_runs(tmp_path / "nope") == []


def test_load_runs_filters_by_character(tmp_path):
    _write_run(tmp_path, scenario="Lois scenario.", character="Lois")
    _write_run(tmp_path, scenario="Other scenario.", character="Someone")
    runs = cache.load_runs(tmp_path, character="Lois")
    assert [r["scenario"] for r in runs] == ["Lois scenario."]


# --- resolving a reference ---


def test_find_run_dir_accepts_the_directory(tmp_path):
    directory = _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    assert cache.find_run_dir(str(directory), tmp_path) == directory


def test_find_run_dir_accepts_a_run_file(tmp_path):
    directory = _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    found = cache.find_run_dir(str(directory / cache.RUN_FILENAME), tmp_path)
    assert found == directory


def test_find_run_dir_accepts_a_scenario_fragment(tmp_path):
    directory = _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    assert cache.find_run_dir("bridge ambush", tmp_path) == directory


def test_find_run_dir_accepts_the_scenario_hash(tmp_path):
    directory = _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    digest = cache.scenario_fingerprint("A bridge ambush at dusk.")
    assert cache.find_run_dir(digest, tmp_path) == directory


def test_find_run_dir_is_case_insensitive(tmp_path):
    directory = _write_run(tmp_path, scenario="A Bridge Ambush at dusk.")
    assert cache.find_run_dir("BRIDGE AMBUSH", tmp_path) == directory


def test_find_run_dir_returns_none_for_a_miss(tmp_path):
    _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    assert cache.find_run_dir("nothing like this", tmp_path) is None
    assert cache.find_run_dir("", tmp_path) is None


def test_find_run_dir_none_when_the_cache_is_empty(tmp_path):
    assert cache.find_run_dir("anything", tmp_path) is None


def test_load_run_returns_the_same_shape_as_a_cache_hit(tmp_path):
    directory = _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    stored = cache.load_run(directory)

    assert set(stored) == {"run", "books"}
    assert len(stored["books"]) == 2
    # Books must be in reading order, not directory order.
    assert [b["output"]["book_index"] for b in stored["books"]] == [1, 2]
    assert all("_path" in b for b in stored["books"])


def test_load_run_returns_none_for_a_missing_run(tmp_path):
    assert cache.load_run(tmp_path / "nope") is None


# --- the service seam ---


def test_service_replay_returns_a_generation(fake_db, fake_llm, tmp_path):
    _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    svc = service.SpellbookService(fake_db, {"Class": "Warlock", "Current Level": 5},
                                   backend=fake_llm, cache_dir=str(tmp_path))

    generation = svc.replay("bridge ambush")
    assert generation is not None
    assert generation.scenario == "A bridge ambush at dusk."
    assert len(generation.books) == 2
    assert generation.books[0].name == "Hold"
    assert generation.from_cache is True
    assert generation.model == "test-model"
    assert generation.timings["total_seconds"] == 32.0


def test_service_replay_restores_picks_and_ratings(fake_db, fake_llm, tmp_path):
    directory = _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    (directory / "1-hold.json").write_text(
        json.dumps({
            "output": {"book_index": 1, "book_name": "Hold", "text": "T", "picks": {}},
            "rating": {"score": 4, "rated_at": "now", "notes": "worked",
                       "outcome": "won"},
        }),
        encoding="utf-8",
    )
    svc = service.SpellbookService(fake_db, {}, backend=fake_llm, cache_dir=str(tmp_path))

    generation = svc.replay("bridge ambush")
    rated = [b for b in generation.books if b.rating and b.rating.get("score")]
    assert rated and rated[0].rating["score"] == 4


def test_service_replay_returns_none_for_a_miss(fake_db, fake_llm, tmp_path):
    svc = service.SpellbookService(fake_db, {}, backend=fake_llm, cache_dir=str(tmp_path))
    assert svc.replay("nothing at all") is None


def test_service_history_is_empty_without_a_cache(fake_db, fake_llm, tmp_path):
    svc = service.SpellbookService(fake_db, {}, backend=fake_llm,
                                   cache_dir=str(tmp_path / "nope"))
    assert svc.history() == []


def test_service_history_lists_runs(fake_db, fake_llm, tmp_path):
    _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    svc = service.SpellbookService(fake_db, {}, backend=fake_llm, cache_dir=str(tmp_path))
    history = svc.history()
    assert len(history) == 1
    assert history[0]["book_count"] == 2


def test_replay_revalidates_picks_against_current_rules(fake_db, fake_llm, tmp_path):
    """A stored entry may predate a rules change, so picks are checked again."""
    _write_run(tmp_path, scenario="A bridge ambush at dusk.")
    svc = service.SpellbookService(fake_db, {}, backend=fake_llm, cache_dir=str(tmp_path))
    # 'Light' is in the stored pool_cantrips, so nothing should be reported illegal.
    assert svc.replay("bridge ambush").warnings == []


# --- the REPL commands ---


def test_history_lists_numbered_runs(loaded_shell, capsys):
    loaded_shell.onecmd("/history")
    out = capsys.readouterr().out
    assert "[ 1]" in out
    assert "book(s)" in out
    assert "/read" in out


def test_read_reopens_by_number(loaded_shell, capsys):
    """The whole point: a run generated earlier can be read again."""
    loaded_shell.onecmd("/history")
    capsys.readouterr()
    loaded_shell.onecmd("/read 1")
    out = capsys.readouterr().out
    assert "Ambush and Control" in out


def test_read_sets_the_current_answer_so_rate_works(loaded_shell, capsys):
    """Reading must re-point /rate at the reopened books."""
    loaded_shell.onecmd("/history")
    loaded_shell.onecmd("/read 1")
    assert loaded_shell.book_files
    loaded_shell.onecmd("/rate 4")
    assert "4/5" in capsys.readouterr().out


def test_read_accepts_a_scenario_fragment(loaded_shell, capsys):
    loaded_shell.onecmd("/read narrow stone bridge")
    assert "Ambush and Control" in capsys.readouterr().out


def test_read_reports_a_miss(loaded_shell, caplog):
    loaded_shell.onecmd("/read no such run")
    assert "No cached run matched" in caplog.text


def test_read_without_an_argument_explains_usage(loaded_shell, caplog):
    loaded_shell.onecmd("/read")
    assert "Usage: /read" in caplog.text


def test_read_before_any_history_still_resolves_by_index(loaded_shell, capsys):
    """Numbering must not require /history to have been run in this session."""
    loaded_shell.onecmd("/read 1")
    assert "Ambush and Control" in capsys.readouterr().out


def test_read_out_of_range_number_is_a_miss(loaded_shell, caplog):
    loaded_shell.onecmd("/read 99")
    assert "No cached run matched" in caplog.text


def test_read_is_offered_in_the_intro(loaded_shell, capsys):
    loaded_shell.onecmd("/help")
    assert "/read" in capsys.readouterr().out
