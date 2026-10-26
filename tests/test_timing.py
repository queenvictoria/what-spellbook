"""Per-phase timings: measurement, persistence and aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.libs import cache, config, prompts, service, timing

SCENARIO = "A rust monster eats the fighter's plate armour mid-fight."


def _entry(directory, phases, total=None, name="1-hold-the-line"):
    directory.mkdir(parents=True, exist_ok=True)
    # Non-numeric values are written through deliberately, so a corrupt entry can be
    # tested; only attempt the sum when the values actually add up.
    numeric = all(isinstance(v, (int, float)) for v in phases.values())
    payload = {
        "schema_version": cache.SCHEMA_VERSION,
        "timings": {
            "phases": phases,
            "total_seconds": total if total is not None else (sum(phases.values()) if numeric else None),
        },
    }
    (directory / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory / "run.json"


# --- the stopwatch ---


def test_timer_records_each_phase():
    # The clock is read once to start, twice per phase (open and close), once at the end.
    ticks = iter([0.0, 1.0, 2.0, 2.0, 4.5, 4.5])
    timer = service.Timer(clock=lambda: next(ticks))
    with timer.phase("retrieval"):
        pass
    with timer.phase("books"):
        pass

    measured = timer.measured()
    assert measured["phases"] == {"retrieval": 1.0, "books": 2.5}
    assert measured["total_seconds"] == 4.5


def test_timer_records_a_phase_that_raises():
    """A failed run must still say how far it got and where it died."""
    ticks = iter([0.0, 0.0, 2.0, 2.0])
    timer = service.Timer(clock=lambda: next(ticks))
    with pytest.raises(RuntimeError):
        with timer.phase("retrieval"):
            raise RuntimeError("index unavailable")

    assert timer.measured()["phases"] == {"retrieval": 2.0}


def test_timer_reports_unaccounted_time():
    """Time outside the phases is real - it must not silently vanish."""
    # start 0.0, phase opens 2.0, closes 3.0, end 9.0 -> 1.0 accounted, 8.0 unaccounted.
    ticks = iter([0.0, 2.0, 3.0, 9.0])
    timer = service.Timer(clock=lambda: next(ticks))
    with timer.phase("retrieval"):
        pass

    measured = timer.measured()
    assert measured["phases"]["retrieval"] == 1.0
    assert measured["total_seconds"] == 9.0
    assert measured["unaccounted_seconds"] == 8.0


def test_unaccounted_time_is_never_negative():
    """A clock that steps backwards must not produce a negative duration."""
    ticks = iter([0.0, 5.0, 6.0, 1.0])
    timer = service.Timer(clock=lambda: next(ticks))
    with timer.phase("retrieval"):
        pass
    assert timer.measured()["unaccounted_seconds"] == 0.0


def _only_run_file(root):
    """The single run.json under ``root``, for a test that wrote exactly one."""
    found = list(Path(root).rglob(cache.RUN_FILENAME))
    assert len(found) == 1, f"expected one run file, found {len(found)}"
    return found[0]


# --- persistence ---


def test_save_run_stores_timings(tmp_path):
    cache.save_run(
        answer="## Book 1 - Hold\n\n**Cantrips:** Light",
        cache_dir=tmp_path,
        character="Lois",
        level=5,
        party="Barbarian",
        db_version=3,
        scenario=SCENARIO,
        timings={"phases": {"retrieval": 2.0}, "total_seconds": 3.0},
    )
    run = json.loads(_only_run_file(tmp_path).read_text(encoding="utf-8"))
    assert run["timings"]["phases"]["retrieval"] == 2.0


def test_save_run_without_timings_stores_an_empty_block(tmp_path):
    cache.save_run(
        answer="## Book 1 - Hold\n\n**Cantrips:** Light",
        cache_dir=tmp_path,
        character="Lois",
        level=5,
        party="Barbarian",
        db_version=3,
        scenario=SCENARIO,
    )
    run = json.loads(_only_run_file(tmp_path).read_text(encoding="utf-8"))
    assert run["timings"] == {}


def test_schema_version_was_not_bumped_for_an_added_optional_key():
    """Timings are optional: an entry without them reads as "no data", not as old.

    Bumping for an additive change discards every cached run and every rating, and
    costs the user a fresh model call for nothing.
    """
    assert cache.SCHEMA_VERSION == 2


# --- aggregation ---


def test_summary_is_empty_with_no_history(tmp_path):
    stats = timing.summary(tmp_path)
    assert stats["samples"] == 0
    assert stats["phases"] == {}
    assert stats["total_seconds"] is None


def test_summary_uses_a_recent_median_as_the_typical_value(tmp_path):
    """A single outlier must not poison the estimate; a real trend must still show.

    The latest sample alone is fragile (one rate-limited run skews every later estimate),
    so the typical value is a median over a short recent window.
    """
    import os
    import time as _time

    for index, seconds in enumerate([4.0, 5.0, 6.0]):
        _entry(tmp_path / f"r{index}" / "1", {"retrieval": seconds}, total=seconds)
    outlier = _entry(tmp_path / "slow" / "1", {"retrieval": 400.0}, total=400.0)
    os.utime(outlier, (_time.time() + 50, _time.time() + 50))

    stats = timing.summary(tmp_path)
    phase = stats["phases"]["retrieval"]
    assert phase["latest_seconds"] == 400.0
    # Four samples: recent window is all of them, so the median rejects the outlier.
    assert phase["typical_seconds"] == 5.5


def test_typical_value_follows_a_sustained_change(tmp_path):
    """A model change should move the estimate, not be averaged away forever."""
    import os
    import time as _time

    base = _time.time()
    for index, seconds in enumerate([2.0] * 6):
        entry = _entry(tmp_path / f"old{index}" / "1", {"retrieval": seconds}, total=seconds)
        os.utime(entry, (base - 1000 + index, base - 1000 + index))
    for index, seconds in enumerate([50.0] * 5):
        entry = _entry(tmp_path / f"new{index}" / "1", {"retrieval": seconds}, total=seconds)
        os.utime(entry, (base + index, base + index))

    # The most recent five samples are all the slow ones, so the window sees only those.
    assert timing.summary(tmp_path)["phases"]["retrieval"]["typical_seconds"] == 50.0


def test_estimates_need_more_than_one_sample(tmp_path):
    """One run is not a basis for predicting the next; do not guess."""
    _entry(tmp_path / "a" / "1", {"retrieval": 4.0})
    assert timing.estimates(tmp_path) == {}

    _entry(tmp_path / "b" / "1", {"retrieval": 6.0})
    # Two samples in the window, so the estimate is their median.
    assert timing.estimates(tmp_path) == {"retrieval": 5.0}


def test_summary_keeps_samples_that_are_missing_a_phase(tmp_path):
    """A run that died in the model call still has a valid retrieval time."""
    _entry(tmp_path / "a" / "1", {"retrieval": 2.0})
    _entry(tmp_path / "b" / "1", {"retrieval": 3.0, "books": 30.0})

    stats = timing.summary(tmp_path)
    assert stats["phases"]["retrieval"]["count"] == 2
    assert stats["phases"]["books"]["count"] == 1


def test_summary_ignores_unreadable_and_empty_runs(tmp_path):
    broken = tmp_path / "a" / "1"
    broken.mkdir(parents=True)
    (broken / "run.json").write_text("{not json", encoding="utf-8")
    _entry(tmp_path / "b" / "1", {})

    assert timing.summary(tmp_path)["samples"] == 0


def test_summary_ignores_non_numeric_phase_values(tmp_path):
    """A corrupt value must be skipped, not crash or be summed into the total."""
    _entry(tmp_path / "a" / "1", {"retrieval": "slow"})
    stats = timing.summary(tmp_path)
    assert stats["samples"] == 0
    assert stats["phases"] == {}


def test_format_summary_is_a_single_readable_line(tmp_path):
    _entry(tmp_path / "a" / "1", {"retrieval": 4.0, "books": 30.0}, total=34.0)
    _entry(tmp_path / "b" / "1", {"retrieval": 6.0, "books": 40.0}, total=46.0)

    line = timing.format_summary(timing.summary(tmp_path), prefix="Typical: ")
    assert line.startswith("Typical: ")
    assert "\n" not in line
    assert "Fetching spells from the grimoire" in line
    assert "typical total" in line


def test_format_summary_handles_no_history():
    assert "No timing history" in timing.format_summary({"phases": {}})


def test_run_files_are_newest_first(tmp_path):
    """The newest sample must be findable, since 'typical' is the latest value."""
    import os
    import time as _time

    first = _entry(tmp_path / "a" / "1", {"retrieval": 1.0})
    second = _entry(tmp_path / "b" / "1", {"retrieval": 2.0})
    os.utime(first, (_time.time() - 100, _time.time() - 100))

    order = timing.run_files(tmp_path)
    assert order[0] == second
    assert order[-1] == first


def test_phase_names_match_the_service_and_the_labels():
    """A renamed phase would silently yield an empty breakdown, not an error."""
    assert set(timing.PHASES) <= set(timing.PHASE_LABELS)
    assert len(timing.PHASE_LABELS) == len(timing.PHASES)


# --- the prompt follows the configured count ---


@pytest.mark.parametrize("count", [1, 2, 3, 5, 9])
def test_full_prompt_asks_for_the_requested_number_of_books(count):
    prompt = prompts.full_prompt(
        character_text="SHEET",
        rule_context="RULES",
        scenario="SCENARIO",
        pool_text="POOL",
        books=count,
    )
    assert f"Produce EXACTLY {count} distinct" in prompt
    assert f'"Book {count}"' in prompt
    # The old hard-coded wording must be gone, or the model gets two instructions.
    assert "EXACTLY 3" not in prompt or count == 3


def test_full_prompt_labels_every_book():
    prompt = prompts.full_prompt(
        character_text="SHEET", rule_context="RULES", scenario="S",
        pool_text="POOL", books=4,
    )
    for n in range(1, 5):
        assert f'"Book {n}"' in prompt
    assert '"Book 5"' not in prompt


def test_full_prompt_defaults_to_the_configured_count():
    prompt = prompts.full_prompt(
        character_text="SHEET", rule_context="RULES", scenario="S", pool_text="POOL",
    )
    assert f"EXACTLY {config.BOOK_COUNT} distinct" in prompt


# --- BOOKS env variable ---


def test_book_count_defaults_when_unset():
    assert config.select_book_count({}) == config.BOOK_COUNT


@pytest.mark.parametrize("value", ["1", "2", "3", "4", "9"])
def test_book_count_accepts_in_range_values(value):
    assert config.select_book_count({"BOOKS": value}) == int(value)


@pytest.mark.parametrize("value", ["0", "-3", "10", "999"])
def test_book_count_clamps_out_of_range_values(value):
    result = config.select_book_count({"BOOKS": value})
    assert config.MIN_BOOKS <= result <= config.MAX_BOOKS


def test_book_count_survives_a_typo():
    """A bad value in an untracked file must not fail the whole run."""
    assert config.select_book_count({"BOOKS": "lots"}) == config.BOOK_COUNT
    assert config.select_book_count({"BOOKS": "3.5"}) == config.BOOK_COUNT


def test_book_count_tolerates_quotes_and_whitespace():
    assert config.select_book_count({"BOOKS": ' " 4 " '}) == 4


def test_book_count_treats_blank_as_unset():
    assert config.select_book_count({"BOOKS": "   "}) == config.BOOK_COUNT


# --- service ---


def test_service_uses_the_configured_book_count(spellbook):
    assert spellbook.books == config.BOOK_COUNT


def test_service_accepts_an_explicit_book_count(fake_db):
    svc = service.SpellbookService(fake_db, {"Class": "Warlock"}, backend=object(), books=5)
    assert svc.books == 5


def test_scenario_records_timings(spellbook, fake_llm, monkeypatch):
    monkeypatch.setattr(config, "select_book_count", lambda *a, **k: 1)
    generation = spellbook.scenario(SCENARIO)
    assert generation.timings["total_seconds"] >= 0
    assert set(generation.timings["phases"]) == {"retrieval", "prompt", "books"}


def test_cached_generation_replays_stored_timings(loaded_shell):
    """A replayed run must report what the original cost, not zero."""
    spellbook = loaded_shell.spellbook
    first = spellbook.find_cached(loaded_shell.current_scenario)
    assert first is not None and first.timings["phases"]

    replay = spellbook.find_cached(loaded_shell.current_scenario)
    assert replay is not None
    assert replay.from_cache is True
    assert replay.timings == first.timings
