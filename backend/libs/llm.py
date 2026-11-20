"""Reasoning-model selection and response normalisation."""

from __future__ import annotations

import logging

from . import config


# The fast model answers a one-line question, so its budget is a phrase rather than a
# document - but the cap cannot be as small as the answer, and that is a trap worth
# recording. The configured fast model is a *reasoning* model: it spends hidden reasoning
# tokens before writing anything, and `max_tokens` caps those too. Measured over 8 calls
# on one prompt, a cap of 200 returned an empty completion 3 times out of 8, because the
# reasoning alone consumed the whole budget and the response was truncated before a single
# word of the answer. 512 was clean over the same run; 1024 leaves room for the spikes
# (reasoning reached 1635 tokens on one call at a higher cap).
FAST_MAX_TOKENS = 1024

# The reasoning model writes three whole books, and the Anthropic API requires a cap where
# OpenRouter's is optional. Only used by the Claude branch, but sized for the job: it must not
# truncate an answer that OpenRouter would have delivered uncapped.
REASONING_MAX_TOKENS = 8192

# Where Ollama listens when OLLAMA_HOST is unset. Both the reasoning model and the
# embeddings model are reached here, so a failure to connect means the whole local stack
# is down rather than one model.
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def ollama_host() -> str:
    """The Ollama address, so an error can name what it tried to reach."""
    import os

    return (os.getenv("OLLAMA_HOST") or "").strip() or DEFAULT_OLLAMA_HOST


def _text_of(error) -> str:
    return f"{type(error).__name__}: {error}".lower()


def names_connection_failure(error) -> bool:
    """Whether ``error`` is the transport failing, rather than the server answering badly.

    Ollama's client raises a builtin ``ConnectionError`` when nothing is listening, but
    httpx and urllib3 surface their own spellings through LangChain, so the message is
    checked too. The distinction matters: a connection failure has one obvious fix (start
    Ollama) and every other failure does not.
    """
    if isinstance(error, ConnectionError):
        return True
    return any(needle in _text_of(error) for needle in (
        "failed to connect",
        "connection refused",
        "connecterror",
        "connection error",
        "max retries exceeded",
        "name or service not known",
        "temporary failure in name resolution",
        "nodename nor servname",
    ))


def names_auth_failure(error) -> bool:
    """Whether the provider answered that the credential is not acceptable.

    A 401 or 403 is the provider *replying*, so it is not a transport failure and must not be
    reported as one. Kept separate for the advice: a connection failure is fixed by starting a
    server or a network, an auth failure only by changing the key.

    Matched on both the status and the body because the two spellings arrive by different
    stacks: LangChain surfaces OpenAI's ``Error code: 401`` prefix, while the Anthropic client
    says ``authentication_error``.
    """
    text = _text_of(error)
    if "401" in text or "403" in text:
        return True
    return any(needle in text for needle in (
        "unauthorized",
        "authentication",
        "invalid api key",
        "incorrect api key",
        "invalid_api_key",
        "authentication_error",
        "missing credentials",
    ))


def names_missing_model(error) -> bool:
    """Whether Ollama answered that the requested model is not present."""
    text = _text_of(error)
    return "not found" in text or "no such model" in text or "pull model" in text


def explain_failure(error, *, model: str | None = None, purpose: str = "the model",
                    local: bool = True, provider: str = "openrouter") -> str:
    """Turn a backend exception into a sentence a person can act on.

    The raw text from the Ollama client is ``Failed to connect to Ollama. Please check that
    Ollama is downloaded, running and accessible. https://ollama.com/download``, which says
    what is wrong but not what to do about it in *this* project - and it is buried behind
    an HTTP 503 the UI only shows as a red line. Naming the address, the command and the
    model is the difference between a bug report and a fix.

    ``provider`` names which key a remote failure is about, because naming the wrong one
    sends the user to edit a credential the failing request never read.
    """
    if local and names_connection_failure(error):
        message = (
            f"Ollama is not reachable at {ollama_host()}, so {purpose} could not run. "
            "Start it with: ollama serve"
        )
        if model:
            message += f" - and make sure the model is installed with: ollama pull {model}"
        return message + ". Then retry."
    if local and names_missing_model(error) and model:
        return (
            f"Ollama is running but does not have the model '{model}'. Install it with: "
            f"ollama pull {model} - then retry."
        )
    if not local and names_auth_failure(error):
        # The provider answered, so the network is fine and something about the credential is
        # not. Saying "could not reach it" here was actively misleading: a 401 arrives from a
        # reachable server, and the raw body ("Missing Authentication header") reads like a bug
        # in this code rather than like a key that is wrong.
        named = f"'{model}'" if model else "the model"
        key_env = config.provider_key_env(provider) or "the API key"
        return (
            f"{config.provider_label(provider)} rejected the API key, so {named} could not "
            f"run. "
            f"Check {key_env} on the Settings tab - it must be the whole key, pasted from the "
            f"provider, not the masked preview this app shows. Then retry."
        )
    if not local and names_connection_failure(error):
        # A remote provider is not something the user can start, so the advice is about the
        # two things they *can* change: the key and the network.
        named = f"'{model}'" if model else "the model"
        key_env = config.provider_key_env(provider) or "the API key"
        return (
            f"Could not reach {named} at {config.provider_label(provider)}. Check that "
            f"{key_env} is set and valid, and that the network allows the request."
        )
    if isinstance(error, TimeoutError) or "timed out" in _text_of(error):
        return (
            f"{purpose.capitalize()} timed out. A local model can be slow to load into "
            "memory on first use; retry in a moment."
        )
    return f"Could not reach {purpose}: {error}"


def build_llm(env=None):
    """Build the reasoning client chosen by ``config.select_model()``.

    One ``LLM_MODEL`` setting covers both backends; see ``select_model`` for how the
    name decides which one. A failure to construct the OpenRouter client (bad key,
    missing dependency) drops back to Ollama rather than aborting the session.

    ``env`` is the effective environment to read. The API passes the merged
    environment - the environment overlaid with whatever the browser sent - while the CLI
    passes nothing and gets ``os.environ``. A mapping rather than a dataclass because that is
    what ``select_model`` already takes, so the two surfaces cannot disagree about precedence
    by each doing their own merge.
    """
    return _build(config.select_model(env), label="LLM", env=env)


def build_fast_llm(env=None):
    """Build the small, fast client chosen by ``config.select_fast_model()``.

    A second client rather than a second setting on the first, because the two do
    different jobs: the reasoning model writes a whole recommendation and is worth
    waiting for, while this one answers a one-line question about a spell - "how many
    beams does this cantrip have at level 5?" - where the answer is a phrase and the
    wait would cost more than the answer is worth.

    ``LLM_MODEL_FAST`` unset means the main model is used, so the setting is optional.
    """
    return _build(config.select_fast_model(env), label="fast LLM",
                  max_tokens=FAST_MAX_TOKENS, env=env)


def _build(selection: tuple[str, str], *, label: str, max_tokens: int | None = None,
           env=None):
    """Construct one client from a resolved ``(provider, model)`` pair.

    Shared by both builders so the two cannot disagree about how a provider is reached -
    the bug this replaced was a branch that read the requested model in one path and a
    hard-coded default in the other.

    A provider that cannot be constructed falls back to Ollama rather than aborting the
    session, because a settings page saved on another machine is not a reason to have no
    working backend at all. The fallback is logged and named, so it never looks like the
    requested model answered.
    """
    import os

    from langchain_ollama import OllamaLLM

    provider, model = selection
    source = os.environ if env is None else env

    if provider == "openrouter":
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=model,
                api_key=_usable_key(provider, source),
                base_url=config.OPENROUTER_BASE_URL,
                temperature=0.3,
                max_retries=2,
                timeout=180,
                **({"max_tokens": max_tokens} if max_tokens else {}),
            )
            logging.info(f"{label} provider: OpenRouter ({model})")
            return llm
        except Exception as e:
            return _local_fallback(label, model, source, e)

    if provider == "claude":
        try:
            from langchain_anthropic import ChatAnthropic

            llm = ChatAnthropic(
                model=model,
                api_key=_usable_key(provider, source),
                temperature=0.3,
                max_retries=2,
                default_request_timeout=180,
                # `max_tokens` is *required* by the Anthropic API rather than optional, so the
                # reasoning client needs a floor even though it is the one caller that does not
                # care about a cap. Sized well above the fast cap because this is the model that
                # writes three whole books.
                max_tokens=max_tokens or REASONING_MAX_TOKENS,
            )
            logging.info(f"{label} provider: Claude ({model})")
            return llm
        except Exception as e:
            return _local_fallback(label, model, source, e)

    # `model` is already the resolved Ollama name, including any LLM_MODEL override.
    logging.info(f"{label} provider: Ollama ({model})")
    return OllamaLLM(model=model, **({"num_predict": max_tokens} if max_tokens else {}))


def _usable_key(provider: str, source) -> str:
    """One provider's key from the effective environment, refusing a value that cannot be one.

    A guard rather than a formality, because the client libraries do not provide it:
    ``ChatOpenAI`` raises on an *absent* key and accepts any string otherwise, so a mask
    (``…``) or a placeholder builds a working client that fails at the provider with
    ``401 Missing Authentication header``. Raising here instead keeps that failure local,
    where the message can say which box is wrong.
    """
    name = config.PROVIDER_KEY_ENV[provider]
    value = config._clean(source.get(name))
    problem = config.key_problem(provider, value)
    if problem is not None:
        raise ValueError(problem)
    return value


def _local_fallback(label: str, model: str, source, error):
    """Hand back the local client after a remote one could not be constructed.

    The fallback must be the *Ollama* default and not the requested remote id, which no local
    server would recognise - and it must honour the pushed ``OLLAMA_MODEL``, so a browser's
    local name is still used.
    """
    from langchain_ollama import OllamaLLM

    logging.warning(
        f"Could not initialise the {label} provider for '{model}' ({error}); "
        f"falling back to Ollama."
    )
    fallback = config._clean(source.get("OLLAMA_MODEL")) or config.OLLAMA_MODEL
    logging.info(f"{label} provider: Ollama ({fallback})")
    return OllamaLLM(model=fallback)


def extract_text(response) -> str:
    """Normalise Ollama's string output and ChatOpenAI's AIMessage to plain text."""
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if callable(text):
        text = text()
    return text if text else str(getattr(response, "content", response))


def model_name(llm) -> str:
    """Best-effort label for the model that produced an answer."""
    for attribute in ("model", "model_name"):
        value = getattr(llm, attribute, None)
        if isinstance(value, str):
            return value
    return type(llm).__name__


class EmptyCompletion(RuntimeError):
    """Raised when the backend returns no text.

    Ollama's thinking models (for example qwen3.5) can spend the whole token budget on
    hidden reasoning and return an empty ``response``. Treating that as success makes a
    failed run look like a successful one, so it is surfaced as an error.
    """


class LLMUnavailable(RuntimeError):
    """Raised when the backend call itself fails (network, auth, transport)."""


class EmbeddingUnavailable(LLMUnavailable):
    """Raised when the *embedding* backend fails, which is the same Ollama the model uses.

    A subclass rather than a sibling so every surface that already handles
    ``LLMUnavailable`` handles this too - the CLI's commands and the API's routes all need
    the same "the local stack is down, retry when it is back" treatment, and a second type
    would have to be added to each of them or it would fall through as an unhandled 500.
    """


def is_local(llm) -> bool:
    """Whether this client talks to a local Ollama rather than a remote provider.

    The advice differs: a local failure is fixed with ``ollama serve``, a remote one is a
    key, quota or network problem. Decided by client type rather than by re-reading the
    environment, which could have changed since the client was built.
    """
    return client_provider(llm) == "ollama"


def client_provider(llm) -> str:
    """Which provider a built client talks to, decided by its type.

    Read off the client rather than off the environment for the same reason ``is_local`` is:
    the environment may have changed since the client was built, and a message that names the
    wrong key sends the user to edit a credential the failing request never read.
    """
    name = type(llm).__name__.lower()
    if name.startswith("ollama"):
        return "ollama"
    if name.startswith("chatanthropic"):
        return "claude"
    return "openrouter"


def embedding_failure(error) -> "EmbeddingUnavailable | None":
    """Translate a vector store's embedding exception, or return ``None``.

    Embeddings go to the same Ollama as the reasoning model, so the same transport failure
    appears here with a different stack: the store calls ``embed_documents`` while adding
    or ``embed_query`` while searching, and the ``ConnectionError`` surfaces from
    ``langchain_chroma`` rather than from ``invoke``. Callers in ``indexing``, ``search``
    and ``retrieval`` all need it typed, and none of them should each invent a message.
    """
    if not names_connection_failure(error) and not isinstance(error, TimeoutError):
        return None
    return EmbeddingUnavailable(
        explain_failure(error, model=config.EMBEDDING_MODEL,
                        purpose="the embeddings model")
    )


def invoke(llm, prompt: str) -> str:
    """Call the backend once, raising ``EmptyCompletion`` on a blank answer."""
    try:
        text = extract_text(llm.invoke(prompt))
    except Exception as e:
        raise LLMUnavailable(
            explain_failure(e, model=model_name(llm), purpose="the model",
                            local=is_local(llm),
                            provider=client_provider(llm))
        ) from e
    if not text.strip():
        raise EmptyCompletion(
            "The model returned an empty response. This usually means it used its "
            "entire token budget on internal reasoning, or the prompt exceeded the "
            "model's context window."
        )
    return text
