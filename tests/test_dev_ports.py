"""Tests for the dev-server port settings.

Both the API and the Vite dev server are separate processes on separate ports, and more
than one copy of each may be running on the same machine. Neither port is hard-coded, and
the API's CORS allow-list is derived from the front end's port rather than fixed - a fixed
list silently blocks the second dev server, which is a failure that only shows up in the
browser console.
"""

import pytest

from backend.libs import config


# --- port selection ---

@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, config.API_PORT),
        ({"API_PORT": "8100"}, 8100),
        # .env entries are often quoted, and a blank value means unset.
        ({"API_PORT": '"8100"'}, 8100),
        ({"API_PORT": "  8100  "}, 8100),
        ({"API_PORT": ""}, config.API_PORT),
        # A typo in an untracked file must not stop the server from starting.
        ({"API_PORT": "eight thousand"}, config.API_PORT),
        ({"API_PORT": "0"}, config.API_PORT),
        ({"API_PORT": "70000"}, config.API_PORT),
        ({"API_PORT": "-1"}, config.API_PORT),
    ],
)
def test_select_port_falls_back_rather_than_failing(env, expected):
    assert config.select_port("API_PORT", config.API_PORT, env) == expected


def test_select_port_reads_the_named_variable():
    """The two ports are independent, so one setting must not answer for the other."""
    env = {"API_PORT": "8100", "FRONTEND_PORT": "5273"}
    assert config.select_port("API_PORT", config.API_PORT, env) == 8100
    assert config.select_port("FRONTEND_PORT", config.FRONTEND_PORT, env) == 5273


# --- CORS origins ---

def test_dev_origins_follow_the_frontend_port():
    """The allow-list must move with the dev server, or the second one is blocked.

    A browser treats `localhost` and `127.0.0.1` as distinct origins, so both spellings of
    the configured port are allowed.
    """
    origins = config.dev_origins({"FRONTEND_PORT": "5273"})
    assert "http://localhost:5273" in origins
    assert "http://127.0.0.1:5273" in origins
    assert "http://localhost:5173" not in origins


def test_dev_origins_default_to_the_documented_port():
    origins = config.dev_origins({})
    assert f"http://localhost:{config.FRONTEND_PORT}" in origins


def test_dev_origins_accept_extras():
    """A LAN address or a preview build is not derivable from the port, so it is listed."""
    origins = config.dev_origins(
        {"FRONTEND_PORT": "5273", "CORS_ORIGINS": "http://192.168.1.5:4173, http://example.test"}
    )
    assert "http://192.168.1.5:4173" in origins
    assert "http://example.test" in origins
    # The derived origins are always included, not replaced.
    assert "http://localhost:5273" in origins


def test_dev_origins_ignore_blanks_and_duplicates():
    origins = config.dev_origins(
        {"FRONTEND_PORT": "5273", "CORS_ORIGINS": " , http://localhost:5273/ , "}
    )
    assert origins.count("http://localhost:5273") == 1
    assert "" not in origins


def test_the_api_uses_the_derived_origins(monkeypatch):
    """The wiring, not just the helper: a hard-coded list would pass the tests above."""
    from backend.api import main

    monkeypatch.setenv("FRONTEND_PORT", "5273")
    app = main.create_app(vector_db=None, backend=None, character_name=None)

    cors = [m for m in app.user_middleware if "CORS" in str(m.cls)]
    assert cors, "no CORS middleware is installed"
    assert cors[0].kwargs["allow_origins"] == config.dev_origins()
    assert "http://localhost:5273" in cors[0].kwargs["allow_origins"]
