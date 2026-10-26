"""Render the model's markdown for a terminal.

The answers are markdown and were being printed raw, so the user saw `### Book 1` and
`**Cantrips:**`. This converts the subset the model actually emits into styled terminal
text using `rich`, falling back to the raw text when `rich` is unavailable or output is
redirected to a file.

`render()` is deliberately the only entry point: a future API would serialise the
markdown as-is, so styling must stay on this side of the boundary.
"""

from __future__ import annotations

import re

try:
    from rich.console import Console
    from rich.markdown import Markdown

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - rich is a CLI convenience, not a requirement
    RICH_AVAILABLE = False


# --- progress stages ---

STAGE_FETCH = "Fetching spells from the grimoire"
STAGE_PROMPT = "Crafting the prompt"
STAGE_SCRIBE = "Scribing the Books of Shadows"
STAGE_REFINE = "Refining the current choices"


def render(markdown_text: str, console=None) -> None:
    """Print markdown to the terminal, styled where the terminal supports it.

    Falls back to the plain text so piping output to a file or a test capture still
    yields the model's answer verbatim.
    """
    if not RICH_AVAILABLE:
        print(markdown_text)
        return

    console = console or Console()
    if not console.is_terminal:
        # A redirected stream should not receive ANSI escapes.
        print(markdown_text)
        return
    console.print(Markdown(markdown_text))


def banner(text: str, console=None) -> None:
    """Print a short emphasised line (cache notice, warnings)."""
    if RICH_AVAILABLE and (console or Console()).is_terminal:
        (console or Console()).print(f"[bold cyan]{text}[/bold cyan]")
    else:
        print(text)


def warning(text: str, console=None) -> None:
    """Print a short warning line."""
    if RICH_AVAILABLE and (console or Console()).is_terminal:
        (console or Console()).print(f"[bold yellow]{text}[/bold yellow]")
    else:
        print(text)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences, for tests that compare rendered output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)
