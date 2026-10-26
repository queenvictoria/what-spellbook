"""The interactive REPL.

This module owns presentation only: command parsing, TAB completion, progress and
formatting. Every piece of work goes through ``backend.service.SpellbookService``, so
the same operations are available to an API without a terminal.

`cmd.Cmd` carries two traps worth remembering, both handled here:
  * ``cmdloop()`` rebinds readline's completer after ``__init__``, so slash completion
    must be injected through the ``completenames`` hook.
  * readline treats ``/`` as a word delimiter by default, which routes TAB on ``/s`` to
    argument completion and bypasses ``completenames`` entirely, so it is removed.
"""

from __future__ import annotations

import cmd
import json
import logging
import re
from pathlib import Path

try:
    import readline
except ImportError:  # Windows has no readline; cmd merely loses TAB completion there.
    readline = None

from backend import cache as cache_store
from backend import characters, config, llm, service, timing

from . import progress as progress_mod
from . import render


class SpellbookShell(cmd.Cmd):
    # Bare command names; the '/' prefix is added by the REPL and TAB completion.
    COMMANDS = ("scenario", "ask", "read", "rate", "history", "exit")

    intro = (
        "\n🔮 Tome Warlock Spellbook Generator Initialised.\n"
        "Commands:\n"
        "  /scenario <text> - Set a new tactical scenario and generate books.\n"
        "  /ask <text>      - Ask a follow-up or refining question about the current books.\n"
        "  /read <n>        - Read a previous run's books (see /history).\n"
        "  /rate <n> [n]    - Rate generated books 1-5, optionally naming a book.\n"
        "  /history         - List previous runs, newest first.\n"
        "  /exit            - Close the session.\n"
        "Type '/' and press TAB to complete a command.\n"
    )
    prompt = "TomeWarlock> "

    def __init__(self, spellbook: service.SpellbookService, *, show_progress=True,
                 cache_dir=None, console=None):
        super().__init__()
        self.spellbook = spellbook
        self.last: service.Generation | None = None
        self.cache_dir = cache_dir or spellbook.cache_dir
        self.console = console
        self.progress = (
            progress_mod.StageProgress(
                console=console, estimates=self._stage_estimates()
            ) if show_progress
            else progress_mod.SilentProgress()
        )
        # Book references for the current answer -> their cache files, so /rate can
        # address a book without the user typing a path.
        self.book_files: dict[str, str] = {}
        # The listing /history last printed, so '/read 2' means the second row shown.
        self.history_runs: list[dict] = []
        # readline must treat '/' as word text, not a separator, or TAB on '/s'
        # would report text 's' at begidx 1 and skip completenames entirely.
        if readline is not None:
            delims = readline.get_completer_delims()
            if "/" in delims:
                readline.set_completer_delims(delims.replace("/", ""))

    @property
    def llm(self):
        """The backend in use, so it can be swapped without reaching into the service."""
        return self.spellbook.llm

    @llm.setter
    def llm(self, backend):
        self.spellbook.llm = backend

    @property
    def character(self):
        return self.spellbook.character

    @character.setter
    def character(self, sheet):
        self.spellbook.character = sheet

    @property
    def character_context(self):
        return self.spellbook.character_text

    @character_context.setter
    def character_context(self, text):
        self.spellbook.character_text = text

    @property
    def current_scenario(self):
        return self.last.scenario if self.last else ""

    @property
    def last_response(self):
        return self.last.answer if self.last else ""

    @property
    def last_prompt(self):
        return self.last.prompt if self.last else ""

    # --- cmd.Cmd hooks ---

    def _stage_estimates(self) -> dict[str, float]:
        """Map each progress stage message to its typical duration from past runs.

        Keyed by the exact stage text the service emits, so a renamed stage simply loses
        its estimate instead of showing the wrong one.
        """
        try:
            per_phase = timing.estimates(self.cache_dir)
        except OSError:
            return {}
        return {
            timing.PHASE_LABELS[phase]: seconds
            for phase, seconds in per_phase.items()
            if phase in timing.PHASE_LABELS
        }

    def _log_timing_summary(self):
        """Log how long this run took, and the typical profile across all runs."""
        measured = self.progress.report()
        if measured:
            logging.info(f"Scenario timings: {measured}")
        try:
            stats = timing.summary(self.cache_dir)
        except OSError:
            return
        if stats.get("samples", 0) > 1:
            logging.info(timing.format_summary(stats, prefix="Typical: "))

    def completenames(self, text, *ignored):
        """Offer '/<command>' for a leading-slash token, the bare command otherwise."""
        if text.startswith("/"):
            return [f"/{name} " for name in self.COMMANDS if f"/{name}".startswith(text)]
        return super().completenames(text, *ignored)

    def parseline(self, line):
        """Accept the '/command' form by dropping one leading slash.

        cmd only recognises identchars as the command token, so '/scenario ruin' would
        otherwise parse as an empty command and land in default().
        """
        stripped = line.lstrip()
        if stripped.startswith("/"):
            line = stripped[1:]
        return super().parseline(line)

    def do_help(self, arg):
        """Show the available commands: /help"""
        print(self.intro)

    def default(self, line):
        logging.error(
            f"Unknown command: '{line}'. Use '/scenario <text>', '/ask <text>', or '/exit'."
        )

    # --- commands ---

    def do_scenario(self, arg):
        """Submit a brand new tactical scenario: /scenario <description>"""
        try:
            with self.progress:
                generation = self.spellbook.scenario(arg, progress=self.progress)
        except ValueError as e:
            logging.error(str(e))
            return
        except service.NoEligibleSpells as e:
            print(str(e))
            return
        except llm.EmptyCompletion:
            logging.error(
                "The model returned an empty response. This usually means it used its "
                "entire token budget on internal reasoning, or the prompt exceeded the "
                "model's context window."
            )
            print(
                "The model returned an empty response. Try again, shorten the scenario, "
                "or use a larger model (OPENROUTER_API_KEY selects the OpenRouter backend)."
            )
            return
        except llm.LLMUnavailable as e:
            logging.error(f"LLM request failed: {e}")
            print(f"Request to the model failed: {e}")
            return

        self._log_timing_summary()
        self._show(generation)

    def do_ask(self, arg):
        """Ask a refining question about the last generated output: /ask <question>"""
        try:
            with self.progress:
                generation = self.spellbook.refine(arg, self.last, progress=self.progress)
        except ValueError as e:
            logging.error(str(e))
            return
        except llm.EmptyCompletion:
            logging.error("The model returned an empty response.")
            return
        except llm.LLMUnavailable as e:
            logging.error(f"LLM request failed: {e}")
            print(f"Request to the model failed: {e}")
            return

        self.last = generation
        render.render(generation.answer, self.console)

    def do_rate(self, arg):
        """Rate generated books 1-5: /rate <score> [book name or number]"""
        if not self.book_files:
            logging.error(
                "Nothing to rate yet. Generate books with '/scenario <text>' first, "
                "or use '/rate <score> <file>' to rate a cached file."
            )
            return

        match = re.match(r"\s*([1-5])\b\s*(.*)$", arg)
        if not match:
            logging.error(
                "Usage: /rate <1-5> [book name or number]. "
                f"Books available: {', '.join(sorted(self.book_files))}"
            )
            return

        score = int(match.group(1))
        target = match.group(2).strip()
        paths = self._resolve_books(target)
        if not paths:
            logging.error(
                f"No cached book matched '{target}'. "
                f"Available: {', '.join(sorted(self.book_files))}"
            )
            return

        for path in paths:
            try:
                entry = cache_store.rate(path, score=score)
            except OSError as e:
                logging.error(f"Could not rate {path}: {e}")
                continue
            name = (entry.get("output") or {}).get("book_name", Path(path).stem)
            print(f"Rated '{name}' {score}/5.")
            logging.info(f"Rated {path} {score}/5")

    def do_history(self, arg):
        """List previous runs (scenario + books) newest first: /history

        Lists *runs*, not books: a book is ambiguous on its own, and reading one means
        reading the scenario it was written for. Each entry is numbered so ``/read <n>``
        can reopen it without typing a path.
        """
        runs = self.spellbook.history()
        if not runs:
            print(f"No runs cached yet under {self.cache_dir}/.")
            print("Generate one with '/scenario <text>'.")
            return

        self.history_runs = runs
        shown = runs[:20]
        print(f"{len(runs)} cached run(s) under {self.cache_dir}/ (newest first):\n")
        for position, run in enumerate(shown, start=1):
            scores = [
                (entry.get("rating") or {}).get("score")
                for entry in cache_store.load_run(run["directory"])["books"]
            ]
            rated = [s for s in scores if s]
            mark = f"{sum(rated)/len(rated):.1f}/5" if rated else "unrated"
            scenario = " ".join((run.get("scenario") or "").split())
            if len(scenario) > 68:
                scenario = scenario[:65].rstrip() + "..."
            created = (run.get("created_at") or "")[:16].replace("T", " ")
            total = (run.get("timings") or {}).get("total_seconds")
            took = f"{total:.0f}s" if isinstance(total, (int, float)) else "-"

            print(f"  [{position:>2}] {created}  {run.get('book_count')} book(s)  "
                  f"{mark:>8}  {took:>5}")
            print(f"       {scenario}")
            if run.get("book_names"):
                names = ", ".join(n for n in run["book_names"] if n)
                if len(names) > 70:
                    names = names[:67].rstrip() + "..."
                print(f"       {names}")
        if len(runs) > len(shown):
            print(f"\n  ... and {len(runs) - len(shown)} more.")

        print("\nRead one with '/read <number>', e.g. '/read 1'.")

    def do_read(self, arg):
        """Open a previous run and print its books: /read <number|scenario|dir>

        After a restart the current answer is gone, so this is how a stored
        recommendation is read back. It reuses the same presentation as a fresh
        generation, so the books, the legality warnings and /rate all behave identically.
        """
        reference = arg.strip()
        if not reference:
            logging.error("Usage: /read <number|scenario fragment|run directory>. "
                          "Run '/history' to list what is available.")
            return

        reference = self._resolve_history_reference(reference)
        try:
            generation = self.spellbook.replay(reference)
        except OSError as e:
            logging.error(f"Could not read the cache: {e}")
            return

        if generation is None:
            logging.error(
                f"No cached run matched '{reference}'. Run '/history' to list them."
            )
            return

        self._show(generation)

    def _resolve_history_reference(self, reference: str) -> str:
        """Turn a number from the last /history listing into a run directory.

        Numbering is what makes /history usable: a cache path is long, and a scenario
        hash is meaningless to read.
        """
        if not reference.isdigit():
            return reference
        index = int(reference)
        if 1 <= index <= len(self.history_runs):
            return self.history_runs[index - 1]["directory"]
        # Nothing listed yet this session, so fall back to whichever run sorts there.
        runs = self.spellbook.history()
        if 1 <= index <= len(runs):
            return runs[index - 1]["directory"]
        return reference

    def do_exit(self, arg):
        """Exit the script cleanly."""
        return True

    def do_EOF(self, arg):
        """Exit on Ctrl+D, same as /exit."""
        print()
        return True

    # --- presentation ---

    def _show(self, generation: service.Generation):
        """Print an answer and re-point /rate at its book files."""
        self.last = generation
        self.book_files = {
            Path(b.cache_path).stem: b.cache_path
            for b in generation.books if b.cache_path
        }

        if generation.from_cache:
            render.banner(
                f"📖 Reusing the cached books for this scenario ({len(generation.books)} book(s)).\n"
                "   Drop the cache files, change the scenario, or pass --refresh to regenerate.",
                self.console,
            )

        logging.info("=" * 50)
        render.render(generation.answer, self.console)
        self._warn_about_illegal_picks(generation)
        logging.info("=" * 50)

    def _warn_about_illegal_picks(self, generation: service.Generation):
        """Report any book pick that is not actually eligible.

        The pool is filtered before the model sees it, but a model can still pull a
        name from the rules context (or invent one). Without this check a book that
        cannot legally be written would be presented as ready to use.
        """
        if not generation.warnings:
            return
        logging.warning(
            "Illegal book picks in the model's answer: " + "; ".join(generation.warnings)
        )
        render.warning("\n⚠️  Some picks are not legal for the Book of Shadows:", self.console)
        for problem in generation.warnings:
            print(f"   - {problem}")
        print("   Verify each pick against the eligible list above before using it.")

    def _resolve_books(self, target: str) -> list[str]:
        """Map a book reference to cache file paths.

        An empty target means 'all books from the current answer'.
        """
        if not target:
            return list(self.book_files.values())

        needle = target.lower()
        exact = [p for k, p in self.book_files.items() if k.lower() == needle]
        if exact:
            return exact
        # A plain number addresses the generated order ("/rate 4 2").
        numbered = [p for k, p in self.book_files.items() if k.startswith(f"{needle}-")]
        if numbered:
            return numbered
        return [p for k, p in self.book_files.items() if needle in k.lower()]


def build_shell(*, character_name=None, refresh=False, show_progress=True,
                db_version=None, vector_db=None, backend=None, context_dir=None,
                cache_dir=None, console=None) -> SpellbookShell:
    """Load a character and index, then return a ready shell.

    Kept separate from ``main()`` so a test can build a shell around a fake index and
    backend without a terminal.
    """
    from backend import indexing

    name = character_name or config.DEFAULT_CHARACTER
    sheet = characters.load_character_data(name)
    spellbook = service.SpellbookService(
        vector_db if vector_db is not None else indexing.ensure_db(),
        sheet,
        db_version=db_version,
        refresh=refresh,
        backend=backend,
        context_dir=context_dir,
        cache_dir=cache_dir,
    )
    return SpellbookShell(spellbook, show_progress=show_progress, console=console)
