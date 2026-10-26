"""Tests for terminal presentation: markdown rendering and stage progress.

Both must degrade to plain text when the output is not a terminal, so a redirected run
or a captured test still contains the model's answer verbatim rather than ANSI escapes.
"""

import pytest

from cli import progress, render


# --- markdown rendering ---

def test_render_prints_the_answer_verbatim_when_not_a_terminal(capsys):
    """A redirected stream must not receive escapes or lose any text."""
    render.render("## Book 1\n**Cantrips:** Light, Mending")
    out = capsys.readouterr().out
    assert "## Book 1" in out
    assert "**Cantrips:**" in out
    assert "\x1b[" not in out


def test_render_never_swallows_the_answer(capsys):
    answer = "## Book 1\nBody text\n\n## Book 2\nMore text"
    render.render(answer)
    out = capsys.readouterr().out
    for line in answer.splitlines():
        assert line in out


def test_banner_is_plain_without_a_terminal(capsys):
    render.banner("Reusing the cached books")
    out = capsys.readouterr().out
    assert "Reusing the cached books" in out
    assert "\x1b[" not in out


def test_warning_is_plain_without_a_terminal(capsys):
    render.warning("Some picks are not legal")
    out = capsys.readouterr().out
    assert "Some picks are not legal" in out
    assert "\x1b[" not in out


def test_strip_ansi_removes_escape_sequences():
    assert render.strip_ansi("\x1b[1mBold\x1b[0m") == "Bold"


class _FakeConsole:
    """Stands in for a live terminal without needing one."""

    def __init__(self, is_terminal=True):
        self.is_terminal = is_terminal
        self.printed = []

    def print(self, value, *args, **kwargs):
        self.printed.append(value)


def test_render_uses_markdown_styling_on_a_terminal():
    console = _FakeConsole()
    render.render("## Book 1\n**Cantrips:** Light", console=console)
    from rich.markdown import Markdown

    assert console.printed, "expected the markdown to be rendered"
    assert isinstance(console.printed[0], Markdown)


def test_render_falls_back_to_text_on_a_dead_terminal(capsys):
    render.render("## Book 1", console=_FakeConsole(is_terminal=False))
    assert "## Book 1" in capsys.readouterr().out


# --- progress stages ---

def test_progress_announces_each_stage(capsys):
    stage = progress.StageProgress()
    stage("Fetching spells from the grimoire")
    stage("Crafting the prompt")
    stage.done()
    out = capsys.readouterr().out
    for expected in ("Fetching spells", "Crafting the prompt"):
        assert expected in out


def test_progress_completes_the_previous_stage_on_the_next_call(capsys):
    """Each call closes the stage before it, so a stage is never left spinning."""
    stage = progress.StageProgress()
    stage("first")
    stage("second")
    out = capsys.readouterr().out
    assert "done: first" in out


def test_progress_done_is_idempotent(capsys):
    stage = progress.StageProgress()
    stage("only")
    stage.done()
    stage.done()
    assert capsys.readouterr().out.count("done: only") == 1


def test_progress_done_without_a_stage_is_safe(capsys):
    progress.StageProgress().done()
    assert capsys.readouterr().out == ""


def test_progress_disabled_says_nothing(capsys):
    stage = progress.StageProgress(enabled=False)
    stage("Fetching spells")
    stage.done()
    assert capsys.readouterr().out == ""


def test_silent_progress_is_a_no_op(capsys):
    silent = progress.SilentProgress()
    silent("anything")
    silent.done()
    assert capsys.readouterr().out == ""


def test_progress_works_as_a_context_manager(capsys):
    """The shell wraps a whole command, so a crash must still close the stage."""
    with progress.StageProgress() as stage:
        stage("Scribing the Books of Shadows")
    out = capsys.readouterr().out
    assert "Scribing the Books of Shadows" in out
    assert "done: Scribing the Books of Shadows" in out
