"""The HTTP API: a transport layer over ``backend.service``.

Nothing here contains logic. Every endpoint validates its input, calls one service
method, and maps the result or a typed error to a status code. That is deliberate: the
service is shared with the CLI, so a rule that lives in a route handler would be a rule
the CLI does not have.

Error mapping is the main thing this layer owns:

===========================  ======  ============================================
Error                        Status  Meaning
===========================  ======  ============================================
``ValueError``               400     Bad input the caller can fix
``CharacterNotFound``        404     No such character sheet
``CharacterNotLoaded``       409     The request needs a character and none is loaded
``rules.RulesUnavailable``   404     The 2024 SRD has no rule for the question
``NoEligibleSpells``         422     The character's rules allow no book picks
``llm.EmptyCompletion``      502     The model returned nothing
``llm.LLMUnavailable``       503     The model could not be reached
===========================  ======  ============================================

The distinction that matters most: 4xx means "your request cannot work", 5xx means "the
server could not do it just now". Retrying a 422 is pointless; retrying a 502 is not.

Session model: one index load per process, one service per character. ``SpellbookService``
is stateless between calls beyond the loaded sheet, so it is created once at startup and
reused - loading the vector index per request would dominate the response time.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.libs import cache as cache_store
from backend.libs import characters, config, indexing, llm, rules, service, spells

from . import schemas


def _error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def _run_id(directory) -> str:
    """The directory name used as an opaque run id.

    The name is already ``<level>-<party>-<db>-<books>-<scenario hash>``, so it is
    unique within a character without a lookup table, and exposing it reveals nothing a
    caller cannot compute from the scenario it just sent.
    """
    return Path(directory).name


def _resolve_run(svc, reference: str) -> str:
    """Turn an opaque run id back into the directory ``replay`` expects.

    An id is only resolvable against the current cache, so a directory that has since
    been deleted falls through to ``replay`` as an ordinary unmatched reference. Any
    other reference - a scenario fragment, a hash, a path - is passed straight through
    so the CLI and the API accept exactly the same set of things.
    """
    for run in svc.history():
        if _run_id(run["directory"]) == reference:
            return run["directory"]
    return reference


def create_app(*, vector_db=None, backend=None, character_name=None,
               cache_dir=None) -> FastAPI:
    """Build the app, optionally around an injected index and model.

    Injection is what makes this testable: a test passes a fake index and a fake model
    and gets real routing, real serialisation and real error mapping without Ollama or
    OpenRouter. Without it every test would need the live index.
    """
    app = FastAPI(
        title="what-spellbook API",
        version="1.0.0",
        description=(
            "Spell recommendations and character lookups for a D&D 5.5e (2024) Warlock. "
            "The rules answers are grounded in the 2024 SRD only."
        ),
    )

    # The Vite dev server runs on a different origin, so the browser needs CORS. Scoped
    # to the dev origins rather than '*' so a deployment must make the choice explicitly.
    # The origins follow FRONTEND_PORT so a second dev server on another port works
    # without editing this file.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.dev_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    state = {
        "db": vector_db,
        "backend": backend,
        "character_name": character_name,
        "cache_dir": Path(cache_dir) if cache_dir is not None else config.CACHE_DIR_PATH,
        "services": {},
    }

    def get_db():
        """The vector index, loaded once per process."""
        if state["db"] is None:
            try:
                state["db"] = indexing.ensure_db()
            except indexing.IndexUnavailable as e:
                raise _error(503, f"The spell index is unavailable: {e}")
        return state["db"]

    def service_for(name: str | None) -> service.SpellbookService:
        """A service for one character, memoised so a sheet is read once."""
        wanted = name or state["character_name"] or config.DEFAULT_CHARACTER
        key = str(wanted)
        if key not in state["services"]:
            try:
                sheet = characters.load_character_data(wanted)
            except characters.CharacterNotFound as e:
                raise _error(404, str(e))
            state["services"][key] = service.SpellbookService(
                get_db(), sheet, backend=state["backend"], cache_dir=state["cache_dir"],
            )
        return state["services"][key]

    # --- health ---

    @app.get("/api/health", response_model=schemas.HealthSchema, tags=["meta"])
    def health():
        """Liveness plus the settings a client needs to describe the session."""
        try:
            svc = service_for(None)
            name = characters.character_name(svc.character)
            model = llm.model_name(svc.llm)
        except HTTPException:
            name, model = None, None
        return schemas.HealthSchema(
            status="ok", character=name, model=model,
            index_version=config.INDEX_VERSION, cache_dir=str(state["cache_dir"]),
        )

    # --- character ---

    @app.get("/api/character", response_model=schemas.CharacterSchema, tags=["character"])
    def get_character(name: str | None = Query(default=None)):
        """The loaded sheet, for the character screen."""
        svc = service_for(name)
        return schemas.CharacterSchema(
            name=characters.character_name(svc.character) or "unknown",
            sheet=svc.character,
            text=svc.character_text,
        )

    @app.get("/api/characters", response_model=list[str], tags=["character"])
    def list_characters():
        """Sheet names available on disk, for a character picker."""
        directory = config.resolve(config.CHARACTERS_DIR)
        return sorted(p.stem for p in directory.glob("*.yaml"))

    # --- generation ---

    @app.post("/api/scenario", response_model=schemas.GenerationSchema,
              tags=["generation"])
    def post_scenario(request: schemas.ScenarioRequest,
                      character: str | None = Query(default=None)):
        """Generate book loadouts for a scenario.

        Long-running: the model call dominates (tens of seconds). A client should show a
        progress state rather than assume a fast reply.
        """
        svc = service_for(character)
        try:
            generation = svc.scenario(request.scenario)
        except service.NoEligibleSpells as e:
            raise _error(422, str(e))
        except service.CharacterNotLoaded as e:
            raise _error(409, str(e))
        except llm.EmptyCompletion as e:
            raise _error(502, f"The model returned an empty response: {e}")
        except llm.LLMUnavailable as e:
            raise _error(503, f"The model could not be reached: {e}")
        except ValueError as e:
            raise _error(400, str(e))
        return schemas.GenerationSchema.from_generation(generation)

    @app.post("/api/ask", response_model=schemas.GenerationSchema, tags=["generation"])
    def post_ask(request: schemas.AskRequest,
                 scenario: str = Query(description="The scenario the question refines."),
                 character: str | None = Query(default=None)):
        """Answer a follow-up about a previous scenario's books.

        Takes the scenario rather than a session id, because the cache already keys on
        the scenario - so this works after a server restart with no session state.
        """
        svc = service_for(character)
        previous = svc.find_cached(scenario)
        if previous is None:
            raise _error(404, "No books are cached for that scenario; generate it first.")
        try:
            return schemas.GenerationSchema.from_generation(
                svc.refine(request.question, previous)
            )
        except llm.EmptyCompletion as e:
            raise _error(502, f"The model returned an empty response: {e}")
        except llm.LLMUnavailable as e:
            raise _error(503, f"The model could not be reached: {e}")
        except ValueError as e:
            raise _error(400, str(e))

    @app.get("/api/cached", response_model=schemas.GenerationSchema | None,
             tags=["generation"])
    def get_cached(scenario: str = Query(...), character: str | None = Query(default=None)):
        """The stored run for a scenario, or null. Lets a client avoid a duplicate run."""
        svc = service_for(character)
        generation = svc.find_cached(scenario)
        return schemas.GenerationSchema.from_generation(generation) if generation else None

    # --- history and reading ---

    @app.get("/api/history", response_model=list[schemas.RunSummary], tags=["history"])
    def get_history(character: str | None = Query(default=None)):
        """Every stored run, newest first. Runs, not books: a book is ambiguous alone.

        A run is identified by an opaque ``id``, never by its directory: a browser
        cannot use a server path, and publishing the cache layout is a leak with no
        upside. ``replay`` also still accepts a scenario fragment, so a caller can skip
        the listing when it already knows which scenario it wants.
        """
        svc = service_for(character)
        return [
            schemas.RunSummary(
                id=_run_id(run["directory"]), scenario=run["scenario"],
                character=run.get("character"), level=run.get("level"),
                created_at=run.get("created_at"), model=run.get("model"),
                book_count=run.get("book_count", 0),
                book_names=[n for n in run.get("book_names", []) if n],
                timings=schemas.TimingsSchema(
                    phases=(run.get("timings") or {}).get("phases") or {},
                    total_seconds=(run.get("timings") or {}).get("total_seconds"),
                ),
            )
            for run in svc.history()
        ]

    @app.get("/api/runs/{reference:path}", response_model=schemas.RunBooksSchema,
             tags=["history"])
    def get_run(reference: str, character: str | None = Query(default=None)):
        """Reopen a stored run by opaque id, scenario hash, directory or text fragment.

        Before this, the only way back into a result was a cache path on disk, which a
        browser cannot use.
        """
        svc = service_for(character)
        resolved = _resolve_run(svc, reference)
        try:
            generation = svc.replay(resolved)
        except OSError as e:
            raise _error(500, f"Could not read the cache: {e}")
        if generation is None:
            raise _error(404, f"No cached run matched '{reference}'.")

        directory = cache_store.find_run_dir(resolved, svc.cache_dir)
        stored = cache_store.load_run(directory) if directory else {}
        return schemas.RunBooksSchema(
            scenario=generation.scenario,
            created_at=(stored.get("run") or {}).get("created_at"),
            run_id=generation.run_id,
            books=[
                schemas.BookSchema(index=b.index, name=b.name, text=b.text,
                                   picks=b.picks or {}, cache_path=b.cache_path,
                                   rating=b.rating)
                for b in generation.books
            ],
        )

    @app.post("/api/runs/{reference:path}/rate", response_model=list[schemas.BookSchema],
              tags=["history"])
    def post_rate(reference: str, request: schemas.RateRequest,
                  character: str | None = Query(default=None)):
        """Record an outcome rating for one book, or every book in the run.

        A rating belongs to a book *slot*, so re-generating a scenario carries it
        forward. This is the data the project exists to collect: it records what was
        asked, what was suggested and how it actually went.
        """
        svc = service_for(character)
        generation = svc.replay(_resolve_run(svc, reference))
        if generation is None:
            raise _error(404, f"No cached run matched '{reference}'.")

        targets = _select_books(generation.books, request.book)
        if not targets:
            available = ", ".join(b.name for b in generation.books)
            raise _error(404, f"No book matched '{request.book}'. Available: {available}.")

        rated = []
        for book in targets:
            if not book.cache_path:
                continue
            try:
                entry = cache_store.rate(book.cache_path, score=request.score,
                                         notes=request.notes, outcome=request.outcome)
            except OSError as e:
                raise _error(500, f"Could not write the rating: {e}")
            output = entry.get("output") or {}
            rated.append(schemas.BookSchema(
                index=output.get("book_index", book.index),
                name=output.get("book_name", book.name),
                text=output.get("text", book.text),
                picks=output.get("picks") or {},
                cache_path=book.cache_path,
                rating=entry.get("rating"),
            ))
        return rated

    # --- questions ---

    @app.get("/api/character/ask", response_model=schemas.AnswerSchema,
             tags=["character"])
    def get_character_answer(question: str = Query(min_length=1),
                             character: str | None = Query(default=None)):
        """Ask about the character: the ``/c`` command.

        A sheet fact (``/c perception``) is answered exactly from the YAML with no model
        call, so it is instant and cannot be wrong. ``source`` says which happened.
        """
        svc = service_for(character)
        try:
            return schemas.AnswerSchema.from_answer(svc.ask_character(question))
        except service.CharacterNotLoaded as e:
            raise _error(409, str(e))
        except llm.EmptyCompletion as e:
            raise _error(502, f"The model returned an empty response: {e}")
        except llm.LLMUnavailable as e:
            raise _error(503, f"The model could not be reached: {e}")
        except ValueError as e:
            raise _error(400, str(e))

    @app.get("/api/rules", response_model=schemas.AnswerSchema, tags=["rules"])
    def get_rules_answer(question: str = Query(min_length=1),
                         character: str | None = Query(default=None)):
        """Ask a rules question: the ``/?`` command, grounded in the 2024 SRD.

        A 404 here means the SRD genuinely has no rule for the question - rests, the
        Rules Glossary and most conditions are not in it. That is reported rather than
        answered from the model's memory, which is how 2014 numbers leak into 2024
        answers.
        """
        svc = service_for(character)
        try:
            return schemas.AnswerSchema.from_answer(svc.ask_rules(question))
        except rules.RulesUnavailable as e:
            raise _error(404, str(e))
        except llm.EmptyCompletion as e:
            raise _error(502, f"The model returned an empty response: {e}")
        except llm.LLMUnavailable as e:
            raise _error(503, f"The model could not be reached: {e}")
        except ValueError as e:
            raise _error(400, str(e))

    @app.get("/api/spell", response_model=schemas.SpellSchema, tags=["rules"])
    def get_spell(name: str = Query(min_length=1,
                                    description="Spell name, e.g. Fireball")):
        """One spell's own text, quoted from a vendored file.

        Deterministic - no model is involved, so this cannot hallucinate a damage die. The
        SRD is tried first and the retrieval corpus second, because the SRD carries only
        339 of the corpus's 544 spells and the missing ones include cantrips the app
        recommends. A 404 therefore means neither source has it, which is a real miss
        rather than a branding difference.
        """
        spell = rules.find_spell(name)
        if spell is None:
            raise _error(
                404,
                f"No spell named '{name}' is in the 2024 SRD or the spell corpus. "
                "Check the spelling - the corpus uses the name as published, so "
                "\"Tenser's Floating Disk\" rather than \"Floating Disk\".",
            )
        return schemas.SpellSchema(**spell)

    @app.get("/api/spells", response_model=list[str], tags=["rules"])
    def spell_names():
        """Every spell name in the retrieval corpus, for linking prose to the SRD.

        Sent from the server rather than hard-coded in the front end so there is one
        authority on which names exist: the corpus is what the model may pick from, and a
        spell added to it should become linkable without editing the UI.
        """
        return spells.corpus_spell_names()

    @app.get("/api/sheet-keys", response_model=list[str], tags=["character"])
    def sheet_keys():
        """Every value ``/c`` can look up, for autocomplete and a help panel."""
        from backend.libs import lookup

        return lookup.sheet_keys()

    return app


def _select_books(books, reference: str | None):
    """Resolve a book reference the way the CLI does, so both behave identically."""
    if not reference:
        return list(books)
    needle = reference.strip().lower()
    if needle.isdigit():
        wanted = int(needle)
        return [b for b in books if b.index == wanted]
    exact = [b for b in books if b.name.lower() == needle]
    if exact:
        return exact
    return [b for b in books if needle in b.name.lower()]


app = None


def get_app() -> FastAPI:
    """The module-level app, built on first use.

    Deferred so importing this module never loads the vector index - a test that only
    wants the schemas should not pay for an index build, and ``uvicorn --reload``
    restarts would otherwise rebuild it on every edit.
    """
    global app
    if app is None:
        app = create_app()
    return app
