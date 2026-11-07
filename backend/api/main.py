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
from backend.libs import (
    characters,
    config,
    indexing,
    llm,
    rules,
    search,
    service,
    spellstats,
    spells,
    srd,
)

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


def _scaling_for(service_for, character: str | None, spell: dict) -> str | None:
    """The spell's note for ``character``, or ``None`` if it cannot be worked out.

    Best-effort on purpose. The note is an addition to a card whose text is read straight
    from a file, so a missing or unreadable sheet must not turn a working spell lookup into
    a 404 - the spell is still quotable, it just cannot be contextualised. That is the same
    bargain ``spell_scaling`` makes with a model failure.
    """
    try:
        return service_for(character).spell_scaling(spell)
    except HTTPException as e:
        logging.warning(f"No character for the spell note ({e.detail}); omitting it.")
        return None


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
                svc.refine(request.question, previous, thread_id=request.thread_id)
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
            preamble=generation.preamble,
            pairings=generation.pairings,
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

    # --- conversations ---

    @app.get("/api/conversations", response_model=list[schemas.ConversationSummary],
             tags=["conversations"])
    def get_conversations(kind: str | None = Query(default=None),
                          character: str | None = Query(default=None)):
        """Every stored ask/chat conversation, newest first.

        A conversation is a *thread*: the questions asked and the answers given, in order.
        Listed rather than the individual answers because a follow-up is only meaningful
        beside the question it followed - "and a grapple?" is not a question on its own.

        ``kind`` filters to one surface: ``rules`` (``/?``), ``character`` (``/c``),
        ``selection`` (the contextual menu) or ``refine`` (``/ask``).
        """
        svc = service_for(character)
        return [
            schemas.ConversationSummary.from_conversation(conversation)
            for conversation in svc.conversations(kind=kind)
        ]

    @app.get("/api/conversations/{reference:path}", response_model=schemas.ConversationSchema,
             tags=["conversations"])
    def get_conversation(reference: str, kind: str | None = Query(default=None),
                         character: str | None = Query(default=None)):
        """One stored conversation, every turn in order.

        ``reference`` is the thread's id, or a fragment of its opening question - so a
        caller that already knows what it wants can skip the listing.
        """
        svc = service_for(character)
        conversation = svc.conversation(reference, kind=kind)
        if conversation is None:
            raise _error(404, f"No stored conversation matched '{reference}'.")
        return schemas.ConversationSchema.from_conversation(conversation)

    # --- questions ---

    @app.get("/api/character/ask", response_model=schemas.AnswerSchema,
             tags=["character"])
    def get_character_answer(question: str = Query(min_length=1),
                             thread_id: str | None = Query(default=None),
                             character: str | None = Query(default=None)):
        """Ask about the character: the ``/c`` command.

        A sheet fact (``/c perception``) is answered exactly from the YAML with no model
        call, so it is instant and cannot be wrong. ``source`` says which happened.

        ``thread_id`` continues a stored conversation, so a follow-up is read in context.
        The answer carries the thread's id back, which is what a client passes next.
        """
        svc = service_for(character)
        try:
            return schemas.AnswerSchema.from_answer(
                svc.ask_character(question, thread_id=thread_id))
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
                         thread_id: str | None = Query(default=None),
                         character: str | None = Query(default=None)):
        """Ask a rules question: the ``/?`` command, grounded in the 2024 SRD.

        A 404 here means the SRD genuinely has no rule for the question - rests, the
        Rules Glossary and most conditions are not in it. That is reported rather than
        answered from the model's memory, which is how 2014 numbers leak into 2024
        answers.

        ``thread_id`` continues a stored conversation, so a follow-up is read in context.
        """
        svc = service_for(character)
        try:
            return schemas.AnswerSchema.from_answer(
                svc.ask_rules(question, thread_id=thread_id))
        except rules.RulesUnavailable as e:
            raise _error(404, str(e))
        except llm.EmptyCompletion as e:
            raise _error(502, f"The model returned an empty response: {e}")
        except llm.LLMUnavailable as e:
            raise _error(503, f"The model could not be reached: {e}")
        except ValueError as e:
            raise _error(400, str(e))

    @app.get("/api/rules/contextual", response_model=schemas.AnswerSchema, tags=["rules"])
    def get_rules_contextual(selected_text: str = Query(min_length=1,
                                                         description="Text selected from the book prose"),
                              context: str | None = Query(default=None,
                                                          description="The sentence the selection came from"),
                              document: list[str] | None = Query(default=None,
                                                                 description="A document attached to the selection, repeatable"),
                              thread_id: str | None = Query(default=None),
                              character: str | None = Query(default=None)):
        """Explain a phrase selected from a book's prose, grounded in the 2024 SRD.

        Three retrieval paths are tried in falling order of precision - a heading naming the
        selection, a heading naming its subject, and finally the selection's own words - so
        a fragment like "2 beams" is answered from the "Cantrip Upgrade" rule it came from
        rather than being refused for lacking a heading of its own. ``source`` says which
        path ran; ``rules`` is a quotation and ``rules-inferred`` is not.

        ``context`` is the sentence around the selection, and it reaches the prompt only.
        A fragment is ambiguous in the way its sentence resolves ("2 beams" could be any
        spell), but the selection is what was asked about, so the sentence never steers
        retrieval.

        ``document`` attaches a named rule - a spell or an invocation - to the selection, and
        may be repeated. This is what makes a book's sentence answerable: "Repelling Blast
        misses, so Thorn Whip pulls it" names two spells, and no retrieval over the
        *selection* can turn those names into their rules, because their descriptions are
        written in different words. Pass none and the mentions in the selection are resolved
        automatically; a selection whose documents cover it is answered from them even when
        the SRD has no rule of its own for the sentence.

        A 404 here means the SRD does not discuss the selection at all - a monster ability
        it does not carry, or a term like "flanking" that appears nowhere in 2024. That is
        reported rather than answered from the model's memory, which is how 2014 numbers
        leak into 2024 answers.
        """
        svc = service_for(character)
        try:
            return schemas.AnswerSchema.from_answer(
                svc.ask_rules_contextual(selected_text, context=context or "",
                                         attachments=document, thread_id=thread_id))
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
                                    description="Spell name, e.g. Fireball"),
                  character: str | None = Query(default=None)):
        """One spell's own text, quoted from a vendored file.

        Deterministic - no model is involved, so this cannot hallucinate a damage die. The
        SRD is tried first and the retrieval corpus second, because the SRD carries only
        339 of the corpus's 544 spells and the missing ones include cantrips the app
        recommends. A 404 therefore means neither source has it, which is a real miss
        rather than a branding difference.

        ``scaling`` is the one field that is *about* the loaded character rather than about
        the spell: "2 beams (L5)" for a level 5 Warlock's Eldritch Blast. It is read out of
        the spell's own text, so it is still a rule and not a guess - but it is this app's
        reading of the rule applied to a sheet, which is why it is a field of its own.
        """
        spell = rules.find_spell(name)
        if spell is None:
            raise _error(
                404,
                f"No spell named '{name}' is in the 2024 SRD or the spell corpus. "
                "Check the spelling - the corpus uses the name as published, so "
                "\"Tenser's Floating Disk\" rather than \"Floating Disk\".",
            )
        return schemas.SpellSchema(
            **spellstats.attach(spell),
            scaling=_scaling_for(service_for, character, spell),
        )

    @app.get("/api/invocation", response_model=schemas.SpellSchema, tags=["rules"])
    def get_invocation(name: str = Query(min_length=1,
                                         description="Invocation name, e.g. Agonizing Blast"),
                       character: str | None = Query(default=None)):
        """One Eldritch Invocation's rules, read from our own class context.

        A separate endpoint from ``/api/spell`` because an invocation is not a spell: the
        2024 SRD does not publish them at all, so the text comes from
        ``context/classes/warlock/`` and the response's ``source`` says so. Folding them
        into the spell lookup would make a class feature look like an SRD quote.

        The response shape is the same as a spell's, because the card that renders it is
        the same card - and that includes ``stats``, which comes back null here. An
        invocation has no Casting Time, Range or Duration, and the shared card must not
        offer it a strip of empty tiles implying it does.

        ``scaling`` is null for the same reason: an invocation's effect is not a value that
        changes with level, and the one that does - Eldritch Spear's range - states it as a
        formula over the Warlock's level rather than as a table.
        """
        invocation = rules.find_invocation(name)
        if invocation is None:
            raise _error(
                404,
                f"No Eldritch Invocation named '{name}' is in the class context. "
                "Check the spelling - the context uses the name as published, so "
                "\"Agonizing Blast\" rather than \"Agonizing\".",
            )
        return schemas.SpellSchema(
            **spellstats.attach(invocation),
            scaling=_scaling_for(service_for, character, invocation),
        )

    @app.get("/api/spells", response_model=list[str], tags=["rules"])
    def spell_names():
        """Every name the front end may link, for turning prose into links.

        Sent from the server rather than hard-coded in the front end so there is one
        authority on which names exist: a spell added to the corpus or the SRD should
        become linkable without editing the UI.

        This is the union of the corpus and the SRD, not the corpus alone. The SRD has 22
        spells the corpus does not - the 2024 generic renames of the 2014 branded ones,
        "Hideous Laughter" for "Tasha's Hideous Laughter" - and a model writing 2024 prose
        may use either name.

        Eldritch Invocations are included even though they are not spells, because the
        books name them in the same prose ("Agonizing Blast on Eldritch Blast") and a
        mention that does not link is the same defect either way. The front end resolves
        each name against ``/api/spell`` and falls back to ``/api/invocation``, so the
        list does not need to say which is which.
        """
        return sorted(set(rules.linkable_spell_names()) | set(rules.invocation_names()))

    @app.get("/api/sheet-keys", response_model=list[str], tags=["character"])
    def sheet_keys():
        """Every value ``/c`` can look up, for autocomplete and a help panel."""
        from backend.libs import lookup

        return lookup.sheet_keys()

    # --- index search ---

    @app.get("/api/search", response_model=schemas.SearchResultSchema, tags=["search"])
    def get_search(query: str = Query(default="",
                                      description="Text to search for. May be empty in text mode."),
                   mode: str = Query(default="vector",
                                     description="vector (similarity), text (substring), or hybrid"),
                   limit: int = Query(default=search.DEFAULT_LIMIT, ge=1,
                                      le=search.MAX_LIMIT),
                   offset: int = Query(default=0, ge=0),
                   class_name: list[str] | None = Query(default=None, alias="class",
                                                        description="Class list to require, repeatable"),
                   school: str | None = Query(default=None),
                   level_min: int | None = Query(default=None, ge=0, le=9),
                   level_max: int | None = Query(default=None, ge=0, le=9),
                   ritual: bool | None = Query(default=None),
                   spells_only: bool = Query(default=True),
                   doc_type: str | None = Query(
                       default=None,
                       description=("all, spell, item or srd. An explicit value wins over "
                                    "spells_only; omit it to leave the choice to spells_only"),
                   ),
                   all_terms: bool = Query(default=True,
                                           description="Text mode: require every word, not just one")):
        """Search the vector index directly, for inspection and testing.

        This is the diagnostic surface, not the recommender: it can return a spell the
        character could never pick, on purpose. ``retrieval`` answers "what is legal for
        this character"; this answers "what is in the index, and what does a query bring
        back", which is how a missing recommendation gets explained.

        Three modes, because they fail differently:

        * ``vector`` - a similarity search, i.e. what the recommender itself does. Needs
          text to embed; ``distance`` is Chroma's, lower being closer.
        * ``text`` - a substring scan over the chunk bodies, which is the only mode that
          can answer "which chunks mention X". Accepts an empty query to list everything
          the filters admit.
        * ``hybrid`` - the vector candidates re-ordered so hits containing the query's
          words come first. A ranking aid, not a retrieval algorithm: it cannot find a
          spell the embedding did not return.

        ``class`` is repeatable and matches any of the named classes. It is applied as an
        ``$or`` over the exact class-list strings the index stores, because the field is
        one comma-joined value and Chroma's ``$contains`` does not match inside it - see
        ``search._class_clause``.

        ``doc_type`` narrows to one kind of indexed text: ``all``, ``spell``, ``item`` or
        ``srd``. **An explicit value wins outright**, so ``doc_type=all`` returns the whole
        collection including the rulebook and the magic items - which is what a caller
        asking about a *rule* needs. Omitting it leaves the choice to ``spells_only``, whose
        default gives the recommender's view. The two are not combined: ``doc_type=all`` with
        the default ``spells_only=true`` used to resolve to spells only, so the value that
        reads as "everything" returned the narrowest set and silently defeated a rules
        search.

        A 400 means the request cannot work (an unknown mode, an inverted level range, a
        vector search with nothing to embed); an empty result is a normal answer.
        """
        try:
            result = search.search(
                get_db(), query, mode=mode, limit=limit, offset=offset,
                classes=class_name or (), school=school, level_min=level_min,
                level_max=level_max, ritual=ritual, spells_only=spells_only,
                all_terms=all_terms, doc_type=doc_type,
            )
        except ValueError as e:
            raise _error(400, str(e))
        return schemas.SearchResultSchema.from_result(result)

    @app.get("/api/search/facets", response_model=schemas.SearchFacetsResponse,
             tags=["search"])
    def get_search_facets():
        """Every class, school and level the index actually holds, with counts.

        Sent from the server rather than hard-coded in the front end so the filter values
        cannot drift from the corpus: a class added to the index becomes filterable with no
        UI edit, and a value that exists nowhere is never offered.
        """
        found = search.facets(get_db())
        return schemas.SearchFacetsResponse(
            index_version=config.INDEX_VERSION,
            facets=schemas.SearchFacetsSchema(
                classes=[schemas.SearchFacetSchema(value=f.value, count=f.count)
                         for f in found.classes],
                schools=[schemas.SearchFacetSchema(value=f.value, count=f.count)
                         for f in found.schools],
                levels=[schemas.SearchLevelFacetSchema(level=f.level, label=f.label,
                                                       count=f.count)
                        for f in found.levels],
                rituals=found.rituals, spells=found.spells, chunks=found.chunks,
                doc_types=[schemas.SearchFacetSchema(value=f.value, count=f.count)
                           for f in found.doc_types],
            ),
        )

    # --- browsing the vendored SRD ---

    @app.get("/api/srd", response_model=list[schemas.SrdDocumentSchema], tags=["rules"])
    def srd_documents():
        """Every vendored SRD file, with its headings nested.

        The table of contents for the Rules screen. Sent whole rather than per file because
        it is small - seven files, ~1280 headings, no text - and a client that had to ask
        seven times to draw one list would show it filling in.

        ``PROVENANCE.md`` is excluded by ``rules.source_files``: it is the CC-BY-4.0
        attribution, not SRD text, and listing it would offer licence boilerplate as a
        rule.
        """
        return [schemas.SrdDocumentSchema.from_document(d) for d in srd.documents()]

    @app.get("/api/srd/{name}", response_model=schemas.SrdSectionSchema, tags=["rules"])
    def srd_section(name: str,
                    slug: str | None = Query(default=None,
                                             description="Heading anchor; omit for the whole file")):
        """One section of one vendored SRD file, as renderable Markdown.

        Deterministic, like ``/api/spell``: the text is read from the file, so this cannot
        paraphrase a rule. HTML tables are converted to Markdown pipe tables on the way out
        - the numbers in a table *are* the rule, and ``### Cover``'s prose only says "as
        detailed in the Cover table".

        Omitting ``slug`` returns the whole document under its own title, which is what a
        click on the file name asks for. A 404 means the file or the heading does not
        exist, which is a real miss: the anchors are derived from the vendored text, so a
        stale link means the corpus changed.
        """
        try:
            if slug:
                return schemas.SrdSectionSchema.from_section(srd.section(name, slug))
            found = srd.document(name)
            return schemas.SrdSectionSchema(
                document=found.name, title=found.title, heading=found.title,
                slug="", path=found.path, text=srd.text(name),
            )
        except rules.RulesUnavailable as e:
            raise _error(404, str(e))

    # --- our own class context ---

    @app.get("/api/class-context",
              response_model=list[schemas.ClassContextFileSchema], tags=["rules"])
    def class_context_files():
        """Every class context file, class-wide rules first, then pacts, then patrons.

        These are the files spliced into a prompt as ``=== CHARACTER CONTEXT ===``, and
        they are listed so a reader can see what the answer was given. They are *not* SRD
        text: they are our own summary of a class, and the response says so through
        ``source``.

        Derived from the directory rather than listed in code, so a class added to
        ``context/classes/`` appears here without an edit - and a file that does not exist
        is never offered as a link.
        """
        return [
            schemas.ClassContextFileSchema(**found)
            for found in rules.class_context_index()
        ]

    @app.get("/api/class-context/{path:path}",
              response_model=schemas.ClassContextSchema, tags=["rules"])
    def class_context_file(path: str):
        """One class context file, as renderable Markdown.

        Deterministic, like ``/api/srd/{name}``: the text is read from the file, so this
        cannot paraphrase. A 404 means the file is not there, which is a real miss - the
        list above is derived from the same directory, so a stale link means the file was
        removed.

        The path is checked rather than trusted, because it arrives from a URL: anything
        resolving outside ``context/classes`` is refused, so this cannot be turned into a
        reader for the rest of the machine.
        """
        try:
            return schemas.ClassContextSchema.from_document(
                rules.class_context_document(path)
            )
        except rules.RulesUnavailable as e:
            raise _error(404, str(e))

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
