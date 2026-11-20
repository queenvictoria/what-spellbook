"""The settings store, its precedence, and the endpoints the settings page uses.

The store is the interesting part: it is the only place a *user* writes configuration, it can
hold an API key, and it is layered under ``.env`` and the launch environment. So the tests here
are about the three things that would be invisible if they broke - what wins over what, that a
secret never comes back out, and that a partial save leaves the rest alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.libs import config, settings

from conftest import FakeDB, FakeLLM

LOIS = {"Name": "Lois", "Class": "Warlock", "Current Level": 5}


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Redirect the settings file into a temp directory, so the real one is never touched.

    Patched on ``config`` because that is the module ``settings.path`` reads - patching a
    copy would let a test pass while writing the user's real settings.
    """
    target = tmp_path / ".settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE_PATH", target)
    return target


@pytest.fixture
def clean_model_env(settings_file, monkeypatch):
    """A process environment with none of the four editable names set.

    The selectors read the overlay only when they are given no ``env``, so a test that passed
    a dict would be testing the *caller's* mapping and not the precedence at all - which is
    how two of these tests first passed for the wrong reason. Clearing the real values and
    the launch snapshot makes ``select_model()`` observe the settings file and nothing else.
    """
    monkeypatch.setattr(config, "_LAUNCH_ENV", {})
    for name in settings.BY_ENV:
        monkeypatch.delenv(name, raising=False)
    return settings_file


@pytest.fixture
def api(tmp_path, monkeypatch, settings_file):
    """A client wired to fakes, with the character sheet overridden."""
    app = create_app(vector_db=FakeDB(), backend=FakeLLM(), character_name="lois",
                     cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data", lambda name, **kw: dict(LOIS))
    return TestClient(app)


# --- the store ---


def test_saving_and_loading_round_trips(settings_file):
    settings.update({"reasoning_model": "qwen3.5:4b"})
    assert settings.load() == {"LLM_MODEL": "qwen3.5:4b"}
    assert json.loads(settings_file.read_text()) == {"LLM_MODEL": "qwen3.5:4b"}


def test_the_file_stores_environment_names(settings_file):
    """The file stays hand-editable with the same vocabulary .env and the README use."""
    settings.update({"reasoning_model": "x/y", "api_key": "k"})
    written = json.loads(settings_file.read_text())
    assert written["LLM_MODEL"] == "x/y"
    assert written["OPENROUTER_API_KEY"] == "k"


def test_a_missing_file_is_empty_and_not_an_error(settings_file):
    assert not settings_file.exists()
    assert settings.load() == {}


def test_an_unreadable_file_falls_back_rather_than_raising(settings_file):
    """A hand-edited typo must not stop the app from starting.

    This is the file's whole reason to exist - so the values need not be edited by hand - so
    a mistake in it has to be survivable rather than fatal.
    """
    settings_file.write_text("{ this is not json")
    assert settings.load() == {}


def test_unknown_keys_in_the_file_are_ignored(settings_file):
    settings_file.write_text(json.dumps({"LLM_MODEL": "a/b", "SECRET_HANDLE": "x"}))
    assert settings.load() == {"LLM_MODEL": "a/b"}


def test_blank_values_are_not_stored(settings_file):
    settings.update({"reasoning_model": "   "})
    assert settings.load() == {}
    assert json.loads(settings_file.read_text()) == {}


def test_quotes_are_stripped(settings_file):
    """These are the same values .env holds, where a hand-edit often quotes a name."""
    settings.update({"reasoning_model": '"qwen3.5:4b"'})
    assert settings.load() == {"LLM_MODEL": "qwen3.5:4b"}


def test_clearing_one_setting_leaves_the_others(settings_file):
    """Clearing is per-field, because a form that forgot one box must not wipe it."""
    settings.update({"reasoning_model": "a/b", "api_key": "k"})
    settings.update({"reasoning_model": ""})
    assert settings.load() == {"OPENROUTER_API_KEY": "k"}


def test_an_absent_field_is_unchanged_not_cleared(settings_file):
    """The distinction the request model's `None` exists for: absent is not empty."""
    settings.update({"reasoning_model": "a/b", "fast_model": "c/d"})
    settings.update({"fast_model": "e/f"})
    assert settings.load() == {"LLM_MODEL": "a/b", "LLM_MODEL_FAST": "e/f"}


@pytest.mark.parametrize("value", ["has a space", "two  words"])
def test_a_model_name_with_a_space_is_rejected(settings_file, value):
    """A model id is one token, and the failure at call time would not name this field."""
    with pytest.raises(settings.SettingsError):
        settings.update({"reasoning_model": value})


def test_a_line_break_is_rejected(settings_file):
    with pytest.raises(settings.SettingsError):
        settings.update({"api_key": "sk-abc\ndef"})


def test_an_overlong_value_is_rejected(settings_file):
    with pytest.raises(settings.SettingsError):
        settings.update({"reasoning_model": "a" * (settings.MAX_MODEL + 1)})


def test_a_rejected_save_does_not_half_apply(settings_file):
    """A save that fails must leave the file exactly as it was."""
    settings.update({"reasoning_model": "a/b", "fast_model": "c/d"})
    with pytest.raises(settings.SettingsError):
        # `api_key` is fine, `reasoning_model` is not - and neither may land.
        settings.update({"reasoning_model": "bad name", "api_key": "k"})
    assert settings.load() == {"LLM_MODEL": "a/b", "LLM_MODEL_FAST": "c/d"}


def test_an_unknown_setting_name_is_rejected(settings_file):
    with pytest.raises(settings.SettingsError):
        settings.update({"nope": "x"})


def test_a_non_string_value_is_rejected(settings_file):
    with pytest.raises(settings.SettingsError):
        settings.update({"reasoning_model": 42})


def test_clear_removes_the_file(settings_file):
    settings.update({"reasoning_model": "a/b"})
    settings.clear()
    assert not settings_file.exists()
    # Idempotent: clearing an absent file is not an error.
    settings.clear()


def test_the_file_is_not_world_readable(settings_file):
    """It can hold an API key, so it must not be readable by every user on the machine."""
    settings.update({"api_key": "sk-or-v1-secret"})
    mode = settings_file.stat().st_mode & 0o777
    assert mode & 0o077 == 0, f"expected a private file, got {oct(mode)}"


# --- masking ---


def test_a_long_secret_is_masked_to_its_ends():
    """Enough to tell which key is loaded, not enough to use."""
    masked = settings.mask("sk-or-v1-abcdefghijklmnop")
    assert masked == "sk-o…mnop"
    assert "abcdefghij" not in masked


def test_a_short_secret_is_masked_whole():
    """Showing four characters of eight is most of it."""
    assert set(settings.mask("sk-abcde")) == {"•"}


@pytest.mark.parametrize("value", [None, ""])
def test_an_absent_secret_masks_to_none(value):
    assert settings.mask(value) is None


# --- precedence ---


def test_a_saved_setting_overrides_env(settings_file, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from/env")
    settings.update({"reasoning_model": "from/file"})
    assert config.env_view({})["LLM_MODEL"] == "from/file"


def test_a_launched_variable_beats_a_saved_setting(settings_file):
    """A one-off on the command line is a statement about this run, so it must win.

    The regression this guards: a saved file that silently defeats
    `LLM_MODEL=qwen3.5:4b python -m backend` makes the documented override a lie.
    """
    settings.update({"reasoning_model": "from/file"})
    merged = config.env_view({"LLM_MODEL": "from/launch"})
    assert merged["LLM_MODEL"] == "from/launch"


def test_a_launched_variable_beats_env(settings_file, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from/env")
    assert config.env_view({"LLM_MODEL": "from/launch"})["LLM_MODEL"] == "from/launch"


def test_env_applies_when_nothing_is_saved_or_launched(settings_file, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "from/env")
    assert config.env_view({})["LLM_MODEL"] == "from/env"


def test_a_launched_variable_that_is_absent_does_not_clear_a_saved_one(settings_file):
    """Only variables actually *set* at launch win; an empty base must not wipe the file."""
    settings.update({"reasoning_model": "from/file"})
    assert config.env_view({"SOMETHING_ELSE": "x"})["LLM_MODEL"] == "from/file"


def test_the_saved_setting_decides_the_model_and_backend(clean_model_env):
    """The end-to-end point of the overlay: a saved name changes what is selected.

    ``select_model()`` is called *with no argument*, so it reads ``config.env_view()`` - which
    is the whole path a real run takes. Passing a mapping here would exercise the caller's
    dict instead and prove nothing about the settings file.
    """
    settings.update({"reasoning_model": "qwen3.5:4b"})
    assert config.select_model() == ("ollama", "qwen3.5:4b")


def test_a_saved_model_with_a_slash_selects_openrouter_when_a_key_is_present(clean_model_env):
    settings.update({"reasoning_model": "vendor/model", "api_key": "k"})
    assert config.select_model() == ("openrouter", "vendor/model")


def test_the_saved_fast_model_is_used(clean_model_env):
    settings.update({"fast_model": "qwen2.5-coder:1.5b-base"})
    assert config.select_fast_model() == ("ollama", "qwen2.5-coder:1.5b-base")


def test_a_saved_remote_model_without_a_key_falls_back_to_ollama(clean_model_env):
    """The cleared/unset case: a name with a slash is meaningless with no key, and the
    fallback must be the local default rather than the unreachable remote id."""
    settings.update({"reasoning_model": "vendor/model"})
    backend, model = config.select_model()
    assert backend == "ollama"
    assert model == config.OLLAMA_MODEL


@pytest.mark.parametrize(
    ("name", "launch", "saved", "env_value", "expected"),
    [
        ("LLM_MODEL", {"LLM_MODEL": "a"}, "b", "c", "launch"),
        ("LLM_MODEL", {}, "b", "c", "saved"),
        ("LLM_MODEL", {}, None, "c", "env"),
        ("LLM_MODEL", {}, None, None, "default"),
    ],
)
def test_setting_source_names_the_winning_layer(
    settings_file, monkeypatch, name, launch, saved, env_value, expected
):
    """The page cannot show a winner it cannot name, and the merge is invisible without it."""
    if env_value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, env_value)
    if saved is not None:
        settings.update({"reasoning_model": saved})
    assert config.setting_source(name, launch) == expected


# --- the endpoints ---


def test_get_settings_lists_every_editable_field(api):
    body = api.get("/api/settings").json()
    assert [field["key"] for field in body["fields"]] == [
        "reasoning_model", "fast_model", "api_key", "ollama_model",
    ]
    assert body["settings_file"].endswith(".settings.json")


def test_get_settings_reports_the_effective_model(api, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "vendor/model")
    body = api.get("/api/settings").json()
    assert body["reasoning_model"] == "vendor/model"
    assert body["reasoning_backend"] == "openrouter"


def test_get_settings_never_returns_the_api_key(api, monkeypatch):
    """The credential the *server* uses must not be readable through this endpoint."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-verysecretvalue")
    body = api.get("/api/settings").json()
    key = next(field for field in body["fields"] if field["key"] == "api_key")
    assert key["secret"] is True
    assert "verysecretvalue" not in json.dumps(body)
    assert key["value"] == settings.mask("sk-or-v1-verysecretvalue")


def test_put_settings_saves_a_model(api):
    body = api.put("/api/settings", json={"reasoning_model": "qwen3.5:4b"}).json()
    assert body["reasoning_model"] == "qwen3.5:4b"
    assert body["reasoning_backend"] == "ollama"
    assert api.get("/api/settings").json()["reasoning_model"] == "qwen3.5:4b"


def test_a_saved_model_is_rebuilt_for_the_next_request(tmp_path, monkeypatch, settings_file):
    """The bug this guards is the page appearing to work while nothing changed.

    No ``backend`` is injected, so ``service_for`` builds a real client from the settings -
    and the cached service must be dropped or the old client keeps answering.
    """
    app = create_app(vector_db=FakeDB(), character_name="lois",
                     cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data", lambda name, **kw: dict(LOIS))
    client = TestClient(app)

    first = client.get("/api/health").json()["model"]
    client.put("/api/settings", json={"reasoning_model": "qwen2.5-coder:7b-instruct"})
    assert client.get("/api/health").json()["model"] == "qwen2.5-coder:7b-instruct"
    assert first != "qwen2.5-coder:7b-instruct", "the fixture must start somewhere else"


def test_put_settings_only_writes_what_was_sent(api, settings_file):
    api.put("/api/settings", json={"reasoning_model": "a/b", "api_key": "k"})
    api.put("/api/settings", json={"fast_model": "c/d"})
    assert settings.load() == {
        "LLM_MODEL": "a/b", "OPENROUTER_API_KEY": "k", "LLM_MODEL_FAST": "c/d",
    }


def test_put_settings_clears_a_field_sent_empty(api, settings_file):
    """Cleared means the *stored* value is gone; the field then reports the .env default.

    Not ``null``: with the file cleared, ``.env`` supplies the model again, and the page has
    to show what is actually in use rather than an empty box that lies about the next run.
    """
    api.put("/api/settings", json={"reasoning_model": "a/b"})
    assert settings.load() == {"LLM_MODEL": "a/b"}

    body = api.put("/api/settings", json={"reasoning_model": ""}).json()
    assert settings.load() == {}
    field = next(f for f in body["fields"] if f["key"] == "reasoning_model")
    assert field["source"] != "saved"


def test_put_settings_reports_a_bad_value_as_400(api):
    """4xx, not 5xx: the request cannot work however often it is retried."""
    response = api.put("/api/settings", json={"reasoning_model": "not a model name"})
    assert response.status_code == 400
    assert "space" in response.json()["detail"]


def test_put_settings_rejects_an_unknown_field(api):
    """A misspelled field must not be a 200 that changed nothing."""
    response = api.put("/api/settings", json={"reasoning_modle": "a/b"})
    assert response.status_code == 422


def test_an_empty_put_changes_nothing(api, settings_file):
    settings.update({"reasoning_model": "a/b"})
    assert api.put("/api/settings", json={}).status_code == 200
    assert settings.load() == {"LLM_MODEL": "a/b"}


def test_openapi_lists_the_settings_routes(api):
    paths = api.get("/openapi.json").json()["paths"]
    assert "/api/settings" in paths
    assert set(paths["/api/settings"]) >= {"get", "put"}


def test_a_wrong_api_base_does_not_hide_the_way_to_fix_it():
    """The address card must render when the settings request fails.

    A wrong API address is the commonest reason ``GET /api/settings`` fails, and the card that
    repairs it is on this very page - so a screen whose failure path returned only the error
    would be unreachable precisely when it is needed. Checked at the source level because the
    symptom is a blank screen rather than a wrong value, and nothing at runtime here can see
    the difference.
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "app" / "screens" / "SettingsScreen.tsx"
    ).read_text(encoding="utf-8")
    assert "<ApiBaseCard />" in source
    # The card must be drawn inside the loading/error branch, not only in the happy path.
    branch = source.index("if (!settings) {")
    card = source.index("<ApiBaseCard />")
    assert card > branch, "the address card must render when the settings fetch fails"
