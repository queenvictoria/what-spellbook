"""Tests for terminal presentation: markdown rendering and stage progress.

Both must degrade to plain text when the output is not a terminal, so a redirected run
or a captured test still contains the model's answer verbatim rather than ANSI escapes.
"""

import io

import pytest
from rich.console import Console

from backend.cli import progress, render


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
        self._live_renderable = None

    def print(self, value, *args, **kwargs):
        self.printed.append(value)

    # `rich.Live` calls back into the console, so a stand-in has to offer these too or
    # starting a Live against it raises rather than being testable.
    def set_live(self, live):
        self._live_renderable = getattr(live, "renderable", None)
        return True

    def clear_live(self, live):
        self._live_renderable = None

    # rich's Live drives the cursor directly, so a stand-in needs these as well.
    def show_cursor(self, show=True):
        return None

    def hide_cursor(self):
        return None

    def status(self, message, *args, **kwargs):
        return _FakeStatus(message)


class _FakeStatus:
    def __init__(self, message):
        self.message = message
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False





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


# --- percentage and ETA ---


@pytest.mark.parametrize(
    ("elapsed", "expected", "want"),
    [
        (0.0, 100.0, 0),
        (25.0, 100.0, 25),
        (50.0, 100.0, 50),
        (99.9, 100.0, 99),
    ],
)
def test_percent_is_the_fraction_of_the_estimate(elapsed, expected, want):
    assert progress._percent(elapsed, expected) == want


def test_percent_never_reports_a_finished_stage_as_complete():
    """100% while still running reads as 'finished' and makes the next pause look hung."""
    assert progress._percent(150.0, 100.0) == 99
    assert progress._percent(100.0, 100.0) == 99


def test_percent_is_zero_without_an_estimate():
    """No estimate means no basis for a percentage, so none is claimed."""
    assert progress._percent(10.0, 0.0) == 0


def test_expected_total_is_the_whole_run_from_the_start():
    """A fixed denominator, so the bar cannot jump backwards when a stage begins."""
    stage = progress.StageProgress(
        estimates={"fetching": 2.0, "crafting": 1.0, "scribing": 40.0},
        clock=_clock(0.0, 2.0, 2.0, 3.0),
    )
    assert stage.expected_total == 43.0
    stage("fetching")
    assert stage.expected_total == 43.0
    stage("crafting")
    assert stage.expected_total == 43.0


def test_expected_total_ignores_stages_with_no_estimate():
    stage = progress.StageProgress(estimates={"fetching": 2.0}, clock=_clock(0.0, 2.0))
    stage("unknown stage")
    # Only the stage with a known time contributes.
    assert stage.expected_total == 2.0


def test_expected_total_is_zero_when_nothing_ran():
    assert progress.StageProgress().expected_total == 0.0
    assert progress.SilentProgress().expected_total == 0.0


# --- the live line ---


def test_live_line_shows_elapsed_estimate_and_percent():
    """The three things the user asked for: elapsed, estimate, percentage."""
    ticks = [0.0]

    def clock():
        return ticks[0]

    stage = progress.StageProgress(estimates={"fetching": 10.0}, clock=clock)
    stage("fetching")
    ticks[0] = 4.0
    rendered = stage._line_text()

    assert "fetching" in rendered
    assert "4.0s" in rendered
    assert "10.0s" in rendered
    assert "40%" in rendered
    assert "6.0s left" in rendered


def test_live_line_carries_the_total_across_stages():
    """The bar tracks the whole run, so it does not restart at zero each stage."""
    ticks = [0.0]

    def clock():
        return ticks[0]

    stage = progress.StageProgress(
        estimates={"fetching": 2.0, "crafting": 38.0}, clock=clock
    )
    stage("fetching")
    ticks[0] = 2.0
    stage("crafting")
    ticks[0] = 22.0
    rendered = stage._line_text()

    # 2s done + 20s into a 40s total.
    assert "22.0s" in rendered
    assert "40.0s" in rendered
    assert "55%" in rendered


def test_live_line_omits_the_clock_without_an_estimate():
    stage = progress.StageProgress(clock=_clock(0.0, 5.0))
    stage("unknown stage")
    rendered = stage._line_text()
    assert "unknown stage" in rendered
    assert "%" not in rendered
    assert "left" not in rendered


def test_live_line_shows_no_negative_time_left():
    """Overshooting the estimate must not print '~-3s left'."""
    ticks = [0.0]

    def clock():
        return ticks[0]

    stage = progress.StageProgress(estimates={"fetching": 10.0}, clock=clock)
    stage("fetching")
    ticks[0] = 25.0
    rendered = stage._line_text()
    assert "left" not in rendered
    assert "99%" in rendered


def _terminal_console():
    """A real console that believes it is a terminal, writing to a buffer.

    Faking rich's console protocol is not worth it - `Live` calls `set_live`,
    `push_render_hook`, `show_cursor` and more - so the branch is exercised with the real
    thing, and only the read-only checks use the lightweight stand-in.
    """
    return Console(file=io.StringIO(), force_terminal=True, width=90)


def test_live_line_is_offered_once_an_estimate_exists():
    stage = progress.StageProgress(
        estimates={"fetching": 10.0}, console=_terminal_console(), clock=_clock(0.0, 1.0)
    )
    stage("fetching")
    assert stage.wants_live_line is True
    # The status line is not started, so the two displays cannot overlap.
    assert stage._status is None
    stage.done()


def test_no_live_line_without_an_estimate():
    """A bar counting towards an unknown total is worse than a plain spinner."""
    stage = progress.StageProgress(console=_FakeConsole(), clock=_clock(0.0, 1.0))
    stage("fetching")
    assert stage.wants_live_line is False
    assert stage._status is not None
    stage.done()


def test_done_clears_both_displays():
    """A display left running would keep overwriting the answer as it prints."""
    stage = progress.StageProgress(
        estimates={"fetching": 10.0}, console=_terminal_console(), clock=_clock(0.0, 1.0)
    )
    stage("fetching")
    assert stage._live is not None
    stage.done()
    assert stage._live is None
    assert stage._status is None


def test_the_live_line_shows_a_real_progress_bar():
    """A rendered terminal run must contain a bar, not just the numbers."""
    console = _terminal_console()
    stage = progress.StageProgress(
        estimates={"fetching": 10.0}, console=console, clock=_clock(0.0, 4.0)
    )
    stage("fetching")
    console.print(progress._StageLine(stage).__rich__())
    stage.done()

    out = console.file.getvalue()
    assert "fetching" in out
    assert "40%" in out
    assert "━" in out  # the bar itself


def test_progress_line_advances_during_the_longest_stage():
    """The bug this guards: elapsed must include the running stage, not just finished ones.

    `elapsed_total` counts completed stages only, so a live line built on it would sit at
    0% for the whole of the slowest stage - precisely when it is being watched.
    """
    ticks = [0.0]

    def clock():
        return ticks[0]

    stage = progress.StageProgress(estimates={"scribing": 40.0}, clock=clock)
    stage("scribing")
    assert "0%" in stage._line_text()

    ticks[0] = 30.0
    assert "75%" in stage._line_text()

    # The log figure is unchanged: it still reports only completed work.
    assert stage.elapsed_total == 0.0
    assert stage.elapsed_live == 30.0


def test_redirected_output_never_gets_a_live_line(capsys):
    """Redirected output must stay line-based, so no ANSI and no Live."""
    stage = progress.StageProgress(
        estimates={"fetching": 10.0},
        console=_FakeConsole(is_terminal=False),
        clock=_clock(0.0, 1.0),
    )
    stage("fetching")
    stage.done()
    assert stage._live is None
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "done: fetching (1.0s)" in out
