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
    from rich.console import Console, Group

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    RICH_AVAILABLE = False

try:
    from rich.live import Live
    from rich.progress_bar import ProgressBar
    from rich.text import Text

    LIVE_AVAILABLE = True
except ImportError:  # pragma: no cover
    LIVE_AVAILABLE = False


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


def _percent(elapsed: float, expected: float) -> int:
    """Progress percentage, clamped to 99 until the stage actually finishes.

    Showing 100% while a stage is still running is the one thing a progress bar must not
    do: it reads as "finished" and makes the following pause look like a hang.
    """
    if expected <= 0:
        return 0
    return max(0, min(99, int(elapsed / expected * 100)))


class _StageLine:
    """A self-updating progress line: stage name, a bar, percent, and the clock.

    ``expected`` is the running total of every stage's estimate, so the bar tracks the
    whole run rather than restarting at zero for each phase - which is what makes the
    percentage and the ETA meaningful.
    """

    def __init__(self, progress: "StageProgress"):
        self._progress = progress

    def text(self) -> "Text":
        """The summary as rich text: stage, elapsed, estimate, percent, time left.

        Separated from ``__rich__`` so the *content* is assertable without a terminal,
        and so the bar can be dropped without touching the numbers.
        """
        progress = self._progress
        message = progress._last or ""
        elapsed = progress.elapsed_live
        expected = progress.expected_total

        text = Text()
        text.append(message, style="bold cyan")
        if expected > 0:
            text.append(f"  {_short(elapsed)} / ~{_short(expected)}")
            text.append(f"  {_percent(elapsed, expected)}%", style="bold")
            # A time-left figure is more useful than a percentage once a stage runs
            # long, so it is shown throughout rather than only near the end.
            remaining = expected - elapsed
            if remaining > 0:
                text.append(f"  ~{_short(remaining)} left", style="dim")
        return text

    def __rich__(self):
        progress = self._progress
        elapsed = progress.elapsed_live
        expected = progress.expected_total
        if not RICH_AVAILABLE:  # pragma: no cover
            return self.text()
        bar = ProgressBar(
            total=max(expected, elapsed, 1),
            completed=elapsed,
            width=28,
            complete_style="cyan",
            finished_style="green",
        )
        return Group(bar, self.text())


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
        self._live = None
        self._last = None
        self._started = None
        self.completed: list[tuple[str, float]] = []

    @property
    def expected_total(self) -> float:
        """Estimated seconds for the whole run, over every phase we have a time for.

        Summed across all known phases, not just the ones seen so far. If the
        denominator grew each time a stage began, the bar and the percentage would jump
        *backwards* mid-run, which reads as the estimate being wrong rather than as the
        run having further to go than the visible stage.
        """
        return sum(self.estimates.values())

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        self.done()
        self._last = message
        self._started = self._clock()

        if not _on_terminal(self.console):
            print(f"... {self._label(message)}")
            return

        console = self.console or Console()
        if self.wants_live_line:
            self._start_live(console)
        else:
            self._status = console.status(f"[bold cyan]{self._label(message)}[/bold cyan]")
            self._status.start()

    @property
    def elapsed_live(self) -> float:
        """Elapsed seconds including the stage currently running.

        ``elapsed_total`` deliberately counts only completed stages, because it is what
        the log reports. A progress line cannot use that: it would sit at 0% for the
        whole of the longest stage, which is exactly when the user is watching it.
        """
        elapsed = self.elapsed_total
        if self._started is not None:
            elapsed += max(0.0, self._clock() - self._started)
        return elapsed

    def _line_text(self) -> str:
        """The live line's summary as plain text, for tests and non-terminal use."""
        return str(_StageLine(self).text())

    @property
    def wants_live_line(self) -> bool:
        """True when a self-refreshing line is both available and meaningful.

        Without an estimate it would be a progress bar counting towards an unknown total,
        which is worse than a plain spinner, so the estimate gates the whole display.
        """
        return bool(LIVE_AVAILABLE and self.expected_total > 0)

    def _start_live(self, console):
        """Start the self-refreshing line.

        Kept as its own method so it can be exercised without a real terminal: `rich.Live`
        calls back into the console (``set_live``), so a console stand-in has to implement
        more of the protocol than a status line does.
        """
        self._live = Live(
            _StageLine(self),
            console=console,
            auto_refresh=True,
            refresh_per_second=8,
            transient=True,
        )
        self._live.start()

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

        # Stop both displays: only one of them is ever running, and a Live left running
        # would keep overwriting the answer as it prints.
        if self._live is not None:
            self._live.stop()
            self._live = None
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
    def elapsed_live(self) -> float:
        return 0.0

    @property
    def expected_total(self) -> float:
        return 0.0

    @property
    def elapsed_total(self) -> float:
        return 0.0

    def report(self) -> str:
        return ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
