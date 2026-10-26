"""Configured paths must not depend on the directory the CLI was launched from.

Regression tests for a real bug: the cache and the rules context were bare relative
paths resolved against the process CWD, so launching the CLI from anywhere other than
the repo root silently wrote a cache somewhere else (and loaded no rules at all).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend import config, prompts

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "name",
    [
        "DOCS_DIR_PATH",
        "DB_DIR_PATH",
        "CACHE_DIR_PATH",
        "CONTEXT_DIR_PATH",
        "CHARACTERS_DIR_PATH",
    ],
)
def test_every_configured_path_is_absolute_and_under_root(name):
    path = getattr(config, name)
    assert path.is_absolute(), f"{name} must be absolute"
    assert config.ROOT in path.parents or path == config.ROOT


def test_resolve_leaves_absolute_paths_alone(tmp_path):
    assert config.resolve(tmp_path) == tmp_path


def test_repo_context_directory_is_found_from_any_cwd(tmp_path, monkeypatch):
    """The rules context must load even when CWD is unrelated to the repo."""
    monkeypatch.chdir(tmp_path)
    context = prompts.load_rule_context({"Class": "Warlock", "Subclass": "Celestial Patron"})
    assert "Pact of the Tome" in context


def test_context_dir_default_is_the_resolved_constant():
    """A bare default would reintroduce the CWD dependency."""
    assert prompts.load_rule_context.__defaults__ == (None,), (
        "load_rule_context should default to config.CONTEXT_DIR_PATH, not a bare string"
    )


def test_cache_dir_ignores_cwd(tmp_path, monkeypatch):
    """The reported symptom: books written into whatever directory we happened to be in."""
    from backend import service

    monkeypatch.chdir(tmp_path)
    svc = service.SpellbookService(object(), {"Class": "Warlock"}, backend=object())
    assert svc.cache_dir == config.CACHE_DIR_PATH
    assert config.ROOT in svc.cache_dir.parents


def test_cli_reports_the_same_cache_dir_from_another_working_directory(tmp_path):
    """End-to-end guard: a subprocess launched elsewhere must resolve the repo cache."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend import config; print(config.CACHE_DIR_PATH)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(config.CACHE_DIR_PATH)
    assert not (tmp_path / ".cache").exists()
