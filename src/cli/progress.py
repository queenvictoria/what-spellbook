"""A Claude-style stage display for long-running steps.

Fetching candidates embeds the scenario, and generating an answer waits on the model -
together tens of seconds. A silent terminal makes that indistinguishable from a hang, so
each stage is announced and then marked done.

`rich` gives a live status line on a terminal; when it is unavailable or output is
redirected, the same stages are printed as plain lines so logs stay readable. The backend
calls a plain ``emit(message)`` callback, so it never imports `rich`.
"""

from __future__ import annotations

try:
    from rich.console import Console

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    RICH_AVAILABLE = False


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
    """

    def __init__(self, *, enabled=True, console=None):
        self.enabled = enabled
        self.console = console
        self._status = None
        self._last = None

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        self.done()
        self._last = message

        if _on_terminal(self.console):
            console = self.console or Console()
            self._status = console.status(f"[bold cyan]{message}...[/bold cyan]")
            self._status.start()
        else:
            print(f"... {message}")

    def done(self, message: str | None = None) -> None:
        """Complete the in-flight stage. Safe to call when nothing is running."""
        if self._last is None:
            return
        finished, self._last = self._last, None

        if self._status is not None:
            self._status.stop()
            self._status = None
        if self.enabled and not _on_terminal(self.console):
            print(f"    done: {message or finished}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.done()
        return False


class SilentProgress:
    """Progress that says nothing, for API callers and tests."""

    enabled = False

    def __call__(self, message: str) -> None:
        return None

    def done(self, message: str | None = None) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
