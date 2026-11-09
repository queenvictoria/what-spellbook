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


def names_missing_model(error) -> bool:
    """Whether Ollama answered that the requested model is not present."""
    text = _text_of(error)
    return "not found" in text or "no such model" in text or "pull model" in text


def explain_failure(error, *, model: str | None = None, purpose: str = "the model",
                    local: bool = True) -> str:
    """Turn a backend exception into a sentence a person can act on.

    The raw text from the Ollama client is ``Failed to connect to Ollama. Please check that
    Ollama is downloaded, running and accessible. https://ollama.com/download``, which says
    what is wrong but not what to do about it in *this* project - and it is buried behind
    an HTTP 503 the UI only shows as a red line. Naming the address, the command and the
    model is the difference between a bug report and a fix.
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
    if not local and names_connection_failure(error):
        # A remote provider is not something the user can start, so the advice is about the
        # two things they *can* change: the key and the network.
        named = f"'{model}'" if model else "the model"
        return (
            f"Could not reach {named} at the configured provider. Check that "
            "OPENROUTER_API_KEY is set and valid, and that the network allows the request."
        )
    if isinstance(error, TimeoutError) or "timed out" in _text_of(error):
        return (
            f"{purpose.capitalize()} timed out. A local model can be slow to load into "
            "memory on first use; retry in a moment."
        )
    return f"Could not reach {purpose}: {error}"


def build_llm():
    """Build the reasoning client chosen by ``config.select_model()``.

    One ``LLM_MODEL`` setting covers both backends; see ``select_model`` for how the
    name decides which one. A failure to construct the OpenRouter client (bad key,
    missing dependency) drops back to Ollama rather than aborting the session.
    """
    return _build(config.select_model(), label="LLM")


def build_fast_llm():
    """Build the small, fast client chosen by ``config.select_fast_model()``.

    A second client rather than a second setting on the first, because the two do
    different jobs: the reasoning model writes a whole recommendation and is worth
    waiting for, while this one answers a one-line question about a spell - "how many
    beams does this cantrip have at level 5?" - where the answer is a phrase and the
    wait would cost more than the answer is worth.

    ``LLM_MODEL_FAST`` unset means the main model is used, so the setting is optional.
    """
    return _build(config.select_fast_model(), label="fast LLM",
                  max_tokens=FAST_MAX_TOKENS)


def _build(selection: tuple[str, str], *, label: str, max_tokens: int | None = None):
    """Construct one client from a resolved ``(backend, model)`` pair.

    Shared by both builders so the two cannot disagree about how a backend is reached -
    the bug this replaced was a branch that read the requested model in one path and a
    hard-coded default in the other.
    """
    import os

    from langchain_ollama import OllamaLLM

    backend, model = selection
    api_key = os.getenv("OPENROUTER_API_KEY")

    if backend == "openrouter":
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url=config.OPENROUTER_BASE_URL,
                temperature=0.3,
                max_retries=2,
                timeout=180,
                **({"max_tokens": max_tokens} if max_tokens else {}),
            )
            logging.info(f"{label} backend: OpenRouter ({model})")
            return llm
        except Exception as e:
            logging.warning(
                f"Could not initialise OpenRouter client ({e}); falling back to Ollama."
            )
            # A failed construction still falls back to the *Ollama* default, not to the
            # requested OpenRouter id, which no local server would recognise.
            fallback = config.OLLAMA_MODEL
            logging.info(f"{label} backend: Ollama ({fallback})")
            return OllamaLLM(model=fallback)

    # `model` is already the resolved Ollama name, including any LLM_MODEL override.
    logging.info(f"{label} backend: Ollama ({model})")
    return OllamaLLM(model=model, **({"num_predict": max_tokens} if max_tokens else {}))


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
    return type(llm).__name__.lower().startswith("ollama")


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
                            local=is_local(llm))
        ) from e
    if not text.strip():
        raise EmptyCompletion(
            "The model returned an empty response. This usually means it used its "
            "entire token budget on internal reasoning, or the prompt exceeded the "
            "model's context window."
        )
    return text
