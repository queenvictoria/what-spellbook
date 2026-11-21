"""Aggregate the per-phase timings stored with each cached run.

A run records how long retrieval, prompt assembly and the model call each took, which
is what lets the progress display say how much longer a stage is likely to take rather
than just how long it has been going.

Two deliberate choices:

* **The median, not the mean.** Run times are dominated by one-off outliers - a cold
  model, a rate-limited request, a first-touch embedding model load. A mean is dragged
  around by them, so it predicts the *next* run badly. The median describes the typical
  run, which is exactly what an estimate wants.
* **The most recent sample wins for the headline figure.** A slower model or a bigger
  board changes the profile; weighting a hundred historical runs equally hides that.

Nothing here imports Chroma or LangChain: it reads the JSON files the cache writes.
"""

from __future__ import annotations

import json
from pathlib import Path

# Phase names are shared with the service; they are keys in the stored payload, so
# renaming one here without renaming it there would silently produce an empty
# breakdown rather than an error.
PHASES = ("retrieval", "prompt", "books")

# Human labels for each phase, in the order they happen.
PHASE_LABELS = {
    "retrieval": "Fetching spells from the grimoire",
    "prompt": "Crafting the prompt",
    "books": "Scribing the Books of Shadows",
}

# Every stage the service can announce, keyed by the message it announces it with.
#
# The service emits human labels - it has no idea what a client does with them, and the CLI
# prints them verbatim - while a streaming client switches on a stable key. This table is the
# one place the two spellings are tied together, so the keys the browser receives cannot drift
# from the words the terminal shows. A test asserts every message the service emits is in it.
#
# The last three are ask surfaces. They announce the work before the model call and nothing
# during it, so a client that wants to show "the model is writing" has to know the final stage
# from the operation, not from an event - see ``OPERATION_STAGES``.
STAGE_KEYS: dict[str, str] = {
    PHASE_LABELS["retrieval"]: "retrieval",
    PHASE_LABELS["prompt"]: "prompt",
    PHASE_LABELS["books"]: "books",
    "Refining the current choices": "refine",
    "Reading the character sheet": "character",
    "Consulting the 2024 SRD": "consulting",
    "Reading the rules": "reading",
    "Cogitating": "answering",
}

# ``emit(f"Attached {names}")`` names the documents on the way in, so it cannot be a fixed
# string. It is matched by prefix rather than by pattern because the key is the only part a
# client acts on and the rest of the line is prose for a human.
ATTACHED_PREFIX = "Attached "
ATTACHED_KEY = "attaching"

# The stages each streaming operation reports, in order - which is what lets a client show
# what is still to come rather than only what has happened.
#
# ``answering`` is the model call itself, and it is a *reported* stage rather than one a
# client infers from the last message it saw: the call is the longest part of every ask, and
# a panel that stopped at "Reading the rules" would look finished while it was still waiting.
OPERATION_STAGES: dict[str, tuple[str, ...]] = {
    "scenario": PHASES,
    "refine": ("refine", "answering"),
    "character": ("character", "answering"),
    "rules": ("consulting", "reading", "answering"),
    "selection": ("attaching", "consulting", "reading", "answering"),
}


def stage_key(message: str) -> str:
    """The stable key for a stage message, or the message itself when it is unknown.

    An unrecognised message keeps its own text as the key rather than being dropped: a stage
    added to the service but not to ``STAGE_KEYS`` then still reaches the browser, showing a
    label instead of nothing. Losing it silently is the failure this avoids.
    """
    if message.startswith(ATTACHED_PREFIX):
        return ATTACHED_KEY
    return STAGE_KEYS.get(message, message)


# Below this many samples a "typical" figure is noise, so no estimate is offered.
MIN_SAMPLES = 2

# How many recent samples the estimate is drawn from. A single latest sample is
# fragile: one rate-limited or otherwise slow run poisons every estimate after it until
# the next run lands. A median over a short recent window shrugs off a single outlier
# while still following a real trend (a model change, a longer scenario), which a median
# over the whole history would not.
RECENT_WINDOW = 5


def _median(values: list[float]) -> float:
    """Median of a non-empty list; for an even count, the mean of the two middles."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def run_files(cache_dir) -> list[Path]:
    """Every ``run.json`` under the cache, newest first by modification time."""
    root = Path(cache_dir)
    if not root.is_dir():
        return []
    paths = list(root.glob("*/*/run.json"))
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def _read_timings(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("timings") or {}


def collect(cache_dir, *, character: str | None = None) -> list[dict]:
    """Every usable timing sample, newest first.

    Samples missing a phase are kept: a run that failed during the model call still
    has a valid retrieval time, and discarding it would throw away real data. Only a
    payload with no phases at all is dropped.
    """
    samples = []
    for path in run_files(cache_dir):
        timings = _read_timings(path)
        phases = {k: float(v) for k, v in (timings.get("phases") or {}).items()
                  if isinstance(v, (int, float))}
        if not phases:
            continue
        samples.append({
            "path": str(path),
            "phases": phases,
            "total_seconds": timings.get("total_seconds"),
            "model": None,
        })
    return samples


def summary(cache_dir, *, character: str | None = None) -> dict:
    """Per-phase typical/median/latest/count, plus the total.

    ``typical`` is what an estimate should use: the latest value when there is one,
    otherwise the median. Empty when there is nothing to go on, so callers show no
    estimate rather than a fabricated one.
    """
    samples = collect(cache_dir, character=character)
    if not samples:
        return {"samples": 0, "phases": {}, "total_seconds": None}

    phases = {}
    for name in PHASES:
        values = [s["phases"][name] for s in samples if name in s["phases"]]
        if not values:
            continue
        phases[name] = {
            "label": PHASE_LABELS.get(name, name),
            "count": len(values),
            "median_seconds": round(_median(values), 3),
            # Newest first, so index 0 is the most recent sample of this phase.
            "latest_seconds": round(values[0], 3),
            "min_seconds": round(min(values), 3),
            "max_seconds": round(max(values), 3),
            # Recent median: follows a genuine trend but ignores one-off outliers.
            "typical_seconds": round(_median(values[:RECENT_WINDOW]), 3),
        }

    totals = [float(s["total_seconds"]) for s in samples
              if isinstance(s["total_seconds"], (int, float))]
    return {
        "samples": len(samples),
        "phases": phases,
        # Median, so one pathological run does not distort the headline.
        "total_seconds": round(_median(totals), 3) if totals else None,
    }


def estimates(cache_dir, *, character: str | None = None) -> dict[str, float]:
    """``{"retrieval": 12.4, ...}`` of typical seconds per phase, for progress display."""
    stats = summary(cache_dir, character=character)
    return {
        name: data["typical_seconds"]
        for name, data in stats["phases"].items()
        if data["count"] >= MIN_SAMPLES
    }


def format_summary(stats: dict, *, prefix: str = "") -> str:
    """One log line listing each phase, for after a run."""
    if not stats.get("phases"):
        return f"{prefix}No timing history yet."

    parts = [
        f"{PHASE_LABELS.get(name, name)}: {data['typical_seconds']:.1f}s "
        f"(median {data['median_seconds']:.1f}s over {data['count']})"
        for name, data in stats["phases"].items()
    ]
    total = stats.get("total_seconds")
    tail = f" | typical total {total:.1f}s" if total is not None else ""
    return f"{prefix}{'; '.join(parts)}{tail}"
