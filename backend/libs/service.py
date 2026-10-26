"""The application layer: one object that performs a recommendation.

This is the seam between "how we talk to the user" and "how a book gets built". The
CLI drives it today; an HTTP handler could drive the same methods tomorrow without
touching retrieval, prompting or caching.

It owns no presentation: it returns dataclasses and raises typed errors, and never
prints, prompts or exits. Anything a caller might want to render (the answer, the
per-book breakdown, the legality warnings, whether the cache was used) is on the
returned value.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import cache, characters, config, llm, lookup, prompts, retrieval, rules, spells


@dataclass
class Book:
    """One generated Book of Shadows loadout."""

    index: int
    name: str
    text: str
    picks: dict[str, list[str]] = field(default_factory=dict)
    cache_path: str | None = None
    rating: dict | None = None

    @classmethod
    def from_cache(cls, entry: dict) -> Book:
        output = entry.get("output") or {}
        return cls(
            index=output.get("book_index", 0),
            name=output.get("book_name", "Untitled"),
            text=output.get("text", ""),
            picks=output.get("picks") or {},
            cache_path=entry.get("_path"),
            rating=entry.get("rating"),
        )


@dataclass
class Generation:
    """The result of a recommendation, whether it was generated or replayed.

    ``from_cache`` is what a caller uses to tell the user why the answer was instant.
    """

    scenario: str
    answer: str
    books: list[Book] = field(default_factory=list)
    prompt: str = ""
    warnings: list[str] = field(default_factory=list)
    from_cache: bool = False
    model: str | None = None
    pool: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    # The stored run's id, when there is one. A client needs it to rate a book: the
    # scenario text is not a reliable handle, because a run is keyed on the scenario
    # *and* the character, level and book count, so two runs can share a scenario.
    run_id: str | None = None

    @property
    def summary(self) -> str:
        """One line describing what happened, for a progress display."""
        if self.from_cache:
            return f"Loaded {len(self.books)} book(s) from the cache"
        return f"Scribed {len(self.books)} book(s)"


class Timer:
    """Wall-clock stopwatch for the named phases of a run.

    Phases are recorded rather than merely totalled so a slow run can be attributed:
    retrieval embeds the scenario locally, prompting is pure CPU, and the model call is
    network-bound remote work. They fail independently and want different fixes.

    Every phase is recorded even when it raises, so a failed run still says how far it
    got and where it died.
    """

    def __init__(self, clock=time.perf_counter):
        self._clock = clock
        self.phases: dict[str, float] = {}
        self._started = self._clock()

    @contextmanager
    def phase(self, name: str):
        start = self._clock()
        try:
            yield
        finally:
            self.phases[name] = round(self._clock() - start, 3)

    def measured(self) -> dict:
        """The timing payload stored with the run."""
        total = round(self._clock() - self._started, 3)
        return {
            "phases": dict(self.phases),
            "total_seconds": total,
            "unaccounted_seconds": round(
                max(0.0, total - sum(self.phases.values())), 3
            ),
        }


class NoEligibleSpells(RuntimeError):
    """Raised when the character's rules allow no book picks at all."""


@dataclass
class Answer:
    """A reply to a question about the character or the rules.

    ``source`` says where the answer came from so the UI can be honest about it: a
    ``sheet`` lookup is exact and instant, ``model`` is the LLM reasoning over the sheet,
    ``rules`` is grounded in fetched 2024 SRD text, and ``rules-inferred`` is an answer
    interpreted from related SRD text when no heading names the question. Showing a model's
    guess as though it were a sheet value is the failure this distinction exists to
    prevent, and an interpretation wearing a quotation's badge is the same failure.
    """

    question: str
    answer: str
    source: str
    # The sheet field the answer was quoted from. Named ``field_name`` rather than
    # ``field`` because a dataclass attribute called ``field`` shadows the ``field()``
    # helper inside the class body, which breaks the next default_factory.
    field_name: str | None = None
    citations: list[str] = field(default_factory=list)
    from_cache: bool = False


class CharacterNotLoaded(RuntimeError):
    """Raised when a character question is asked with no sheet loaded."""


class SpellbookService:
    """Builds book loadouts for one character against one vector index.

    Construct once per character/session; ``scenario()`` and ``refine()`` are the two
    entry points. The service is stateless between calls beyond the loaded sheet, so a
    future API can hold one per session and a test can hold one per case.
    """

    def __init__(self, vector_db, character: dict, *, db_version=None,
                 refresh=False, backend=None, context_dir=None, cache_dir=None,
                 books=None):
        self.db = vector_db
        self.character = character or {}
        self.character_text = characters.format_character(self.character)
        self.db_version = config.INDEX_VERSION if db_version is None else db_version
        self.refresh = refresh
        self.books = config.select_book_count() if books is None else books
        self.context_dir = context_dir or config.CONTEXT_DIR_PATH
        self.cache_dir = cache_dir or config.CACHE_DIR_PATH
        self.llm = backend if backend is not None else llm.build_llm()
        self.rule_context = (
            prompts.load_rule_context(self.character, self.context_dir) if self.character else ""
        )

    # --- keying ---

    def cache_key(self, scenario: str) -> dict:
        return cache.key_parts(
            character=characters.character_name(self.character),
            level=characters.character_level(self.character),
            party=characters.first_present(self.character, "Party", "party"),
            db_version=self.db_version,
            scenario=scenario,
            books=self.books,
        )

    def _cache_lookup_args(self, scenario: str) -> dict:
        return {
            "cache_dir": self.cache_dir,
            "character": characters.character_name(self.character),
            "level": characters.character_level(self.character),
            "party": characters.first_present(self.character, "Party", "party"),
            "db_version": self.db_version,
            "scenario": scenario,
            "character_fingerprint": cache.character_fingerprint(self.character),
            "book_count": self.books,
        }

    # --- public API ---

    def find_cached(self, scenario: str) -> Generation | None:
        """Return a previously generated run for these inputs, if there is one.

        Looked up before any work is done, so a repeat costs nothing: no embedding call
        for the ranking lane, no prompt assembly, no model call.
        """
        if self.refresh or not self.character:
            return None

        try:
            cached = cache.find_run(**self._cache_lookup_args(scenario))
        except OSError as e:
            # A broken cache must never block a fresh recommendation.
            logging.warning(f"Could not read the cache ({e}); regenerating.")
            return None
        if cached is None:
            return None

        run = cached["run"]
        books = [Book.from_cache(entry) for entry in cached["books"]]
        return Generation(
            scenario=scenario,
            answer=run.get("response", ""),
            books=books,
            prompt=(run.get("prompt") or {}).get("prompt", ""),
            from_cache=True,
            model=run.get("model"),
            pool=self._pool_from_context(run.get("context") or {}),
            # Replayed unchanged so a caller can show what the original run cost.
            timings=run.get("timings") or {},
            warnings=self.validate(run.get("response", ""), self._pool_from_context(
                run.get("context") or {})),
        )

    def scenario(self, scenario: str, progress=None) -> Generation:
        """Build three books for ``scenario``, or replay a cached run.

        Raises NoEligibleSpells when the character's rules allow no book picks, and
        llm.EmptyCompletion / llm.LLMUnavailable when the backend fails.
        """
        if not scenario.strip():
            raise ValueError("Please provide a scenario description.")

        cached = self.find_cached(scenario)
        if cached is not None:
            return cached

        emit = progress or (lambda _message: None)
        slot_level = characters.max_spell_level(self.character) if self.character else None
        timer = Timer()

        # Stage 1: the legal pool. Class, pact and subclass decide what can go in the
        # book; the scenario only ranks which legal candidates get their full text.
        emit("Fetching spells from the grimoire")
        with timer.phase("retrieval"):
            bucket = retrieval.gather_spell_candidates(
                self.db, character=self.character, query=scenario
            )
            if not bucket["cantrips"] and not bucket["rituals"]:
                raise NoEligibleSpells(
                    "There are no spells matching this character's eligibility rules."
                )

            pool_text = retrieval.format_pool(bucket, slot_level, character=self.character)
            spell_text = retrieval.format_full_text(bucket)

        if not self.rule_context:
            logging.warning(
                f"No rule context found under {self.context_dir}/; "
                "the model gets no rules grounding."
            )

        # Stage 2: the model ranks an already-legal pool, with rules and sheet in hand.
        emit("Crafting the prompt")
        with timer.phase("prompt"):
            full_prompt = prompts.full_prompt(
                character_text=self.character_text,
                rule_context=self.rule_context,
                scenario=scenario,
                pool_text=pool_text,
                spell_text=spell_text,
                books=self.books,
            )
            if warning := prompts.prompt_budget_warning(full_prompt):
                logging.warning(warning)

        emit("Scribing the Books of Shadows")
        with timer.phase("books"):
            answer = llm.invoke(self.llm, full_prompt)

        generation = Generation(
            scenario=scenario,
            answer=answer,
            prompt=full_prompt,
            books=self._split_books(answer),
            model=llm.model_name(self.llm),
            pool=bucket,
            timings=timer.measured(),
        )
        generation.warnings = self.validate(answer, bucket)
        self._persist(generation, bucket, pool_text)
        return generation

    def refine(self, question: str, previous: Generation | None, progress=None) -> Generation:
        """Answer a follow-up question about a previous answer."""
        if previous is None or not previous.answer:
            raise ValueError(
                "No books have been generated yet. Set a scenario first with /scenario."
            )
        if not question.strip():
            raise ValueError("Please provide a question.")

        emit = progress or (lambda _message: None)
        emit("Refining the current choices")
        prompt = prompts.refine_prompt(
            question=question,
            previous_response=previous.answer,
            scenario=previous.scenario,
            rule_context=self.rule_context,
            pool_text=retrieval.format_pool(
                previous.pool,
                characters.max_spell_level(self.character) if self.character else None,
                character=self.character,
            ) if previous.pool else "",
        )
        answer = llm.invoke(self.llm, prompt)
        return Generation(
            scenario=previous.scenario,
            answer=answer,
            prompt=prompt,
            books=self._split_books(answer),
            model=llm.model_name(self.llm),
            pool=previous.pool,
        )

    def ask_character(self, question: str, progress=None) -> Answer:
        """Answer a question about the character sheet: ``/c <question>``.

        Two-stage on purpose. A question whose answer is already a field on the sheet
        ("what's my passive perception?") is resolved by lookup, because a model adds
        latency and a chance of being wrong about a fact we hold verbatim. Anything else
        ("why do I have two Light spells?") is answered by the model *with the sheet in
        context*, so it is grounded rather than recalled.

        A duplicate-spell question is resolved by lookup too, since the sheet records
        which field granted each spell and that is the whole answer.
        """
        if not question.strip():
            raise ValueError("Please provide a question about your character.")
        if not self.character:
            raise CharacterNotLoaded("No character is loaded, so there is nothing to ask about.")

        # Duplicate spell: the sheet already names the granting fields.
        duplicate = re.match(
            r"\s*why\s+(?:do\s+i\s+)?(?:have\s+)?(?:\w+\s+){0,3}?(?:two|2|multiple|duplicate)"
            r"\s+(?P<spell>[A-Za-z' ]+?)(?:\s+spells?)?\s*\??\s*$",
            question, re.IGNORECASE,
        )
        if duplicate:
            name = duplicate.group("spell").strip()
            origins = lookup.spell_origins(self.character, name)
            if len(origins) > 1:
                return Answer(
                    question=question,
                    answer=(
                        f"You have {name} from {len(origins)} separate sources: "
                        + "; ".join(origins) + "."
                    ),
                    source="sheet",
                    field_name=", ".join(origins),
                )

        found = lookup.answer(question, self.character)
        if found is not None:
            return Answer(question=question, answer=found["answer"], source="sheet",
                          field_name=found.get("field"))

        emit = progress or (lambda _message: None)
        emit("Reading the character sheet")
        prompt = prompts.character_prompt(
            question=question,
            character_text=self.character_text,
            rule_context=self.rule_context,
        )
        return Answer(question=question, answer=llm.invoke(self.llm, prompt),
                      source="model")

    def ask_rules(self, question: str, progress=None) -> Answer:
        """Answer a rules question from the 2024 SRD: ``/? <question>``.

        Grounded in fetched text rather than model recall, because a rules answer is
        checkable and a wrong one silently corrupts a recommendation. Raises
        ``rules.RulesUnavailable`` when the SRD has no matching rule, which the caller
        reports rather than answering from memory.

        When no heading names the question, the answer is *interpreted* from the closest
        related text and labelled ``rules-inferred``. That label is the point: an answer
        assembled from surrounding prose is not a quotation, and letting it wear the
        ``rules`` badge would present an interpretation as a sourced rule.
        """
        if not question.strip():
            raise ValueError("Please provide a rules question.")

        emit = progress or (lambda _message: None)
        emit("Consulting the 2024 SRD")
        try:
            retrieved = rules.gather(question, cache_dir=self.cache_dir)
            source = "rules"
        except rules.RulesUnavailable:
            # No heading names the question. Fall back to the best related text, which
            # raises in turn when the SRD does not discuss the subject at all.
            retrieved = rules.gather_inferred(question, cache_dir=self.cache_dir)
            source = "rules-inferred"

        if retrieved["from_cache"] and (cached := rules.load_cached(question, self.cache_dir)):
            return Answer(question=question, answer=cached["answer"],
                          source=cached.get("answer_source") or source,
                          citations=[cached["url"]], from_cache=True)

        emit("Reading the rules")
        build = (prompts.rules_prompt if source == "rules"
                 else prompts.rules_inferred_prompt)
        prompt = build(
            question=question, rule_text=retrieved["text"], rule_context=self.rule_context,
        )
        answer = llm.invoke(self.llm, prompt)
        rules.save_cached(question, answer, passages=retrieved["passages"],
                          url=retrieved["url"], answer_source=source,
                          cache_dir=self.cache_dir)
        return Answer(question=question, answer=answer, source=source,
                      citations=[retrieved["url"]])

    def history(self) -> list[dict]:
        try:
            return cache.load_runs(self.cache_dir)
        except OSError as e:
            logging.warning(f"Could not read the cache ({e}).")
            return []

    def replay(self, reference: str) -> Generation | None:
        """Re-open a stored run by reference, so a past recommendation can be read.

        A run's books only make sense beside the scenario and sheet that produced them,
        so this returns a full ``Generation`` - the same shape a cache hit produces, and
        the same shape the REPL renders. Picks are re-validated against the current
        rules, because an entry may predate a change.

        Accepts a run directory, a ``run.json`` path, a scenario hash or a fragment of
        the scenario text.
        """
        try:
            directory = cache.find_run_dir(reference, self.cache_dir)
            if directory is None:
                return None
            stored = cache.load_run(directory)
        except OSError as e:
            logging.warning(f"Could not read the cache ({e}).")
            return None
        if stored is None:
            return None

        run = stored["run"]
        pool = self._pool_from_context(run.get("context") or {})
        answer = run.get("response", "")
        return Generation(
            run_id=Path(directory).name,
            scenario=(run.get("key") or {}).get("scenario_text", ""),
            answer=answer,
            books=[Book.from_cache(entry) for entry in stored["books"]],
            prompt=(run.get("prompt") or {}).get("prompt", ""),
            from_cache=True,
            model=run.get("model"),
            pool=pool,
            timings=run.get("timings") or {},
            warnings=self.validate(answer, pool),
        )

    def validate(self, answer: str, pool: dict) -> list[str]:
        """Check the answer's book picks against the eligible pool.

        The pool is filtered before the model sees it, and models still mis-file picks.
        The recurring real failure: a Celestial Warlock's always-prepared Guiding Bolt
        appears in the rules context, so the model puts it in a book where it is
        illegal. Re-run on cache hits too, since an entry may predate a rules change.
        """
        return spells.validate_book_picks(
            answer,
            pool.get("cantrips", []),
            pool.get("rituals", []),
            known=characters.known_spells(self.character),
        )

    # --- internals ---

    @staticmethod
    def _split_books(answer: str) -> list[Book]:
        return [
            Book(index=b["index"], name=b["name"], text=b["text"],
                 picks=cache.parse_picks(b["text"]))
            for b in cache.split_books(answer)
        ]

    @staticmethod
    def _pool_from_context(context: dict) -> dict:
        """Rebuild the pool shape from a cached run so picks can still be validated."""
        def spell(name, level, ritual):
            return spells.Spell(name=name, filename="", level=level, school="",
                                classes=(), is_ritual=ritual, is_spell=True)

        return {
            "cantrips": [spell(n, 0, False) for n in context.get("pool_cantrips", [])],
            "rituals": [spell(n, 1, True) for n in context.get("pool_rituals", [])],
            "ranked": [],
        }

    def _persist(self, generation: Generation, bucket: dict, pool_text: str) -> None:
        """Write the run so it can be replayed and rated. Never raises.

        Reported failures only: losing the cache must not lose an answer the user is
        about to read.
        """
        if not self.character:
            return
        try:
            written = cache.save_run(
                answer=generation.answer,
                cache_dir=self.cache_dir,
                character=characters.character_name(self.character),
                level=characters.character_level(self.character),
                party=characters.first_present(self.character, "Party", "party"),
                db_version=self.db_version,
                scenario=generation.scenario,
                input_data={"character_sheet": self.character},
                context={
                    "database_version": self.db_version,
                    "rule_context_files": prompts.context_files_for(self.character),
                    "pool_cantrips": [s.name for s in bucket.get("cantrips", [])],
                    "pool_rituals": [s.name for s in bucket.get("rituals", [])],
                    "pool_text": pool_text,
                },
                prompts={"prompt": generation.prompt},
                model=generation.model,
                character_fingerprint=cache.character_fingerprint(self.character),
                timings=generation.timings,
                book_count=self.books,
            )
        except OSError as e:
            logging.warning(f"Could not write the cache ({e}); the answer is unaffected.")
            return

        by_index = {b.index: b for b in generation.books}
        for path in written:
            if Path(path).name == cache.RUN_FILENAME:
                generation.run_id = Path(path).parent.name
                continue
            index = int(Path(path).name.split("-", 1)[0]) if Path(path).name[0].isdigit() else 0
            if index in by_index:
                by_index[index].cache_path = str(path)
        logging.info(f"Cached {len(generation.books)} book(s) under {written[0].parent}")
