"""Settings: the store behind the settings page, and why the values live on the server.

The page edits four things - the reasoning model, the fast model, the OpenRouter key and the
local Ollama name - and every one of them is read *by the backend* when it builds a model
client. A browser copy would therefore be decorative: the value could be saved, shown and
even summarised back, and the next recommendation would still use whatever ``.env`` held.
Worse, the API key is the credential the *server* uses to call the provider, so putting it in
``localStorage`` would publish it to anything running on the page and send it back on every
request.

So the page is a form over this store: ``.settings.json`` at the repo root, layered between
``.env`` and the environment the process was launched with (see ``config.env_view``). The one
setting the browser does keep in ``localStorage`` is the API *base* address, because that has
to be known before a request can be made at all.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from . import config


class SettingsError(ValueError):
    """Raised when a proposed setting cannot be stored as given.

    A ``ValueError`` subclass because it is the caller's mistake - a model name with a space
    in it, an unknown field - which the API reports as a 400.
    """


class SettingsUnavailable(RuntimeError):
    """Raised when the settings file itself cannot be written.

    Separate from :class:`SettingsError` because it is not the caller's fault, and because a
    save that silently fails is the worst outcome a settings page can have: the user believes
    the value took. The API reports this as a 500 rather than a 400.
    """


@dataclass(frozen=True)
class Setting:
    """One editable setting, and the two names it goes by.

    ``key`` is the wire name the page and the API use; ``env`` is the environment variable it
    overlays, which is also the name stored in the file. One table rather than a translation
    at each boundary, because two mappings would eventually disagree about what was saved.
    """

    key: str
    env: str
    label: str
    help: str
    secret: bool = False


EDITABLE: tuple[Setting, ...] = (
    Setting(
        key="reasoning_model",
        env="LLM_MODEL",
        label="Reasoning model",
        help=(
            "Writes the book recommendations. A name containing a slash is an OpenRouter id "
            "(vendor/model); anything else is an Ollama model on this machine."
        ),
    ),
    Setting(
        key="fast_model",
        env="LLM_MODEL_FAST",
        label="Fast model",
        help=(
            "Answers the one-line questions, such as how a spell scales at the loaded level. "
            "Leave empty to use the reasoning model."
        ),
    ),
    Setting(
        key="api_key",
        env="OPENROUTER_API_KEY",
        label="OpenRouter API key",
        help=(
            "Needed by any model whose name contains a slash. Stored on the server and never "
            "sent to the browser."
        ),
        secret=True,
    ),
    Setting(
        key="ollama_model",
        env="OLLAMA_MODEL",
        label="Local Ollama model",
        help="Used when no OpenRouter key is set, or when the reasoning model names a local model.",
    ),
)

BY_KEY = {setting.key: setting for setting in EDITABLE}
BY_ENV = {setting.env: setting for setting in EDITABLE}

# A model id and a key are both short tokens, so these limits are not a policy - they are a
# guard against a paste that carries a newline or a whole document. Neither is usable
# downstream, and both would otherwise be stored happily and then fail at call time with a
# message that does not point back at the field.
MAX_SECRET = 512
MAX_MODEL = 200


def path() -> Path:
    """The settings file's location, read through config so a test can redirect it."""
    return Path(config.SETTINGS_FILE_PATH)


def load() -> dict[str, str]:
    """The saved settings, keyed by environment name, or ``{}`` when nothing is saved.

    **Never raises.** The file is user data, and a hand-edited one with a typo must not stop
    the app from starting - least of all now that this page exists so the values need not be
    edited by hand at all. An unreadable file is reported and treated as empty, which leaves
    the ``.env`` defaults in force and the app running.

    Deliberately not cached. The file is a few hundred bytes and is read when a model client
    is built rather than per request, so a cache would add only a way to serve a stale model
    after an edit.
    """
    location = path()
    try:
        raw = location.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        logging.warning(f"Could not read {location} ({e}); using .env values.")
        return {}

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as e:
        logging.warning(f"{location} is not valid JSON ({e}); using .env values.")
        return {}

    if not isinstance(payload, dict):
        logging.warning(f"{location} does not hold an object; using .env values.")
        return {}

    # Unknown keys are dropped rather than carried forward: they can only come from a
    # hand-edit, and preserving them would mean the next save kept a field nothing reads.
    saved = {}
    for env_name, value in payload.items():
        if env_name not in BY_ENV:
            logging.warning(f"Ignoring unknown setting {env_name!r} in {location}.")
            continue
        if isinstance(value, str) and value.strip():
            saved[env_name] = value.strip()
    return saved


def update(values: dict) -> dict[str, str]:
    """Merge ``values`` into the saved settings and return the result.

    ``values`` is keyed by the wire name (see :data:`EDITABLE`), because that is the
    vocabulary a request carries. Each entry is a string to set, or ``None``/``""`` to clear.

    A field that is **absent** is left alone, which is what lets a form that changed one box
    not wipe the other three; an empty string is a deliberate "forget this", which is a
    different statement and has to be expressible. That distinction is why the request model
    uses ``None`` for "unchanged" rather than defaulting to ``""``.

    Raises :class:`SettingsError` for input that cannot be stored, and the file is left
    exactly as it was - a rejected save must not half-apply.
    """
    if not isinstance(values, dict):
        raise SettingsError("Settings must be sent as an object.")

    unknown = [str(key) for key in values if key not in BY_KEY]
    if unknown:
        raise SettingsError(f"Unknown setting(s): {', '.join(sorted(unknown))}.")

    saved = load()
    for key, value in values.items():
        setting = BY_KEY[key]
        text = clean(value, setting=setting)
        if not text:
            saved.pop(setting.env, None)
            continue
        saved[setting.env] = _validate(setting, text)

    write(saved)
    return saved


def clear() -> None:
    """Delete the settings file, so every value falls back to ``.env`` and the defaults."""
    location = path()
    try:
        location.unlink()
    except FileNotFoundError:
        return
    except OSError as e:
        raise SettingsUnavailable(f"Could not delete {location}: {e}") from e


def mask(value: str | None) -> str | None:
    """A secret safe to send to a browser: enough to recognise, not enough to use.

    The point is that a user can tell *which* key is loaded - the two ends usually identify
    it - without the response becoming a way to read the secret back out. A short value is
    masked whole, because showing four characters of eight is most of it.
    """
    if not value:
        return None
    if len(value) <= 12:
        return "•" * 8
    return f"{value[:4]}…{value[-4:]}"


def clean(value, *, setting: Setting | None = None) -> str:
    """Normalise a submitted value; anything blank means "not set".

    Quotes are stripped because these are the same values ``.env`` holds, where a hand-edit
    commonly wraps a name in quotes - and a quoted name would otherwise be sent to the server
    verbatim.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        name = setting.label if setting else "value"
        raise SettingsError(f"{name} must be text, not {type(value).__name__}.")
    return value.strip().strip('"').strip("'").strip()


def _validate(setting: Setting, text: str) -> str:
    """Reject a value no backend could use, rather than storing it to fail later."""
    limit = MAX_SECRET if setting.secret else MAX_MODEL
    if len(text) > limit:
        raise SettingsError(
            f"{setting.label} is {len(text)} characters; the limit is {limit}."
        )
    if any(character in text for character in "\n\r\t"):
        raise SettingsError(f"{setting.label} cannot contain a line break or a tab.")
    if not setting.secret and any(character.isspace() for character in text):
        # A model id is one token: OpenRouter writes ``vendor/model`` and Ollama writes
        # ``name:tag``. A space means a sentence was pasted, and the failure at call time
        # ("no such model") would not point back at the field that caused it.
        raise SettingsError(f"{setting.label} cannot contain a space.")
    return text


def write(saved: dict[str, str]) -> None:
    """Write the settings atomically, so a crash cannot leave a half-written file.

    Written to a sibling and then renamed, because ``os.replace`` is atomic: a reader sees
    either the old file or the new one, never a truncated one. That matters more here than it
    looks - the reader is ``config.env_view`` while a model client is being built, so a torn
    file would mean silently falling back to ``.env`` for a whole run.
    """
    location = path()
    payload = {name: saved[name] for name in BY_ENV if name in saved}
    try:
        location.parent.mkdir(parents=True, exist_ok=True)
        temporary = location.with_name(location.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        # The file can hold an API key, so it is not world-readable. Best-effort: a filesystem
        # without POSIX permissions must not fail the save over this.
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, location)
    except OSError as e:
        raise SettingsUnavailable(f"Could not write {location}: {e}") from e
