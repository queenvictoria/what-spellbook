"""The model settings a browser sends, and the rule that decides which of them apply.

The browser is the store of record for these now, so the server's job is narrow and worth
pinning precisely: accept what it is sent, hold it **in memory only**, let a launched
environment variable outrank it, and never write the key anywhere. Each of those is a
statement that would be invisible if it broke - a file appearing on disk, a pushed model
being ignored, a secret coming back out - so each has a test here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.libs import config, llm

from conftest import FakeDB, FakeLLM

LOIS = {"Name": "Lois", "Class": "Warlock", "Current Level": 5}
SECRET = "sk-or-v1-supersecretvalue999"


@pytest.fixture
def clean_model_env(monkeypatch):
    """A process environment with none of the four editable names set.

    The selectors read ``os.environ``, so a developer's own ``.env`` would otherwise decide
    what these tests observe - and a test that passes because of the machine it ran on is
    worse than no test.
    """
    monkeypatch.setattr(config, "_LAUNCH_ENV", {})
    for setting in config.MODEL_SETTINGS:
        monkeypatch.delenv(setting.env, raising=False)
    return monkeypatch


@pytest.fixture
def api(tmp_path, monkeypatch, clean_model_env):
    """A client wired to fakes, with the character sheet overridden."""
    app = create_app(vector_db=FakeDB(), backend=FakeLLM(), character_name="lois",
                     cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data", lambda name, **kw: dict(LOIS))
    return TestClient(app)


# --- the settings table ---


def test_every_setting_names_both_its_wire_and_environment_name():
    """One table, so the page and the CLI cannot drift into two names for one setting."""
    keys = {setting.key for setting in config.MODEL_SETTINGS}
    envs = {setting.env for setting in config.MODEL_SETTINGS}
    assert keys == {"reasoning_model", "fast_model", "api_key", "ollama_model"}
    assert envs == {"LLM_MODEL", "LLM_MODEL_FAST", "OPENROUTER_API_KEY", "OLLAMA_MODEL"}


def test_only_the_key_is_secret():
    secret = [s.key for s in config.MODEL_SETTINGS if s.secret]
    assert secret == ["api_key"]


# --- defaults and overrides ---


def test_defaults_report_only_what_is_set(clean_model_env):
    assert config.model_defaults() == {}
    clean_model_env.setenv("LLM_MODEL", "a/b")
    assert config.model_defaults() == {"LLM_MODEL": "a/b"}


def test_a_client_value_wins_over_the_environment(clean_model_env):
    clean_model_env.setenv("LLM_MODEL", "from/env")
    merged = config.model_overrides({"reasoning_model": "from/browser"})
    assert merged["LLM_MODEL"] == "from/browser"


def test_a_launched_variable_beats_the_client(clean_model_env):
    """The rule that keeps a container or CLI from being second-guessed by a browser tab.

    A process started with an explicit model is a statement about that process, so a value
    pushed from a page must not override it - and the page is told which fields are pinned so
    an edit that has no effect is explained rather than mysterious.
    """
    merged = config.model_overrides({"reasoning_model": "from/browser"},
                                    base={"LLM_MODEL": "pinned:1"})
    assert merged["LLM_MODEL"] == "pinned:1"


def test_a_blank_client_value_clears_rather_than_falls_back(clean_model_env):
    """Clearing a box means "no preference", not "resurrect the old .env entry"."""
    clean_model_env.setenv("LLM_MODEL", "from/env")
    merged = config.model_overrides({"reasoning_model": ""})
    assert merged["LLM_MODEL"] == ""
    assert config.select_model(merged) == ("ollama", config.OLLAMA_MODEL)


def test_an_absent_field_leaves_the_environment_alone(clean_model_env):
    clean_model_env.setenv("LLM_MODEL", "from/env")
    assert config.model_overrides({})["LLM_MODEL"] == "from/env"


def test_a_pushed_model_decides_the_backend(clean_model_env):
    merged = config.model_overrides({"reasoning_model": "vendor/model", "api_key": "k"})
    assert config.select_model(merged) == ("openrouter", "vendor/model")


def test_a_pushed_local_model_selects_ollama(clean_model_env):
    merged = config.model_overrides({"reasoning_model": "qwen3.5:4b"})
    assert config.select_model(merged) == ("ollama", "qwen3.5:4b")


def test_a_pushed_fast_model_is_used(clean_model_env):
    merged = config.model_overrides({"fast_model": "qwen2.5-coder:1.5b-base"})
    assert config.select_fast_model(merged) == ("ollama", "qwen2.5-coder:1.5b-base")


def test_an_unset_fast_model_falls_back_to_the_reasoning_model(clean_model_env):
    merged = config.model_overrides({"reasoning_model": "qwen3.5:4b"})
    assert config.select_fast_model(merged) == config.select_model(merged)


# --- the clients are built from the pushed settings ---


def test_build_llm_honours_a_pushed_ollama_model(clean_model_env):
    client = llm.build_llm(config.model_overrides({"reasoning_model": "qwen2.5-coder:7b-instruct"}))
    assert type(client).__name__ == "OllamaLLM"
    assert client.model == "qwen2.5-coder:7b-instruct"


def test_build_llm_honours_a_pushed_openrouter_model(clean_model_env):
    client = llm.build_llm(
        config.model_overrides({"reasoning_model": "openai/gpt-4o-mini", "api_key": "k"})
    )
    assert type(client).__name__ == "ChatOpenAI"
    assert client.model_name == "openai/gpt-4o-mini"


def test_build_llm_uses_the_pushed_key_not_the_environment_one(clean_model_env):
    """The key travels with the model, or a pushed remote model would be called with no key."""
    clean_model_env.setenv("OPENROUTER_API_KEY", "env-key")
    client = llm.build_llm(
        config.model_overrides({"reasoning_model": "openai/gpt-4o-mini", "api_key": "pushed-key"})
    )
    assert client.openai_api_key.get_secret_value() == "pushed-key"


def test_build_fast_llm_honours_a_pushed_fast_model(clean_model_env):
    client = llm.build_fast_llm(
        config.model_overrides({"fast_model": "qwen2.5-coder:1.5b-base"})
    )
    assert client.model == "qwen2.5-coder:1.5b-base"


def test_the_fast_client_still_caps_its_output(clean_model_env):
    client = llm.build_fast_llm(config.model_overrides({"fast_model": "qwen3.5:4b"}))
    assert client.num_predict == llm.FAST_MAX_TOKENS


def test_a_broken_openrouter_client_falls_back_to_the_pushed_local_model(clean_model_env, monkeypatch):
    """The fallback must be the *local* name, and the pushed one - not the environment's."""
    import langchain_openai

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", lambda **kw: (_ for _ in ()).throw(RuntimeError("bad key")))
    merged = config.model_overrides({
        "reasoning_model": "openai/gpt-4o-mini", "api_key": "k", "ollama_model": "pushed:local",
    })
    client = llm.build_llm(merged)
    assert type(client).__name__ == "OllamaLLM"
    assert client.model == "pushed:local"


# --- the service ---


def test_the_service_resolves_overrides_once(clean_model_env):
    from backend.libs import service

    svc = service.SpellbookService(
        FakeDB(), {}, backend=FakeLLM(),
        overrides={"reasoning_model": "a/b", "api_key": "k", "fast_model": "c/d"},
    )
    assert config.select_model(svc.model_env) == ("openrouter", "a/b")
    assert config.select_fast_model(svc.model_env) == ("openrouter", "c/d")


def test_the_service_without_overrides_reads_the_environment(clean_model_env):
    from backend.libs import service

    # A name with no slash, so it resolves as a local model: a slash would mean OpenRouter and
    # fall back to the default for want of a key, which is a different behaviour.
    clean_model_env.setenv("LLM_MODEL", "env-model:tag")
    svc = service.SpellbookService(FakeDB(), {}, backend=FakeLLM())
    assert config.select_model(svc.model_env) == ("ollama", "env-model:tag")


# --- the endpoints ---


def test_get_settings_lists_every_editable_field(api):
    body = api.get("/api/settings").json()
    assert [field["key"] for field in body["fields"]] == [
        "reasoning_model", "fast_model", "api_key", "ollama_model",
    ]
    assert body["client_storage"] == "localStorage"


def test_get_settings_reports_the_servers_own_fallback(api, clean_model_env):
    clean_model_env.setenv("LLM_MODEL", "env-model:tag")
    body = api.get("/api/settings").json()
    field = next(f for f in body["fields"] if f["key"] == "reasoning_model")
    assert field["value"] == "env-model:tag"


def test_get_settings_never_returns_the_api_key(api, clean_model_env):
    """The credential the server uses must not be readable through this endpoint."""
    clean_model_env.setenv("OPENROUTER_API_KEY", SECRET)
    body = api.get("/api/settings").json()
    assert SECRET not in json.dumps(body)
    field = next(f for f in body["fields"] if f["key"] == "api_key")
    assert field["secret"] is True
    assert field["value"] == "sk-o…e999"


def test_put_settings_applies_the_pushed_model(api, clean_model_env):
    body = api.put("/api/settings", json={"reasoning_model": "qwen2.5-coder:7b-instruct"}).json()
    assert body["reasoning_model"] == "qwen2.5-coder:7b-instruct"
    assert body["reasoning_backend"] == "ollama"


def test_the_pushed_model_reaches_the_next_request(tmp_path, monkeypatch, clean_model_env):
    """The bug this guards is the page appearing to work while nothing changed.

    No ``backend`` is injected, so ``service_for`` builds a real client from the pushed
    settings - and the memoised service must be dropped or the old client keeps answering.
    """
    app = create_app(vector_db=FakeDB(), character_name="lois",
                     cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data", lambda name, **kw: dict(LOIS))
    client = TestClient(app)

    first = client.get("/api/health").json()["model"]
    client.put("/api/settings", json={"reasoning_model": "qwen2.5-coder:7b-instruct"})
    assert client.get("/api/health").json()["model"] == "qwen2.5-coder:7b-instruct"
    assert first != "qwen2.5-coder:7b-instruct", "the fixture must start somewhere else"


def test_put_settings_reports_the_same_model_health_does(tmp_path, monkeypatch, clean_model_env):
    """The page and the health endpoint must not disagree about the model in use.

    Resolving the payload from the environment instead of through the merge was a real
    inconsistency: after a push this reported the server's old model while ``/api/health``,
    which asks the service, reported the new one. No backend is injected, so both endpoints
    resolve a real client and the comparison means something.
    """
    app = create_app(vector_db=FakeDB(), character_name="lois",
                     cache_dir=str(tmp_path / "cache"))
    monkeypatch.setattr("backend.libs.characters.load_character_data", lambda name, **kw: dict(LOIS))
    client = TestClient(app)

    client.put("/api/settings", json={"reasoning_model": "qwen2.5-coder:7b-instruct"})
    assert client.get("/api/settings").json()["reasoning_model"] == \
        client.get("/api/health").json()["model"]


def test_put_settings_never_writes_a_file(api, tmp_path, monkeypatch):
    """The key is a credential, so the server must not keep a copy of it anywhere."""
    monkeypatch.chdir(tmp_path)
    api.put("/api/settings", json={"reasoning_model": "a/b", "api_key": SECRET})
    written = [p.name for p in Path(tmp_path).rglob("*") if p.is_file()]
    assert written == [], f"a push must not write anything, found {written}"


def test_put_settings_does_not_echo_the_key(api, clean_model_env):
    body = api.put("/api/settings", json={"reasoning_model": "a/b", "api_key": SECRET}).json()
    assert SECRET not in json.dumps(body)


def test_a_pinned_setting_is_reported_and_wins(api, clean_model_env):
    """A launched variable outranks the browser, and the page is told which fields those are."""
    clean_model_env.setattr(config, "_LAUNCH_ENV", {"LLM_MODEL": "pinned:1"})
    body = api.put("/api/settings", json={"reasoning_model": "from/browser"}).json()
    assert body["pinned"] == ["reasoning_model"]
    assert body["any_pinned"] is True
    assert body["reasoning_model"] == "pinned:1"


def test_nothing_is_pinned_by_default(api, clean_model_env):
    body = api.get("/api/settings").json()
    assert body["pinned"] == []
    assert body["any_pinned"] is False


def test_put_settings_rejects_an_unknown_field(api):
    """A misspelled field must not be a 200 that changed nothing."""
    assert api.put("/api/settings", json={"reasoning_modle": "a/b"}).status_code == 422


def test_put_settings_accepts_an_empty_push(api, clean_model_env):
    """A client with nothing stored must be able to say so, and get the server's defaults."""
    clean_model_env.setenv("LLM_MODEL", "env-model:tag")
    body = api.put("/api/settings", json={}).json()
    assert body["reasoning_model"] == "env-model:tag"


def test_put_settings_accepts_a_blank_value_as_no_preference(api, clean_model_env):
    clean_model_env.setenv("LLM_MODEL", "env-model:tag")
    body = api.put("/api/settings", json={"reasoning_model": ""}).json()
    assert body["reasoning_model"] == config.OLLAMA_MODEL


def test_openapi_lists_the_settings_routes(api):
    paths = api.get("/openapi.json").json()["paths"]
    assert "/api/settings" in paths
    assert set(paths["/api/settings"]) >= {"get", "put"}


# --- the front end's own contract ---


def test_the_browser_store_owns_the_models_and_the_key():
    """The settings live in `localStorage`, so the module must actually store them.

    A source-level check because the alternative is a browser test, and the failure it guards
    is silent: a page that renders four boxes and persists none of them looks correct until
    the next reload.
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "app" / "lib" / "browserSettings.ts"
    ).read_text(encoding="utf-8")
    assert "what-loadout.models" in source
    assert "readModelSettings" in source and "writeModelSettings" in source


def test_a_wrong_api_base_does_not_hide_the_way_to_fix_it():
    """The address card must render when the settings request fails.

    A wrong API address is the commonest reason ``GET /api/settings`` fails, and the card that
    repairs it is on this very page - so a screen whose failure path returned only the error
    would be unreachable precisely when it is needed. Checked at the source level because the
    symptom is a blank screen rather than a wrong value.
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "app" / "screens" / "SettingsScreen.tsx"
    ).read_text(encoding="utf-8")
    assert "<ApiBaseCard />" in source
    branch = source.index("if (!settings) {")
    card = source.index("<ApiBaseCard />")
    assert card > branch, "the address card must render when the settings fetch fails"
