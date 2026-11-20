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
    assert keys == {
        "reasoning_provider", "reasoning_model",
        "fast_provider", "fast_model",
        "api_key", "anthropic_api_key", "ollama_model",
    }
    assert envs == {
        "LLM_PROVIDER", "LLM_MODEL", "LLM_PROVIDER_FAST", "LLM_MODEL_FAST",
        "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_MODEL",
    }


def test_only_the_two_provider_keys_are_secret():
    secret = [s.key for s in config.MODEL_SETTINGS if s.secret]
    assert secret == ["api_key", "anthropic_api_key"]


def test_the_providers_are_a_closed_set():
    """The dropdown's values come from here, so a typo cannot become a provider that is not.

    The set is deliberately small: every entry needs a client branch in ``llm._build``, so an
    open-ended list would let the page save a provider nobody can build.
    """
    assert config.PROVIDERS == ("openrouter", "claude", "ollama")
    assert set(config.PROVIDER_DEFAULT_MODEL) == set(config.PROVIDERS)
    # Ollama needs no key, which is what makes "can this provider run" one lookup.
    assert config.provider_key_env("ollama") is None
    assert config.provider_key_env("openrouter") == "OPENROUTER_API_KEY"
    assert config.provider_key_env("claude") == "ANTHROPIC_API_KEY"


def test_the_provider_is_a_dropdown_and_the_model_is_not():
    choices = {s.key: s.choices for s in config.MODEL_SETTINGS}
    assert choices["reasoning_provider"] == config.PROVIDERS
    assert choices["fast_provider"] == config.PROVIDERS
    assert choices["reasoning_model"] is None


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


def test_an_explicit_provider_beats_the_name(clean_model_env):
    """The bug this exists for: an Ollama model may be a Hugging Face repo id.

    `hf.co/mradermacher/RollMind-v1-gemma3-12b-GGUF:Q4_K_M` contains slashes, and inferring
    "remote" from that sent a local model to OpenRouter - where it failed with a message about
    the API key. The provider is now a setting, so the name is not asked to mean anything.
    """
    hf = "hf.co/mradermacher/RollMind-v1-gemma3-12b-GGUF:Q4_K_M"
    merged = config.model_overrides({
        "reasoning_provider": "ollama", "reasoning_model": hf, "api_key": "k",
    })
    assert config.select_model(merged) == ("ollama", hf)


def test_an_openrouter_provider_does_not_need_a_slash_in_the_name(clean_model_env):
    """The converse: a slashless name is legal on OpenRouter, and the provider is what says so."""
    merged = config.model_overrides({
        "reasoning_provider": "openrouter", "reasoning_model": "somename", "api_key": "k",
    })
    assert config.select_model(merged) == ("openrouter", "somename")


def test_a_remote_provider_without_its_key_falls_back_and_says_so(clean_model_env, caplog):
    """A provider cannot run without a key, so falling back is the only answer - but logged."""
    merged = config.model_overrides({
        "reasoning_provider": "claude", "reasoning_model": "claude-sonnet-4-5",
        "ollama_model": "local:tag",
    })
    with caplog.at_level("WARNING"):
        assert config.select_model(merged) == ("ollama", "local:tag")
    assert "ANTHROPIC_API_KEY" in caplog.text


def test_each_remote_provider_needs_its_own_key(clean_model_env):
    """An OpenRouter key must not make a Claude model look runnable, or it is called with none."""
    openrouter_only = config.model_overrides({
        "reasoning_provider": "claude", "api_key": "k", "ollama_model": "local:tag",
    })
    assert config.select_model(openrouter_only) == ("ollama", "local:tag")

    anthropic_too = config.model_overrides({
        "reasoning_provider": "claude", "api_key": "k", "anthropic_api_key": "a",
    })
    assert config.select_model(anthropic_too) == ("claude", config.ANTHROPIC_MODEL)


def test_an_unknown_provider_is_ignored_rather_than_used(clean_model_env, caplog):
    """A typo must not become a provider nobody can build."""
    merged = config.model_overrides({"reasoning_provider": "opemrouter"})
    with caplog.at_level("WARNING"):
        backend, _model = config.select_model(merged)
    assert backend in {"openrouter", "ollama"}
    assert "LLM_PROVIDER" in caplog.text


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


def test_build_llm_builds_a_claude_client(clean_model_env):
    client = llm.build_llm(config.model_overrides({
        "reasoning_provider": "claude", "reasoning_model": "claude-sonnet-4-5",
        "anthropic_api_key": "a-key",
    }))
    assert type(client).__name__ == "ChatAnthropic"
    assert client.model == "claude-sonnet-4-5"
    assert client.anthropic_api_key.get_secret_value() == "a-key"


def test_the_claude_client_always_carries_a_token_cap(clean_model_env):
    """Anthropic requires a cap where OpenRouter's is optional, so the reasoning path needs one."""
    client = llm.build_llm(config.model_overrides({
        "reasoning_provider": "claude", "anthropic_api_key": "a-key",
    }))
    assert client.max_tokens == llm.REASONING_MAX_TOKENS


def test_the_fast_claude_client_keeps_the_small_cap(clean_model_env):
    client = llm.build_fast_llm(config.model_overrides({
        "fast_provider": "claude", "anthropic_api_key": "a-key",
    }))
    assert client.max_tokens == llm.FAST_MAX_TOKENS


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


def test_the_fast_provider_falls_back_to_the_reasoning_one(clean_model_env):
    """The common case is one service for both, so naming it once must be enough."""
    merged = config.model_overrides({
        "reasoning_provider": "claude", "anthropic_api_key": "a",
        "fast_model": "claude-haiku-4-5",
    })
    assert config.select_fast_model(merged) == ("claude", "claude-haiku-4-5")


def test_the_fast_provider_can_differ_from_the_reasoning_one(clean_model_env):
    merged = config.model_overrides({
        "reasoning_provider": "claude", "anthropic_api_key": "a",
        "fast_provider": "ollama", "fast_model": "qwen3.5:4b",
    })
    assert config.select_model(merged) == ("claude", config.ANTHROPIC_MODEL)
    assert config.select_fast_model(merged) == ("ollama", "qwen3.5:4b")


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
        "reasoning_provider", "reasoning_model",
        "fast_provider", "fast_model",
        "api_key", "anthropic_api_key", "ollama_model",
    ]
    assert body["client_storage"] == "localStorage"


def test_every_field_names_the_card_it_belongs_in(api):
    """The page groups by the table rather than by its own list of keys."""
    body = api.get("/api/settings").json()
    groups = {field["key"]: field["group"] for field in body["fields"]}
    assert groups["reasoning_provider"] == "Models"
    assert groups["api_key"] == "API keys"
    assert groups["ollama_model"] == "Fallback"


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
    assert body["reasoning_provider"] == "ollama"


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


def test_a_second_save_does_not_wipe_the_key(api, clean_model_env):
    """The bug the user reported: saving twice lost the key.

    A secret box is never pre-filled — the response carries only a mask — so the page cannot
    resend a key it already holds. Treating an absent field as "cleared" therefore blanked the
    credential on the second save, and the model then fell back to Ollama with no explanation.
    Absent now means "no change"; only a blank string removes a key.
    """
    api.put("/api/settings", json={"reasoning_provider": "openrouter", "api_key": SECRET})
    # A second save that only touches the model box: the key is not resent.
    body = api.put("/api/settings", json={"reasoning_model": "openai/gpt-4o-mini"}).json()
    assert body["reasoning_provider"] == "openrouter"
    field = next(f for f in body["fields"] if f["key"] == "api_key")
    assert field["value"] == "sk-o…e999", "the key must survive a save that does not mention it"


def test_a_blank_key_removes_it(api, clean_model_env):
    """Which is what the Clear button sends, and the only way to forget a key."""
    api.put("/api/settings", json={"api_key": SECRET})
    body = api.put("/api/settings", json={"api_key": ""}).json()
    field = next(f for f in body["fields"] if f["key"] == "api_key")
    assert field["value"] is None


def test_clearing_a_key_drops_the_provider_to_the_fallback(api, clean_model_env):
    """A key that is gone cannot serve a remote provider, and saying so beats a silent swap."""
    api.put("/api/settings", json={
        "reasoning_provider": "claude", "reasoning_model": "claude-sonnet-4-5",
        "anthropic_api_key": "a-key", "ollama_model": "local:tag",
    })
    body = api.put("/api/settings", json={"anthropic_api_key": ""}).json()
    assert body["reasoning_provider"] == "ollama"
    assert body["reasoning_model"] == "local:tag"


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


def test_an_empty_push_forgets_everything(api, clean_model_env):
    """Which is what Reset sends, so merging an empty push would make Reset a no-op.

    A browser with nothing stored has no opinion to merge, so `{}` cannot mean "keep what you
    have" - that would leave the server using values the page had just told it to forget.
    """
    api.put("/api/settings", json={"api_key": SECRET, "reasoning_provider": "openrouter"})
    body = api.put("/api/settings", json={}).json()
    field = next(f for f in body["fields"] if f["key"] == "api_key")
    assert field["value"] is None
    assert body["reasoning_provider"] == "ollama"


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


def test_the_page_only_pushes_what_was_changed():
    """The client half of the key-survival fix, checked at the source level.

    A source-level check because the failure is silent in both directions: pushing every box
    sends an empty secret (so a save wipes the key), and pushing nothing makes Save a no-op.
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "app" / "screens" / "SettingsScreen.tsx"
    ).read_text(encoding="utf-8")
    assert "if (!touched[field.key]) continue" in source
    # The Clear button sends a blank value through the same path, so removal stays explicit.
    assert "onClear={() => edit(field, \"\")}" in source


def test_the_page_offers_the_provider_as_a_dropdown():
    """The provider is a closed set, so a text box would let a typo become a wrong backend."""
    source = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "app" / "screens" / "SettingsScreen.tsx"
    ).read_text(encoding="utf-8")
    assert "field.choices ?" in source
    assert "<Select" in source


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
