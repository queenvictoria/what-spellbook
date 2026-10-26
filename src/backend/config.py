"""Repository-wide configuration.

Every path and tunable the backend needs lives here, so the CLI, a future API and the
tests all read the same values instead of reaching into whichever module happened to
define one. Paths are resolved against the repository root rather than the process
working directory, so the package behaves the same however it is launched.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

# src/backend/config.py -> src/backend -> src -> repo root
ROOT = Path(__file__).resolve().parents[2]

# Pull OPENROUTER_API_KEY (and friends) out of the untracked .env file at the repo root.
ENV_FILE = ROOT / ".env"
load_dotenv(ENV_FILE)

# Set up basic configuration for logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- DATA ---
DOCS_DIR = "./data/reddit-spence_post/Spells"
DB_DIR = "./data/chroma_db"

# Bump when the shape or meaning of the stored metadata changes, so a stale index is
# rebuilt instead of silently answering filters with old fields.
INDEX_VERSION = 3

# How many candidate spells to hand the model, and how many get full text. k is per
# filtered query lane; dedupe collapses the many chunks each spell is split into.
RETRIEVAL_K = 60
FULL_TEXT_SPELLS = 12
CONTEXT_DIR = "context"

# Generated books are cached here, keyed by character/level/party/DB version/scenario.
CACHE_DIR = ".cache"

# Character sheets live as YAML files in this directory; CHARACTER env var picks one.
CHARACTERS_DIR = "./data/characters"
DEFAULT_CHARACTER = "lois"

# How many alternative Book of Shadows loadouts the model is asked for. A book holds
# 3 cantrips + 2 level 1 rituals and is one loadout per short rest, so this is how many
# alternatives to compare - not a rules number. Each extra book lengthens the answer
# (and the wait), which is why the ceiling is low rather than unbounded.
BOOK_COUNT = 3
MIN_BOOKS = 1
MAX_BOOKS = 9

# Primary reasoning model: DeepSeek V4.1 Flash over OpenRouter's OpenAI-compatible API.
# Local Ollama (same host the embeddings use) remains the offline fallback.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"
OLLAMA_MODEL = "qwen3.5:4b"
EMBEDDING_MODEL = "nomic-embed-text"


def _clean(value) -> str:
    """Normalise an env value: .env entries are often quoted, blank means unset."""
    return (value or "").strip().strip('"').strip("'").strip()


def select_book_count(env=None) -> int:
    """Return how many books to ask the model for, from ``BOOKS``.

    Clamped rather than rejected: a bad value is a typo in an untracked file, and
    failing a whole run over it would be worse than using a sane number. The clamp is
    reported so a silently ignored setting cannot look like it worked.
    """
    import os

    env = os.environ if env is None else env
    raw = _clean(env.get("BOOKS"))
    if not raw:
        return BOOK_COUNT

    try:
        requested = int(raw)
    except ValueError:
        logging.warning(f"BOOKS='{raw}' is not a whole number; using {BOOK_COUNT}.")
        return BOOK_COUNT

    if requested < MIN_BOOKS or requested > MAX_BOOKS:
        clamped = max(MIN_BOOKS, min(MAX_BOOKS, requested))
        logging.warning(
            f"BOOKS={requested} is outside {MIN_BOOKS}-{MAX_BOOKS}; using {clamped}."
        )
        return clamped

    if requested > 3:
        logging.warning(
            f"BOOKS={requested}: each extra loadout lengthens the answer and the wait."
        )
    return requested


def select_model(env=None) -> tuple[str, str]:
    """Return ``(backend, model)`` for the reasoning model.

    ``LLM_MODEL`` is the single override, and which backend it means is inferred from
    the name rather than from a second setting - the two conventions are unambiguous:
    an OpenRouter id is ``vendor/model`` (always contains a slash) while an Ollama name
    is ``name:tag`` (never does). So:

      LLM_MODEL unset          -> the default for whichever backend the key allows
      LLM_MODEL=deepseek/x     -> OpenRouter
      LLM_MODEL=qwen3.5:4b     -> Ollama, even when an OpenRouter key is present

    That last case is the point: it lets a key be kept in ``.env`` for occasional use
    while running locally by default. If a remote model is requested with no key there
    is nothing to fall back to but Ollama, so that is reported rather than silently
    swapping models.
    """
    import os

    env = os.environ if env is None else env

    requested = _clean(env.get("LLM_MODEL"))
    api_key = _clean(env.get("OPENROUTER_API_KEY"))
    fallback_model = _clean(env.get("OLLAMA_MODEL")) or OLLAMA_MODEL

    if requested:
        if "/" in requested:
            if api_key:
                return "openrouter", requested
            logging.warning(
                f"LLM_MODEL='{requested}' looks like an OpenRouter model but "
                f"OPENROUTER_API_KEY is not set; using Ollama '{fallback_model}'."
            )
        else:
            return "ollama", requested

    return ("openrouter", OPENROUTER_MODEL) if api_key else ("ollama", fallback_model)


def resolve(path) -> Path:
    """Turn a configured relative path into an absolute one under the repo root.

    A bare relative path resolves against the *process* CWD, so running the CLI from
    another directory would silently read a different index, character folder, context
    directory or cache. Every configured path must go through here.
    """
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


# Resolved once at import so every consumer gets an absolute path regardless of the
# directory the CLI was launched from. Preferred over the bare constants above.
DOCS_DIR_PATH = resolve(DOCS_DIR)
DB_DIR_PATH = resolve(DB_DIR)
CACHE_DIR_PATH = resolve(CACHE_DIR)
CONTEXT_DIR_PATH = resolve(CONTEXT_DIR)
CHARACTERS_DIR_PATH = resolve(CHARACTERS_DIR)
