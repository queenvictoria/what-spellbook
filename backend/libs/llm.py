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


def invoke(llm, prompt: str) -> str:
    """Call the backend once, raising ``EmptyCompletion`` on a blank answer."""
    try:
        text = extract_text(llm.invoke(prompt))
    except Exception as e:
        raise LLMUnavailable(str(e)) from e
    if not text.strip():
        raise EmptyCompletion(
            "The model returned an empty response. This usually means it used its "
            "entire token budget on internal reasoning, or the prompt exceeded the "
            "model's context window."
        )
    return text
