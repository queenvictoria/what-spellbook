"""Reasoning-model selection and response normalisation."""

from __future__ import annotations

import logging

from . import config


def build_llm():
    """Build the reasoning client chosen by ``config.select_model()``.

    One ``LLM_MODEL`` setting covers both backends; see ``select_model`` for how the
    name decides which one. A failure to construct the OpenRouter client (bad key,
    missing dependency) drops back to Ollama rather than aborting the session.
    """
    import os

    from langchain_ollama import OllamaLLM

    backend, model = config.select_model()
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
            )
            logging.info(f"LLM backend: OpenRouter ({model})")
            return llm
        except Exception as e:
            logging.warning(
                f"Could not initialise OpenRouter client ({e}); falling back to Ollama."
            )
            # A failed construction still falls back to the *Ollama* default, not to the
            # requested OpenRouter id, which no local server would recognise.
            fallback = config.OLLAMA_MODEL
            logging.info(f"LLM backend: Ollama ({fallback})")
            return OllamaLLM(model=fallback)

    # `model` is already the resolved Ollama name, including any LLM_MODEL override.
    logging.info(f"LLM backend: Ollama ({model})")
    return OllamaLLM(model=model)


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
