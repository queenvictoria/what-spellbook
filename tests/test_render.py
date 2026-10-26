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


# --- progress timing ---


def _clock(*values):
    """A clock returning the given values in order, repeating the last."""
    seq = iter(values)
    last = [values[-1]]

    def tick():
        try:
            value = next(seq)
        except StopIteration:
            return last[0]
        last[0] = value
        return value

    return tick


def test_progress_reports_how_long_each_stage_took(capsys):
    stage = progress.StageProgress(clock=_clock(0.0, 2.5, 2.5, 42.0))
    stage("Fetching spells from the grimoire")
    stage("Crafting the prompt")
    stage.done()
    out = capsys.readouterr().out
    assert "done: Fetching spells from the grimoire (2.5s)" in out
    assert "done: Crafting the prompt (39.5s)" in out


def test_progress_formats_minutes(capsys):
    stage = progress.StageProgress(clock=_clock(0.0, 72.0))
    stage("Scribing the Books of Shadows")
    stage.done()
    assert "(1m 12s)" in capsys.readouterr().out


def test_progress_shows_an_estimate_when_history_exists(capsys):
    """A known stage advertises roughly how long it will take."""
    stage = progress.StageProgress(
        estimates={"Scribing the Books of Shadows": 38.0},
        clock=_clock(0.0, 1.0),
    )
    stage("Scribing the Books of Shadows")
    stage.done()
    out = capsys.readouterr().out
    assert "(~38.0s)" in out


def test_progress_invents_no_estimate_without_history(capsys):
    """With no stored runs there is nothing to base an estimate on."""
    stage = progress.StageProgress(clock=_clock(0.0, 1.0))
    stage("Crafting the prompt")
    stage.done()
    assert "~" not in capsys.readouterr().out


def test_progress_estimates_only_apply_to_known_stages(capsys):
    stage = progress.StageProgress(
        estimates={"Scribing the Books of Shadows": 38.0},
        clock=_clock(0.0, 1.0, 1.0, 2.0),
    )
    stage("Scribing the Books of Shadows")
    stage("Crafting the prompt")
    stage.done()
    out = capsys.readouterr().out
    assert out.count("(~") == 1


def test_progress_total_never_goes_backwards():
    """The total is the sum of completed stages, so an open stage must not count yet."""
    stage = progress.StageProgress(clock=_clock(0.0, 3.0))
    stage("fetching")
    assert stage.elapsed_total == 0.0
    stage.done()
    assert stage.elapsed_total == 3.0


def test_progress_report_names_every_stage():
    stage = progress.StageProgress(clock=_clock(0.0, 2.0, 2.0, 5.0, 5.0))
    stage("fetching")
    stage("crafting")
    stage.done()
    report = stage.report()
    assert "fetching: 2.0s" in report
    assert "crafting: 3.0s" in report
    assert "total 5.0s" in report


def test_progress_report_is_empty_before_anything_runs():
    assert progress.StageProgress().report() == ""


def test_progress_total_is_zero_when_disabled(capsys):
    stage = progress.StageProgress(enabled=False, clock=_clock(0.0, 5.0))
    stage("fetching")
    stage.done()
    assert stage.elapsed_total == 0.0
    assert capsys.readouterr().out == ""


def test_silent_progress_reports_nothing():
    """API callers must get no timing output they have to ignore."""
    assert progress.SilentProgress().report() == ""
    assert progress.SilentProgress().elapsed_total == 0.0


def test_short_duration_formatting():
    assert progress._short(0.0) == "0.0s"
    assert progress._short(4.25) == "4.2s"
    assert progress._short(59.9) == "59.9s"
    assert progress._short(60) == "1m 00s"
    assert progress._short(125) == "2m 05s"
