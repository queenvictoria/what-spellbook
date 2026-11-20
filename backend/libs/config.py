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
ANTHROPIC_MODEL = "claude-sonnet-4-5"
OLLAMA_MODEL = "qwen3.5:4b"
EMBEDDING_MODEL = "nomic-embed-text"

# The services a model name can mean, spelled as they are on the wire. This tuple is the one
# place the list exists: the settings table offers it as a dropdown, ``_select`` branches on
# it, and ``llm._build`` builds one client per entry.
PROVIDERS = ("openrouter", "claude", "ollama")

# The key each remote provider needs. A provider not in here (Ollama) needs none, which is
# what makes "can this provider actually run" a single lookup rather than a chain of ifs.
PROVIDER_KEY_ENV = {"openrouter": "OPENROUTER_API_KEY", "claude": "ANTHROPIC_API_KEY"}

# The inverse, so a key field can say which provider it belongs to without a second table that
# could disagree with this one.
PROVIDER_BY_KEY_ENV = {env: name for name, env in PROVIDER_KEY_ENV.items()}

# How a provider is spelled in a sentence. The wire names are lower-case because they are
# setting values; a message that says "Openrouter" reads as a typo, and `.capitalize()` cannot
# fix it because the brand has a capital in the middle.
PROVIDER_LABELS = {"openrouter": "OpenRouter", "claude": "Claude", "ollama": "Ollama"}


def provider_label(name: str) -> str:
    """A provider's display name, falling back to the raw value for an unknown one."""
    return PROVIDER_LABELS.get(name, name)

# Each provider's default model, used when a provider is chosen but no name is given.
PROVIDER_DEFAULT_MODEL = {
    "openrouter": OPENROUTER_MODEL,
    "claude": ANTHROPIC_MODEL,
    "ollama": OLLAMA_MODEL,
}


@dataclass(frozen=True)
class ModelSetting:
    """One setting a client may send, and the environment name it stands in for.

    ``key`` is the wire name the front end uses; ``env`` is the environment variable the CLI
    uses. Both name the same thing, so the table is what stops the two surfaces drifting into
    different vocabulary for one setting - and it is the list the API validates a request
    against, so a name not in it can never become configuration.

    ``choices`` turns a box into a dropdown. It exists because a provider is one of three
    known values, and a free-text box for it would make a typo look like a backend failure.
    """

    key: str
    env: str
    label: str
    help: str
    secret: bool = False
    choices: tuple[str, ...] | None = None
    # Which card the page puts this field in. Kept here rather than in the page so the table
    # stays the one description of a setting: a field added here appears in a familiar place
    # instead of wherever the front end happened to stop rendering.
    group: str = "Models"


# The settings a browser may supply, in display order. The provider sits above its model
# because it is what the model name *means*: a name alone cannot say which service serves it,
# and inferring from the presence of a slash was wrong - an Ollama model may be a Hugging Face
# repo, ``hf.co/mradermacher/RollMind-v1-gemma3-12b-GGUF:Q4_K_M``.
MODEL_SETTINGS: tuple[ModelSetting, ...] = (
    ModelSetting(
        key="reasoning_provider",
        env="LLM_PROVIDER",
        label="Reasoning provider",
        help=(
            "Which service serves the reasoning model. A model name alone cannot say: an "
            "Ollama model may be a Hugging Face repo id, which also contains slashes."
        ),
        choices=PROVIDERS,
    ),
    ModelSetting(
        key="reasoning_model",
        env="LLM_MODEL",
        label="Reasoning model",
        help="Writes the book recommendations, as the provider above names it.",
    ),
    ModelSetting(
        key="fast_provider",
        env="LLM_PROVIDER_FAST",
        label="Fast provider",
        help="Which service serves the fast model. Unset follows the reasoning provider.",
        choices=PROVIDERS,
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
        help="Needed only by a model whose provider is OpenRouter.",
        secret=True,
        group="API keys",
    ),
    ModelSetting(
        key="anthropic_api_key",
        env="ANTHROPIC_API_KEY",
        label="Anthropic API key",
        help="Needed only by a model whose provider is Claude.",
        secret=True,
        group="API keys",
    ),
    ModelSetting(
        key="ollama_model",
        env="OLLAMA_MODEL",
        label="Local Ollama fallback",
        help=(
            "Used when a chosen provider cannot run - a remote model with no key, or a client "
            "that failed to construct - and as the model when nothing else is set."
        ),
        group="Fallback",
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

    A short value masks to a bare ellipsis, which is deliberately indistinguishable from the
    "nothing here worth showing" case - and that collides with a real bug worth a guard.
    """
    if not value:
        return None
    if len(value) <= 8:
        return "…"
    return f"{value[:4]}…{value[-4:]}"


# What a well-formed key looks like, per provider. Not a validity check - only the provider can
# answer that - but enough to reject a value that cannot possibly be one, which is what turns a
# confusing remote 401 into a sentence naming the box that is wrong.
KEY_PREFIXES = {"openrouter": "sk-or-", "claude": "sk-ant-"}

# A provider key shorter than this cannot be real. The shortest genuine-looking key is far
# longer, so a mask (``…``), a placeholder (``changeme``) or a paste that lost most of itself is
# caught here rather than by the provider with a message about an authentication header.
MIN_KEY_LENGTH = 16


def key_problem(name: str, value: str | None) -> str | None:
    """Why ``value`` cannot be a usable key for provider ``name``, or ``None`` if it looks fine.

    This exists because of a real failure that was nearly impossible to diagnose from the
    message it produced. ``ChatOpenAI`` raises only when a key is *absent*; a key of ``"…"`` -
    the mask this very module returns - builds a client happily, sends an ``Authorization``
    header OpenRouter rejects, and the error the user sees is *"Missing Authentication
    header"*. That reads like a bug in the code rather than like a bad key, and the mask is
    the one value the page could plausibly have sent.

    Deliberately a *shape* test, not a validity test: a wrong-but-well-formed key still has to
    reach the provider, because only the provider knows whether it is real. The point is to
    catch values that cannot be a key at all, while they can still be described precisely.
    """
    expected = KEY_PREFIXES.get(name)
    text = (value or "").strip()
    if not text:
        return (
            f"The {provider_label(name)} provider needs an API key and none is set. Add one on "
            f"the Settings tab, or switch the provider to Ollama to run locally."
        )
    if text == "…" or "…" in text:
        # The mask, or something copied out of the settings page's own preview.
        return (
            f"The {provider_label(name)} API key looks like the masked preview this app shows "
            f"('{text}'), not a real key. Enter the full key on the Settings tab - the page "
            f"never displays it in full, so it has to be pasted from the provider."
        )
    if len(text) < MIN_KEY_LENGTH:
        return (
            f"The {provider_label(name)} API key is too short to be real ({len(text)} characters). "
            f"Paste the whole key on the Settings tab."
        )
    if expected and not text.startswith(expected):
        return (
            f"The {provider_label(name)} API key should start with '{expected}' but starts with "
            f"'{text[:6]}'. Check it was not mixed up with another provider's key."
        )
    return None


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


def provider(env=None, key: str = "LLM_PROVIDER") -> str | None:
    """The provider named by ``key``, or ``None`` when the environment names none.

    ``None`` is a real answer here, distinct from ``"ollama"``: it means "the environment has
    no opinion", which is what lets the default be decided by which key is present rather
    than by an arbitrary choice of provider. An unrecognised value is reported and treated as
    absent, because a typo must not silently become a different service.
    """
    env = os.environ if env is None else env
    raw = _clean(env.get(key)).lower()
    if not raw:
        return None
    if raw not in PROVIDERS:
        logging.warning(
            f"{key}='{raw}' is not one of {', '.join(PROVIDERS)}; ignoring it."
        )
        return None
    return raw


def provider_key_env(name: str) -> str | None:
    """The environment variable holding the key ``name`` needs, or ``None`` for a local one."""
    return PROVIDER_KEY_ENV.get(name)


def _select(requested_provider: str | None, requested_model: str,
            env, *, label: str) -> tuple[str, str]:
    """Resolve one provider/model pair, honouring an explicit provider when there is one.

    The explicit provider is authoritative because the name cannot be: an Ollama model may be
    a Hugging Face repo id (``hf.co/…/…:Q4_K_M``) and so contains slashes, which is exactly
    what the old name-based inference read as an OpenRouter id - so it sent a local model to a
    remote service and failed there with a message about the API key.

    With no provider given, the name is still read the old way, because the CLI and a
    hand-written ``.env`` rely on it and one setting is easier to explain than two.
    """
    if requested_provider == "ollama":
        return "ollama", requested_model or _clean(env.get("OLLAMA_MODEL")) or OLLAMA_MODEL

    if requested_provider:
        key_env = PROVIDER_KEY_ENV[requested_provider]
        key = _clean(env.get(key_env))
        model = requested_model or PROVIDER_DEFAULT_MODEL[requested_provider]
        # The *shape* of the key, not only its presence. A key of ``"…"`` - which is the mask
        # this module returns - passes a presence check, builds a client, and comes back from
        # OpenRouter as "Missing Authentication header": a message that reads like a code bug
        # rather than a bad key. See ``key_problem``.
        problem = key_problem(requested_provider, key)
        if problem is None:
            return requested_provider, model
        # A remote provider whose key cannot work cannot answer at all, so falling back is the
        # only thing left - and it is logged, because silently swapping models makes a bad key
        # look like a backend failure.
        fallback = _clean(env.get("OLLAMA_MODEL")) or OLLAMA_MODEL
        logging.warning(
            f"{label} is set to provider '{requested_provider}' but {key_env} is unusable: "
            f"{problem} Using Ollama '{fallback}'."
        )
        return "ollama", fallback

    # No provider: infer from the name, as before.
    if requested_model:
        if "/" in requested_model:
            if _clean(env.get("OPENROUTER_API_KEY")):
                return "openrouter", requested_model
            fallback = _clean(env.get("OLLAMA_MODEL")) or OLLAMA_MODEL
            logging.warning(
                f"{label}='{requested_model}' looks like an OpenRouter model but "
                f"OPENROUTER_API_KEY is not set; using Ollama '{fallback}'."
            )
            return "ollama", fallback
        return "ollama", requested_model

    fallback = _clean(env.get("OLLAMA_MODEL")) or OLLAMA_MODEL
    return ("openrouter", OPENROUTER_MODEL) if _clean(env.get("OPENROUTER_API_KEY")) \
        else ("ollama", fallback)


def select_model(env=None) -> tuple[str, str]:
    """Return ``(provider, model)`` for the reasoning model.

    ``LLM_PROVIDER`` + ``LLM_MODEL`` name it. The provider is what the model name *means*, and
    it is a setting of its own rather than something inferred from the name, because the name
    cannot carry it: OpenRouter ids are ``vendor/model``, but so are Hugging Face Ollama models
    (``hf.co/mradermacher/RollMind-v1-…:Q4_K_M``), and reading a slash as "remote" sent a local
    model to OpenRouter.

    With ``LLM_PROVIDER`` unset the old name-based inference still applies, so an existing
    ``.env`` or CLI one-liner keeps working:

      nothing set              -> OpenRouter if a key is present, else Ollama
      LLM_MODEL=deepseek/x     -> OpenRouter
      LLM_MODEL=qwen3.5:4b     -> Ollama, even when an OpenRouter key is present
      LLM_PROVIDER=ollama      -> Ollama, whatever the name looks like

    A remote provider with no key has nothing to fall back to but Ollama, so that is reported
    rather than silently swapped.
    """
    env = os.environ if env is None else env
    return _select(
        provider(env, "LLM_PROVIDER"), _clean(env.get("LLM_MODEL")), env,
        label="LLM_MODEL",
    )


def select_fast_model(env=None) -> tuple[str, str]:
    """Return ``(provider, model)`` for the small, fast model.

    ``LLM_MODEL_FAST`` is a second, independent setting rather than a modifier on
    ``LLM_MODEL``, because the two do different jobs: the main model writes a whole
    recommendation and is worth waiting for, while the fast one answers a one-line
    question about a spell and is not. Pointing it at a smaller model is the point.

    Unset means "no separate fast model", and the main model is used instead - so the
    setting is optional and a project without it behaves exactly as before. Its provider is
    independently settable through ``LLM_PROVIDER_FAST`` and falls back to the reasoning
    provider, because the common case is one service for both.
    """
    env = os.environ if env is None else env
    requested_model = _clean(env.get("LLM_MODEL_FAST"))
    requested_provider = provider(env, "LLM_PROVIDER_FAST")
    if not requested_model and not requested_provider:
        return select_model(env)

    return _select(
        requested_provider or provider(env, "LLM_PROVIDER"),
        requested_model, env, label="LLM_MODEL_FAST",
    )


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
