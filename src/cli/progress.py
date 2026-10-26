"""A Claude-style stage display for long-running steps, with measured timings.

Fetching candidates embeds the scenario, and generating an answer waits on the model -
together tens of seconds. A silent terminal makes that indistinguishable from a hang,
so each stage is announced and, when it ends, reported *with how long it took*.

Once a couple of runs are in the cache the typical duration of each stage is known, so
a running stage shows a rough estimate and the total is reported when the run ends.
Estimates come from ``backend.timing``; with no history, none is invented.

`rich` gives a live status line on a terminal; when it is unavailable or output is
redirected, the same stages are printed as plain lines so logs stay readable. The backend
calls a plain ``emit(message)`` callback, so it never imports `rich`.
"""

from __future__ import annotations

import time

try:
    from rich.console import Console

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    RICH_AVAILABLE = False


def _short(seconds: float) -> str:
    """Human-readable duration: '4.2s', '1m 12s'."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}m {rest:02d}s"


def _on_terminal(console=None) -> bool:
    if not RICH_AVAILABLE:
        return False
    try:
        return (console or Console()).is_terminal
    except Exception:
        return False


class StageProgress:
    """Callable that announces a stage, then completes it on the next call.

    Used as the ``progress`` argument to the service. Each call closes the previous
    stage and opens a new one, so the caller passes a message and nothing else:

        stage("Fetching spells from the grimoire")   # opens
        stage("Crafting the prompt")                 # completes the fetch, opens craft
        stage.done()                                 # completes the last one

    Time is measured here rather than taken from the service, because this layer knows
    which *display* stage is running. That also keeps the measurement correct if a stage
    is reordered, and gives a total that includes any wait the backend does not own.
    """

    def __init__(self, *, enabled=True, console=None, estimates=None, clock=time.monotonic):
        self.enabled = enabled
        self.console = console
        # Typical seconds per display stage, keyed by the stage message. A stage with
        # no history shows no estimate rather than a fabricated one.
        self.estimates = dict(estimates or {})
        self._clock = clock
        self._status = None
        self._last = None
        self._started = None
        self.completed: list[tuple[str, float]] = []

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        self.done()
        self._last = message
        self._started = self._clock()

        if _on_terminal(self.console):
            console = self.console or Console()
            self._status = console.status(f"[bold cyan]{self._label(message)}[/bold cyan]")
            self._status.start()
        else:
            print(f"... {self._label(message)}")

    def _label(self, message: str) -> str:
        """Stage text, with an estimate when one is known from past runs."""
        estimate = self.estimates.get(message)
        if estimate is None:
            return f"{message}..."
        return f"{message}... (~{_short(estimate)})"

    def done(self, message: str | None = None) -> None:
        """Complete the in-flight stage. Safe to call when nothing is running."""
        if self._last is None:
            return
        finished, self._last = self._last, None

        elapsed = 0.0
        if self._started is not None:
            elapsed = max(0.0, self._clock() - self._started)
            self.completed.append((finished, elapsed))
            self._started = None

        if self._status is not None:
            self._status.stop()
            self._status = None
        if self.enabled and not _on_terminal(self.console):
            print(f"    done: {message or finished} ({_short(elapsed)})")

    @property
    def elapsed_total(self) -> float:
        return sum(seconds for _name, seconds in self.completed)

    def report(self) -> str:
        """One line naming what each stage cost, for the log."""
        if not self.completed:
            return ""
        parts = [f"{name}: {_short(seconds)}" for name, seconds in self.completed]
        return f"{'; '.join(parts)} | total {_short(self.elapsed_total)}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.done()
        return False


class SilentProgress:
    """Progress that says nothing, for API callers and tests."""

    enabled = False
    completed: list = []

    def __call__(self, message: str) -> None:
        return None

    def done(self, message: str | None = None) -> None:
        return None

    @property
    def elapsed_total(self) -> float:
        return 0.0

    def report(self) -> str:
        return ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
