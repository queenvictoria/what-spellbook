"""Tests for choosing the reasoning backend and model.

One `LLM_MODEL` setting covers both backends; the name decides which one, because the
two conventions are unambiguous (OpenRouter is `vendor/model`, Ollama is `name:tag`).
"""

import pytest

from backend.libs import config, llm


# --- routing ---

@pytest.mark.parametrize(
    ("env", "expected"),
    [
        # Nothing requested: the key decides, falling back to the local default.
        ({"OPENROUTER_API_KEY": "k"}, ("openrouter", config.OPENROUTER_MODEL)),
        ({}, ("ollama", config.OLLAMA_MODEL)),
        # An OpenRouter id needs a key to be reachable.
        ({"OPENROUTER_API_KEY": "k", "LLM_MODEL": "anthropic/claude-sonnet-4.5"},
         ("openrouter", "anthropic/claude-sonnet-4.5")),
        ({"LLM_MODEL": "anthropic/claude-sonnet-4.5"}, ("ollama", config.OLLAMA_MODEL)),
        # An Ollama name wins even when a key is present, which is the point of the
        # setting: keep a key in .env but run locally by default.
        ({"OPENROUTER_API_KEY": "k", "LLM_MODEL": "qwen2.5-coder:7b-instruct"},
         ("ollama", "qwen2.5-coder:7b-instruct")),
        ({"LLM_MODEL": "qwen3:4b"}, ("ollama", "qwen3:4b")),
    ],
)
def test_select_model_routes_by_name(env, expected):
    assert config.select_model(env) == expected


@pytest.mark.parametrize("value", ['"qwen3:4b"', "'qwen3:4b'", "  qwen3:4b  ", '" qwen3:4b "'])
def test_select_model_tolerates_quotes_and_spacing(value):
    """Hand-edited .env files are commonly quoted or padded."""
    assert config.select_model({"LLM_MODEL": value}) == ("ollama", "qwen3:4b")


def test_blank_llm_model_falls_through_to_the_default():
    """A key present with no value must not be treated as a model named ''."""
    assert config.select_model({"OPENROUTER_API_KEY": "k", "LLM_MODEL": "   "}) == (
        "openrouter", config.OPENROUTER_MODEL,
    )
    assert config.select_model({"LLM_MODEL": ""}) == ("ollama", config.OLLAMA_MODEL)


def test_ollama_model_env_overrides_the_local_default():
    assert config.select_model({"OLLAMA_MODEL": "glm-4.7-flash:latest"}) == (
        "ollama", "glm-4.7-flash:latest",
    )


def test_a_remote_model_without_a_key_is_reported(caplog):
    """Silently swapping models would make a typo look like a backend failure."""
    with caplog.at_level("WARNING"):
        backend, model = config.select_model({"LLM_MODEL": "openai/gpt-4o-mini"})
    assert backend == "ollama"
    assert "OPENROUTER_API_KEY" in caplog.text


# --- the fast model ---

@pytest.mark.parametrize(
    ("env", "expected"),
    [
        # Unset means "no separate fast model", so the main model answers instead. That is
        # what makes the setting optional rather than required.
        ({"OPENROUTER_API_KEY": "k"}, ("openrouter", config.OPENROUTER_MODEL)),
        ({}, ("ollama", config.OLLAMA_MODEL)),
        ({"OPENROUTER_API_KEY": "k", "LLM_MODEL": "anthropic/claude-sonnet-4.5"},
         ("openrouter", "anthropic/claude-sonnet-4.5")),
        # Set: the fast model is used, and it is independent of the main one.
        ({"OPENROUTER_API_KEY": "k", "LLM_MODEL": "anthropic/claude-sonnet-4.5",
          "LLM_MODEL_FAST": "deepseek/deepseek-v4-flash-0731"},
         ("openrouter", "deepseek/deepseek-v4-flash-0731")),
        ({"OPENROUTER_API_KEY": "k", "LLM_MODEL_FAST": "qwen3:4b"},
         ("ollama", "qwen3:4b")),
        # A remote fast model with no key cannot work, so it falls back and says so.
        ({"LLM_MODEL_FAST": "openai/gpt-4o-mini"}, ("ollama", config.OLLAMA_MODEL)),
    ],
)
def test_select_fast_model_routes_by_name(env, expected):
    assert config.select_fast_model(env) == expected


def test_a_blank_fast_model_falls_through_to_the_main_one():
    """A key present with no value must not be treated as a model named ''."""
    env = {"OPENROUTER_API_KEY": "k", "LLM_MODEL_FAST": "   "}
    assert config.select_fast_model(env) == config.select_model(env)


def test_a_remote_fast_model_without_a_key_is_reported(caplog):
    with caplog.at_level("WARNING"):
        backend, _model = config.select_fast_model({"LLM_MODEL_FAST": "openai/gpt-4o-mini"})
    assert backend == "ollama"
    assert "LLM_MODEL_FAST" in caplog.text


# --- construction ---

@pytest.mark.parametrize(
    ("requested", "expected_type", "expected_model"),
    [
        ("qwen2.5-coder:7b-instruct", "OllamaLLM", "qwen2.5-coder:7b-instruct"),
        ("qwen3:4b", "OllamaLLM", "qwen3:4b"),
    ],
)
def test_build_llm_honours_an_ollama_override(monkeypatch, requested, expected_type, expected_model):
    """Regression: the Ollama branch ignored the requested name entirely."""
    monkeypatch.setenv("LLM_MODEL", requested)
    client = llm.build_llm()
    assert type(client).__name__ == expected_type
    assert client.model == expected_model


def test_build_llm_honours_an_openrouter_override(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    client = llm.build_llm()
    assert type(client).__name__ == "ChatOpenAI"
    assert client.model_name == "openai/gpt-4o-mini"


def test_build_llm_uses_the_local_default_without_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    client = llm.build_llm()
    assert client.model == config.OLLAMA_MODEL


def test_a_broken_openrouter_client_falls_back_to_ollama(monkeypatch, caplog):
    """A bad key must not leave a remote model name pointed at a local server."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")

    import langchain_openai

    def boom(*args, **kwargs):
        raise RuntimeError("bad key")

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", boom)
    with caplog.at_level("WARNING"):
        client = llm.build_llm()
    assert type(client).__name__ == "OllamaLLM"
    assert client.model == config.OLLAMA_MODEL, "must not reuse the OpenRouter id"


def test_build_fast_llm_honours_the_fast_override(monkeypatch):
    """The fast model is a second client, not a second setting on the first."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_MODEL_FAST", "deepseek/deepseek-v4-flash-0731")
    client = llm.build_fast_llm()
    assert type(client).__name__ == "ChatOpenAI"
    assert client.model_name == "deepseek/deepseek-v4-flash-0731"


def test_build_fast_llm_falls_back_to_the_main_model(monkeypatch):
    """Unset means the main model, so a project without the setting is unchanged."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.delenv("LLM_MODEL_FAST", raising=False)
    client = llm.build_fast_llm()
    assert client.model_name == "openai/gpt-4o-mini"


def test_the_fast_client_caps_its_output(monkeypatch):
    """The answer is a phrase, so the call is bounded rather than left open-ended."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL_FAST", "deepseek/deepseek-v4-flash-0731")
    client = llm.build_fast_llm()
    assert client.max_tokens == llm.FAST_MAX_TOKENS


def test_the_fast_budget_leaves_room_for_hidden_reasoning():
    """A cap sized to the *answer* truncates a reasoning model to an empty reply.

    Measured against the configured fast model: a 200-token cap returned nothing on 3 of
    8 calls, because the hidden reasoning consumed the whole budget before the answer
    began. The cap has to cover the reasoning, not the phrase.
    """
    assert llm.FAST_MAX_TOKENS >= 512


def test_the_repo_env_and_the_default_agree():
    """The checked-in default and .env should not silently disagree."""
    from pathlib import Path

    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        pytest.skip(".env is untracked user configuration")

    values = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")

    requested = values.get("LLM_MODEL")
    if not requested:
        pytest.skip("LLM_MODEL is not set in .env")
    if "/" in requested:
        assert requested == config.OPENROUTER_MODEL
    else:
        assert requested == config.OLLAMA_MODEL
