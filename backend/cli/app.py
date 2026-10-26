"""CLI entry point: argument parsing, startup, and clean shutdown.

Thin by design. It resolves the character, starts the corpus watcher, hands the REPL a
configured ``SpellbookService`` and unwinds cleanly on Ctrl+C or SIGTERM.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from backend.libs import config, indexing, service, watching
from backend.libs.characters import CharacterNotFound, load_character_data
from backend.libs.indexing import IndexUnavailable
from backend.libs.service import SpellbookService

from .shell import SpellbookShell


def parse_args(argv=None):
    """Parse CLI flags for choosing the character sheet."""
    parser = argparse.ArgumentParser(
        prog="what-spellbook",
        description="Tome Warlock spellbook generator.",
    )
    parser.add_argument(
        "--character",
        metavar="NAME",
        help=(
            f"Character sheet stem in {config.CHARACTERS_DIR} "
            f"(default: ${'CHARACTER'} or '{config.DEFAULT_CHARACTER}')."
        ),
    )
    parser.add_argument(
        "--refresh",
        "--no-cache",
        dest="refresh",
        action="store_true",
        help="Ignore any cached books and regenerate every scenario.",
    )
    parser.add_argument(
        "--no-progress",
        dest="progress",
        action="store_false",
        default=True,
        help="Disable the stage progress display (implied when output is piped).",
    )
    return parser.parse_args(argv)


def _exit_on_sigterm(signum, frame):
    """Translate SIGTERM into Ctrl+C so both stop the shell the same way."""
    raise KeyboardInterrupt


def main(argv=None) -> int:
    """Start the watcher and REPL, shutting both down cleanly on Ctrl+C."""
    args = parse_args(argv)
    # Precedence: --character flag, then the CHARACTER env var, then the default sheet.
    character_name = args.character or os.getenv("CHARACTER", config.DEFAULT_CHARACTER)

    try:
        sheet = load_character_data(character_name)
    except CharacterNotFound as e:
        logging.critical(str(e))
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        index = indexing.ensure_db()
    except IndexUnavailable as e:
        logging.critical(str(e))
        print(f"error: {e}", file=sys.stderr)
        return 1

    # SIGTERM has no default KeyboardInterrupt, so map it explicitly (e.g. for a
    # container stop).
    signal.signal(signal.SIGTERM, _exit_on_sigterm)

    observer, _thread = watching.start_in_background(config.resolve(config.DOCS_DIR))

    try:
        spellbook = SpellbookShell(
            service.SpellbookService(
                index, sheet, db_version=config.INDEX_VERSION, refresh=args.refresh
            ),
            show_progress=args.progress,
        )
        print(f"Character sheet: {character_name}")
        spellbook.cmdloop()
    except KeyboardInterrupt:
        # Ctrl+C escapes cmdloop's internal input() loop, so unwind here instead.
        print()
        logging.info("Interrupted by user.")
    finally:
        watching.stop_observer(observer)
        logging.info("Goodbye, Warlock.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
