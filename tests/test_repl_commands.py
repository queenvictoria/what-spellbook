"""Tests for the /slash + TAB REPL command layer.

Covers the three interlocking pieces that make `/scenario` work in cmd.Cmd:
parseline stripping the slash, completenames offering '/command', and the
readline delimiter that keeps '/' inside the completion token.
"""

import readline

import pytest

import main

COMMANDS = main.SpellbookShell.COMMANDS


# --- parseline: '/command' must parse as a command, not fall through to default ---

@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("/scenario ruin", ("scenario", "ruin")),
        ("/ask what about hex", ("ask", "what about hex")),
        ("/exit", ("exit", "")),
        ("/scenario", ("scenario", "")),
        ("   /scenario padded", ("scenario", "padded")),
        ("/scenario   extra   space", ("scenario", "extra   space")),
    ],
)
def test_parseline_accepts_slash_prefix(shell, line, expected):
    assert shell.parseline(line)[:2] == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("scenario ruin", ("scenario", "ruin")),
        ("ask why", ("ask", "why")),
        ("exit", ("exit", "")),
    ],
)
def test_parseline_still_accepts_bare_commands(shell, line, expected):
    """The slash form is an addition, not a replacement."""
    assert shell.parseline(line)[:2] == expected


def test_parseline_bare_slash_is_not_a_command(shell):
    """A lone '/' must not raise and must not dispatch to do_.<something>."""
    cmd_name, arg, _ = shell.parseline("/")
    assert not cmd_name
    assert not arg


@pytest.mark.parametrize("line", ["/", "?", "/  ", ""])
def test_parseline_odd_input_is_safe(shell, line):
    """Malformed input returns a tuple rather than raising."""
    assert isinstance(shell.parseline(line), tuple)


# --- completion ---


def _complete(shell, text):
    """Drive cmd's real completion path, as cmdloop's readline hook does."""
    matches, state = [], 0
    while True:
        match = shell.complete(text, state)
        if match is None:
            return matches
        matches.append(match)
        state += 1


def test_slash_s_completes_to_scenario(shell):
    """The headline behaviour: '/s' + TAB offers '/scenario'."""
    assert _complete(shell, "/s") == ["/scenario "]


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("/s", ["/scenario "]),
        ("/a", ["/ask "]),
        ("/e", ["/exit "]),
        ("/", ["/scenario ", "/ask ", "/exit "]),
    ],
)
def test_slash_prefix_completions(shell, prefix, expected):
    assert _complete(shell, prefix) == expected


@pytest.mark.parametrize("prefix", ["/x", "/zzz"])
def test_unknown_slash_prefix_has_no_matches(shell, prefix):
    assert _complete(shell, prefix) == []


def test_bare_prefix_still_uses_cmd_completion(shell):
    """Without a slash, cmd's own bare-name completion is preserved."""
    assert _complete(shell, "sc") == ["scenario"]


def test_every_command_is_completable(shell):
    """Each advertised command must actually be reachable by TAB."""
    for name in COMMANDS:
        assert f"/{name} " in _complete(shell, "/")


def test_completion_matches_dispatch_after_space_stripped(shell):
    """Whatever completion inserts must round-trip through parseline."""
    for match in _complete(shell, "/"):
        cmd_name, _, _ = shell.parseline(match)
        assert cmd_name in COMMANDS


# --- readline configuration ---


def test_slash_is_not_a_word_delimiter(shell):
    """'/' must be word text, else TAB on '/s' reports 's' and skips completenames."""
    assert "/" not in readline.get_completer_delims()


def test_other_delimiters_are_preserved(shell):
    """Removing '/' must not strip the space delimiter that separates arguments."""
    assert " " in readline.get_completer_delims()


def test_completenames_handles_empty_text(shell):
    """Before a slash is typed, cmd's bare-name completion still offers our commands.

    cmd also contributes its own built-ins (help, EOF), so assert a superset.
    """
    names = shell.completenames("")
    assert set(COMMANDS).issubset(set(names))


def test_empty_text_does_not_offer_slash_forms(shell):
    """Slash completions appear only once the user types '/', per the Claude-style UX."""
    assert not any(name.startswith("/") for name in shell.completenames(""))


# --- dispatch through the real command path ---


def test_slash_scenario_dispatches_and_sets_scenario(shell):
    shell.onecmd("/scenario a duel on a narrow bridge")
    assert shell.current_scenario == "a duel on a narrow bridge"


def test_slash_ask_reaches_the_llm_with_context(shell, fake_llm):
    shell.onecmd("/scenario ambush at dusk")
    fake_llm.prompts.clear()
    shell.onecmd("/ask can I swap Fireball?")
    assert len(fake_llm.prompts) == 1
    assert "ambush at dusk" in fake_llm.prompts[0]


def test_slash_exit_returns_true(shell):
    assert shell.onecmd("/exit") is True


def test_bare_slash_does_not_raise(shell):
    shell.onecmd("/")


def test_unknown_slash_command_is_reported(shell, caplog):
    with caplog.at_level("ERROR"):
        shell.onecmd("/bogus")
    assert "bogus" in caplog.text
    assert "/scenario" in caplog.text
