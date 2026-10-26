"""Tests for character selection precedence and CLI argument parsing."""

import os

import pytest

from backend.libs import cache  # noqa: F401
from backend.cli import app as cli_app
from backend.libs import config


def _resolve(monkeypatch, flag=None):
    """Mirror the resolution main() performs: flag, then env, then default."""
    args = cli_app.parse_args(["--character", flag] if flag else [])
    return args.character or os.getenv("CHARACTER", config.DEFAULT_CHARACTER)


# --- --character flag / CHARACTER env var precedence ---


def test_flag_beats_env(monkeypatch):
    monkeypatch.setenv("CHARACTER", "envchar")
    assert cli_app.parse_args(["--character", "flagchar"]).character == "flagchar"
    assert _resolve(monkeypatch, "flagchar") == "flagchar"


def test_env_used_when_no_flag(monkeypatch):
    monkeypatch.setenv("CHARACTER", "envchar")
    assert _resolve(monkeypatch, None) == "envchar"


def test_default_when_neither_flag_nor_env(monkeypatch):
    monkeypatch.delenv("CHARACTER", raising=False)
    assert _resolve(monkeypatch, None) == config.DEFAULT_CHARACTER


def test_default_character_is_lois():
    assert config.DEFAULT_CHARACTER == "lois"


def test_no_flag_yields_none(monkeypatch):
    monkeypatch.delenv("CHARACTER", raising=False)
    assert cli_app.parse_args([]).character is None


def test_flag_accepts_path_form():
    assert cli_app.parse_args(["--character", "data/characters/lois.yaml"]).character == (
        "data/characters/lois.yaml"
    )


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_app.parse_args(["--help"])
    assert exc.value.code == 0
    assert "--character" in capsys.readouterr().out


def test_unknown_flag_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        cli_app.parse_args(["--nonsense"])
    assert exc.value.code != 0


def test_character_flag_requires_a_value():
    with pytest.raises(SystemExit):
        cli_app.parse_args(["--character"])


@pytest.mark.parametrize(
    ("flag", "env", "expected"),
    [
        ("flagchar", "envchar", "flagchar"),
        (None, "envchar", "envchar"),
        (None, None, "lois"),
        ("flagchar", None, "flagchar"),
    ],
)
def test_resolution_precedence(monkeypatch, flag, env, expected):
    if env is None:
        monkeypatch.delenv("CHARACTER", raising=False)
    else:
        monkeypatch.setenv("CHARACTER", env)
    assert _resolve(monkeypatch, flag) == expected
