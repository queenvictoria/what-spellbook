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

# --- MODELS ---
# Primary reasoning model: DeepSeek V4.1 Flash over OpenRouter's OpenAI-compatible API.
# Local Ollama (same host the embeddings use) remains the offline fallback.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"
OLLAMA_MODEL = "qwen3.5:4b"
EMBEDDING_MODEL = "nomic-embed-text"


def resolve(path) -> Path:
    """Turn a configured relative path into an absolute one under the repo root.

    A bare relative path would resolve against the process CWD, so running the CLI
    from another directory would silently read a different index or character folder.
    """
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate
