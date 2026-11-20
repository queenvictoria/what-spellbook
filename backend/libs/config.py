"""Repository-wide configuration.

Every path and tunable the backend needs lives here, so the CLI, a future API and the
tests all read the same values instead of reaching into whichever module happened to
define one. Paths are resolved against the repository root rather than the process
working directory, so the package behaves the same however it is launched.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# backend/libs/config.py -> backend/libs -> backend -> repo root
ROOT = Path(__file__).resolve().parents[2]

# Pull CHARACTER (and friends) out of the untracked .env file at the repo root.
ENV_FILE = ROOT / ".env"

# Snapshot the *launching* environment before .env is merged into it. ``load_dotenv`` does not
# overwrite an existing variable, so after the merge a variable set in the shell and one read
# from .env look identical in ``os.environ`` - and only the shell one may outrank a browser.
# See ``model_overrides``.
_LAUNCH_ENV = dict(os.environ)

load_dotenv(ENV_FILE)

# Set up basic configuration for logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- DATA ---
DOCS_DIR = "./data/reddit-spence_post/Spells"
DB_DIR = "./data/chroma_db"

# Bump when the shape or meaning of the stored metadata changes, so a stale index is
# rebuilt instead of silently answering filters with old fields.
#
# 4 added ``doc_type`` and the vendored SRD rows. Both are required: the eligibility
# filters now key on ``doc_type``, so an index written at 3 has no such field and every
# filter would silently match nothing - the exact failure the version guard exists for.
#
# Deliberately *not* bumped for the optional ``ionas-politis`` rows. A new row is not a
# changed shape - ``doc_type`` already exists and filters keep working - so a bump would
# force every user a full re-embed for a source most do not have, which is the same
# "invalidates the user's data for nothing" mistake the cache schema notes describe. What
# actually needs guarding is that an *installed* source is missing from the index, and that
# is checked precisely, by ``indexing.sources_match`` against the index's own record.
#
# 5 removed 540 content-free rows. An injected ``Spell Name: <name>`` line sat above each
# page's own ``#`` heading, so the heading splitter cut it into a chunk containing nothing
# else - one per spell page, 11.5% of the whole index, every one of them an embedded row
# that could return as a search hit showing a spell's name and no text. This *is* a change
# to the rows rather than to the shape, so ``sources_match`` cannot see it and the version
# is the only guard that can. The cost is deliberate and bounded: a rebuild, plus one fresh
# model call for the next recommendation per character, because ``db_version`` joins the run
# cache key. Existing runs are not deleted - ``cache.load_runs`` globs every version - so
# history and ratings survive; they are only no longer *replayed*, which is the honest
# behaviour when the index that produced them has changed underneath.
INDEX_VERSION = 5

# The optional second rulebook - the DnD Character Sheet Helper JSON, read in place and
# skipped when absent. Point ``IONAS_DIR`` at a checkout elsewhere to override. See
# ``backend/libs/ionas.py`` for why it is optional and what it is worth.
IONAS_DIR = "context/DnD-Character-Sheet-Helper/rulebook"

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

# --- DEV SERVERS ---
# The API and the Vite dev server are separate processes on separate ports, and more
# than one person (or one agent) may be running a copy of each on the same machine. So
# neither port is hard-coded: the API reads API_PORT, the front end reads VITE_PORT, and
# the API's CORS allow-list is derived from the front end's port rather than fixed.
API_PORT = 8000
FRONTEND_PORT = 5173

# Extra browser origins to accept, comma-separated, for the case where the front end is
# served from somewhere the derived list does not cover (a second dev server, a LAN
# address, a preview build). The derived origins are always included.
CORS_ORIGINS = ""


def select_port(name: str, default: int, env=None) -> int:
    """Return a TCP port from ``name``, falling back to ``default``.

    A bad value is a typo in an untracked file, so it is reported and ignored rather
    than raised: refusing to start over a malformed port would be worse than using the
    documented default. Out-of-range values are rejected for the same reason - a port
    outside 1-65535 cannot bind, and failing at bind time with a clear message beats
    failing here with a stack trace.
    """
    env = os.environ if env is None else env
    raw = _clean(env.get(name))
    if not raw:
        return default

    try:
        port = int(raw)
    except ValueError:
        logging.warning(f"{name}='{raw}' is not a whole number; using {default}.")
        return default

    if not 1 <= port <= 65535:
        logging.warning(f"{name}={port} is outside 1-65535; using {default}.")
        return default

    return port


def dev_origins(env=None) -> list[str]:
    """Return the browser origins the API should accept.

    The Vite dev server is reached as either ``localhost`` or ``127.0.0.1`` depending on
    how it was opened, and those are distinct origins to a browser, so both spellings of
    the configured port are allowed. ``CORS_ORIGINS`` adds anything else.
    """
    env = os.environ if env is None else env
    port = select_port("FRONTEND_PORT", FRONTEND_PORT, env)

    origins = [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]
    for extra in _clean(env.get("CORS_ORIGINS")).split(","):
        origin = extra.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


# Primary reasoning model: DeepSeek V4.1 Flash over OpenRouter's OpenAI-compatible API.
# Local Ollama (same host the embeddings use) remains the offline fallback.
#
# These are **fallbacks only**. The model is chosen in the browser (the Settings tab) and sent
# with each request, so nothing here needs to be set for the app to work - an unset
# ``LLM_MODEL`` simply means "whatever the front end asked for". They exist so the CLI, which
# has no browser, and an unconfigured client both have somewhere obvious to land.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"
OLLAMA_MODEL = "qwen3.5:4b"
EMBEDDING_MODEL = "nomic-embed-text"


@dataclass(frozen=True)
class ModelSetting:
    """One setting a client may send, and the environment name it stands in for.

    ``key`` is the wire name the front end uses; ``env`` is the environment variable the CLI
    uses. Both name the same thing, so the table is what stops the two surfaces drifting into
    different vocabulary for one setting - and it is the list the API validates a request
    against, so a name not in it can never become configuration.
    """

    key: str
    env: str
    label: str
    help: str
    secret: bool = False


# The settings a browser may supply, in display order.
MODEL_SETTINGS: tuple[ModelSetting, ...] = (
    ModelSetting(
        key="reasoning_model",
        env="LLM_MODEL",
        label="Reasoning model",
        help=(
            "Writes the book recommendations. A name containing a slash is an OpenRouter id "
            "(vendor/model); anything else is an Ollama model on this machine."
        ),
    ),
    ModelSetting(
        key="fast_model",
        env="LLM_MODEL_FAST",
        label="Fast model",
        help=(
            "Answers the one-line questions, such as how a spell scales at the loaded level. "
            "Leave empty to use the reasoning model."
        ),
    ),
    ModelSetting(
        key="api_key",
        env="OPENROUTER_API_KEY",
        label="OpenRouter API key",
        help="Needed by any model whose name contains a slash.",
        secret=True,
    ),
    ModelSetting(
        key="ollama_model",
        env="OLLAMA_MODEL",
        label="Local Ollama model",
        help="Used when no OpenRouter key is set, or when the reasoning model names a local model.",
    ),
)

MODEL_SETTING_KEYS = tuple(setting.key for setting in MODEL_SETTINGS)
MODEL_SETTINGS_BY_KEY = {setting.key: setting for setting in MODEL_SETTINGS}


def model_defaults(env=None) -> dict[str, str]:
    """The environment's own values for the editable settings, keyed by ``env`` name.

    Sent to the front end so a fresh browser can start from whatever the server has - a
    launched ``LLM_MODEL``, or a hand-edited ``.env`` - instead of an empty form. Only names
    that are actually set appear, so "unset" stays distinguishable from "set to blank".
    """
    env = os.environ if env is None else env
    found = {}
    for setting in MODEL_SETTINGS:
        value = _clean(env.get(setting.env))
        if value:
            found[setting.env] = value
    return found


def model_overrides(values, *, env=None, base=None) -> dict[str, str]:
    """Merge a client's settings over the environment, returning the effective name map.

    The client's value wins **unless the environment set it at launch**, which is the one case
    where a per-run statement has to beat a per-browser one - a CLI or a container started with
    an explicit model must not be second-guessed by whatever a browser tab has stored. A
    *blank* client value is kept rather than treated as absent, so clearing a box on the
    settings page genuinely means "no preference" and falls through to the default instead of
    silently resurrecting an old ``.env`` entry.

    ``base`` replaces the launch environment, which is what a test needs to check the rule
    without touching the real one.
    """
    launch = _launch_env() if base is None else base
    merged = dict(env if env is not None else os.environ)
    for setting in MODEL_SETTINGS:
        if setting.key not in values:
            continue
        value = values[setting.key]
        if _clean(launch.get(setting.env)):
            merged[setting.env] = launch[setting.env]     # pinned for this process
        else:
            merged[setting.env] = "" if value is None else str(value)
    return merged


def _launch_env() -> dict[str, str]:
    """The environment as it was when the process started, before ``.env`` was merged.

    ``load_dotenv`` does not overwrite an existing variable, so once it has run a shell
    variable and a ``.env`` one are indistinguishable in ``os.environ`` - and only the shell
    one should outrank a browser. Snapshotting at import is what keeps that distinction.
    """
    return _LAUNCH_ENV


def _clean(value) -> str:
    """Normalise an env value: .env entries are often quoted, blank means unset."""
    return (value or "").strip().strip('"').strip("'").strip()


def mask_secret(value: str | None) -> str | None:
    """A secret reduced to enough to recognise it and not enough to use it.

    The API returns this instead of the key so the settings response is never a way to read a
    credential back out of the server. It is deliberately not a fixed-width redaction: the
    point is that a user can tell *which* key is loaded, and ``sk-o…e999`` does that where
    ``***`` does not.
    """
    if not value:
        return None
    if len(value) <= 8:
        return "…"
    return f"{value[:4]}…{value[-4:]}"


def select_book_count(env=None) -> int:
    """Return how many books to ask the model for, from ``BOOKS``.

    Clamped rather than rejected: a bad value is a typo in an untracked file, and
    failing a whole run over it would be worse than using a sane number. The clamp is
    reported so a silently ignored setting cannot look like it worked.
    """
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


def select_fast_model(env=None) -> tuple[str, str]:
    """Return ``(backend, model)`` for the small, fast model.

    ``LLM_MODEL_FAST`` is a second, independent setting rather than a modifier on
    ``LLM_MODEL``, because the two do different jobs: the main model writes a whole
    recommendation and is worth waiting for, while the fast one answers a one-line
    question about a spell and is not. Pointing it at a smaller model is the point.

    Unset means "no separate fast model", and the main model is used instead - so the
    setting is optional and a project without it behaves exactly as before. Routing is
    the same name-based inference ``select_model`` uses, and for the same reason.
    """
    env = os.environ if env is None else env

    requested = _clean(env.get("LLM_MODEL_FAST"))
    if not requested:
        return select_model(env)

    api_key = _clean(env.get("OPENROUTER_API_KEY"))
    fallback_model = _clean(env.get("OLLAMA_MODEL")) or OLLAMA_MODEL

    if "/" in requested:
        if api_key:
            return "openrouter", requested
        logging.warning(
            f"LLM_MODEL_FAST='{requested}' looks like an OpenRouter model but "
            f"OPENROUTER_API_KEY is not set; using Ollama '{fallback_model}'."
        )
        return "ollama", fallback_model

    return "ollama", requested


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
IONAS_DIR_PATH = resolve(IONAS_DIR)
