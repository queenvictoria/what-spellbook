"""Compatibility shim.

The application now lives in ``src/``: rules, retrieval, prompting, caching and the
vector index in ``src/backend``; the terminal in ``src/cli``. This shim keeps
``python main.py`` and the existing ``main.<name>`` references working while pointing at
the real implementation.

New code should import the packages directly::

    from backend import service, characters, config
    from cli.app import main

Prefer ``python -m src.cli.app`` over ``python main.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `src/` importable so `from backend import ...` works however this is launched.
SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backend import cache as cache_store  # noqa: E402
from backend import characters, config, indexing, llm, prompts, spells, watching  # noqa: E402
from backend.cache import (  # noqa: E402,F401
    DEFAULT_CACHE_DIR,
    RUN_FILENAME,
    character_fingerprint,
    entry_dir,
    find_run,
    key_dir,
    key_parts,
    load_entries,
    parse_picks,
    save_run,
    scenario_fingerprint,
    split_books,
)
from backend.characters import (  # noqa: E402,F401
    APOSTROPHES,
    CURRENT_BOOK_FIELDS,
    KNOWN_SPELL_FIELDS,
    character_level,
    current_book_spells,
    format_character,
    known_spells,
    load_character,
    load_character_data,
    max_spell_level,
)
from backend.indexing import (  # noqa: E402,F401
    build_index,
    db_is_valid,
    ensure_db,
    get_embeddings,
    index_metadata,
    reset_db,
)
from backend.llm import build_llm  # noqa: E402,F401
from backend.retrieval import (  # noqa: E402,F401
    dedupe_by_spell,
    dedupe_spells,
    exhaustive_lane,
    format_already_have,
    format_full_text,
    format_pool,
    gather_spell_candidates,
    rank_book_candidates,
    retrieve,
)
from backend.watching import get_observer, start_watching, stop_observer, watch_thread  # noqa: E402,F401
from cli.app import main, parse_args  # noqa: E402,F401
from cli.shell import SpellbookShell  # noqa: E402,F401

# --- module-level aliases for the previous private names ---
_first_present = characters.first_present  # noqa: F401
_split_names = characters.split_names  # noqa: F401
_format_character = characters.format_character  # noqa: F401
_index_metadata = indexing.index_metadata  # noqa: F401
_db_is_valid = indexing.db_is_valid  # noqa: F401
_reset_db = indexing.reset_db  # noqa: F401
_reset_db_impl = indexing.reset_db  # noqa: F401
_build_index = indexing.build_index  # noqa: F401
_stop_observer = watching.stop_observer  # noqa: F401
_dedupe_by_spell = retrieval_dedupe = dedupe_by_spell  # noqa: F401
_dedupe_spells = dedupe_spells  # noqa: F401
_retrieve = retrieve  # noqa: F401
_exhaustive_lane = exhaustive_lane  # noqa: F401
_rank_book_candidates = rank_book_candidates  # noqa: F401
_format_pool = format_pool  # noqa: F401
_format_already_have = format_already_have  # noqa: F401
_format_full_text = format_full_text  # noqa: F401
_parse_args = parse_args  # noqa: F401
_exit_on_sigterm = __import__("cli.app", fromlist=["_exit_on_sigterm"])._exit_on_sigterm  # noqa: F401

# --- configuration mirror ---
DOCS_DIR = config.DOCS_DIR
DB_DIR = config.DB_DIR
INDEX_VERSION = config.INDEX_VERSION
RETRIEVAL_K = config.RETRIEVAL_K
FULL_TEXT_SPELLS = config.FULL_TEXT_SPELLS
CONTEXT_DIR = config.CONTEXT_DIR_PATH
CACHE_DIR = config.CACHE_DIR_PATH
CHARACTERS_DIR = config.CHARACTERS_DIR
DEFAULT_CHARACTER = config.DEFAULT_CHARACTER

# Re-exported so tests can keep referencing them through this module.
Document = indexing.Document

if __name__ == "__main__":
    raise SystemExit(main())
