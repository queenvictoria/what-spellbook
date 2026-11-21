# Spellbook Recommendation System - Roadmap

## Project Overview

A spell recommender for Dungeons & Dragons 5.5e (2024) players. Given a scenario, a
character sheet and a ruleset, it retrieves the spells that character can legally cast
and asks a model to compose them into _books_ - small, self-contained sets of picks with
advice for using them.

The system is built as a Python core with two front ends: a terminal REPL and an HTTP
API driving a browser UI. Both call the same `backend.libs.service` layer, so a rule lives in
one place.

## TODO

- [x] Switch to /slash+TAB style commands like Claude CLI and Discord
- Add /test command
- [x] Add /help command
- [x] Move character/s to JSON/YAML file in `data/characters`
- [x] Filter retrieval by what the character can legally prepare
- [x] Ground prompts in `context/` rules files
- [x] Move remaining config to .env file (`CHARACTER` and `LLM_MODEL` are wired; paths are not)
- [x] Cache input, context, and responses so we can learn from the previous outputs
- [x] Reuse the cache when the character and scenario are unchanged
- [x] Rate a generated book after the scenario is played
- [ ] Report on rating patterns once enough books are rated
      — **the data is now there**: 44 of the 97 stored book files carry a rating, so the
      "once enough books are rated" precondition is met. Nothing aggregates them yet; the
      only reader is `/history`, which prints a per-run score.
- [x] Add a character importer and switcher — the Character screen lists YAML sheets from
      `GET /api/characters`, imports validated sheets into `data/characters/`, and remembers
      the selected filename stem in this browser so recommendations and history use it.
      D&D Beyond PDFs are parsed into an editable YAML preview before the sheet is saved.
- [ ] Add /character command to switch characters — `/character` exists but _asks about_ the
      loaded sheet (`/c perception`); nothing switches which sheet is loaded. The API already
      has `GET /api/characters` and `service_for(name)`, so the seam is there.
- [x] Refactor `main.py` and supporting files into a proper class/module structure so it can power both the CLI and a front end via an API. Pulled the CLI functions out into their own layer and noted the design in AGENTS/ROADMAP.
- [x] Expand the CLI to have progress meter like Claude: fetching spells from Grimoire, crafting prompt, scribing Books of Shadow. When printing markdown to the console please format it rather than raw markdown. Bold, italics, headings could be coloured.
- [x] Add a command to ask anything about a character: rule clarification, reason why they have two spells the same, how their stats are being boosted. Could extend to simple retrieval of a roll eg: /c perception (should return a number from a character sheet) or /? short rest (looks up the rules online and caches the answer).
- [x] Build the React/Vite/Tailwind/shadcn front end
- [x] Create the backend API
- [x] The rules lookup button should be an icon and shouldn't wrap the text.
- [x] Each mention of a spell should open the rules tab and display the spell from the vendored repo
- [x] Read books should look like a button with a carat
- [ ] Restructure the book prompt: fold the item pairings into each book, make the
      invocations one run-level line, promote the gotchas into their own block. Section 4
      is ~38% of all prose and its invocation half repeats identically in every book.
      — **partly done**: `=== PAIRINGS ===` is now one run-level section outside the books
      (`prompts._book_template`), so the invocation half no longer repeats per book. The
      pairings are still run-level rather than folded into each book, and there is no
      gotchas block.
- [x] when the read books is open it should show all the content--so grid is probably the wrong thing to do .. Use flex and flex wrap probably and the open one should be full width.
- [x] Opening in the scenario screen should show the results as well as the prompt.
- [x] When reading a book open clicked local context spell descriptions in a pull out drawer.Keep the original link so that CTRL CLICK still opens in a new tab but add an onclick handler to trigger the drawer (for local links).
- [x] The pull out drawer of spells should have a search box at the top to search all spells.
- [x] Spells display parsing: Expand Components to their full meaning (V, S, D, M), add Damage (if any) to the description at the top next to Casting time, add icons to duration, casting time, damage, components, range.
- [x] Asking a question in the rules search like "explain the initiative system to me like I'm 12yo" should respond with a generative answer based on the rules if it can't find a precise rule not "The 2024 SRD has no section matching 'explain the initiative system to me like I'm 12yo'. The SRD covers the core rules, not every option in the Player's Handbook."
- [x] Highlighting a piece of text should bring up a contextual window with search in it. Search should use RAG to find out what the selected text means in context of the game.
- [x] Percentage (in timing) shouldn't stop at 99% if the process is running longer.
- [ ] When showing spells or other information contextualise it to the current character: "Goodbye, Warlock" should be "Goodbye Louis", "Eldritch blast" should show "2 beams (L5)". Use a small fast model for contextualising rules to levels.
      — **the spell half is done**: `spellstats.scaling()` + `SpellSchema.scaling` render
      "2 beams (L5)" on the card, cached per character and level. The greeting is still
      hard-coded (`cli/app.py` logs "Goodbye, Warlock.").
- [x] When you press the "read books" button it flashes some other text briefly (Open something) and then flips back only changing the caret. It should say something like "hide books".
- [ ] We have 'Fetching spells from [the] Grimoire' in multiple places. It should be a const or enum.
      — **half done**: `timing.PHASE_LABELS` is the single source for the phase names and
      `service` emits those strings, but `cli/render.py` still defines its own
      `STAGE_FETCH`/`STAGE_PROMPT`/`STAGE_SCRIBE`/`STAGE_REFINE` constants that nothing
      imports. Delete them and read `timing.PHASE_LABELS`.
- [x] Switch to Lucide icons
- [ ] When switching "tabs" keep the running processes going. eg Scenario planning, question asking. Update the tabs with progress meters.
- [ ] Let's write evals for the scenario planning
- [x] Reduce duplication in the display of books: in the scenario view book, title, and spells are all duplicated
- [x] Replace the model's prose book format with explicit `=== BOOK n ===` sections, so splitting a book no longer relies on heuristics. This also removes the spurious extra "books" the trailing summary produced (`**Book 3 pairs with:**` was read as a fourth book and recited inside the last one).
- [ ] Clean out the runs stored in the old prose format, and delete the legacy parser and the front end's `withoutBookHeader`/`reasoningOnly` once they are gone.
      — **blocked on data, not code**: 12 of the 16 stored runs in `.cache/` predate the
      `pairings` key, and `.cache/` is user data that must not be deleted. The legacy path
      stays until those runs are re-generated or deliberately retired.
- [x] In the book listing at the top both cantrips are in one lozenge and rituals in another. They should be in 5 separate lozenges with a label between the groups.
- [x] As we have a local copy of the rules list them out on the rules page
- [x] Rules list: enable a quick UI only search on titles.
- [x] Rules list: Then enable a vector search over the documents.
- [x] "Ask" box on the Rules tab should: filter rules by title, heading, subheading; search the text using vector search; and ask the question of the LLM. — the three run in parallel, each panel updating as it resolves. The filter matches headings client-side and opens the path to each match; the search is `GET /api/search`; the ask is unchanged.
- [ ] Provide a history search.
      — the Conversations subtab filters by _kind_ (ask/chat), which is a category, not a
      search. Neither subtab has a text box.
- [ ] Rules list: Context documents and attachments should be links to the rules.
      — **partly done**: citations and provenance paths are links (`RulePathLink`), and
      class-context mentions link (`ClassLink`). `AttachmentChips` still renders a bare
      name with no path, so an attached document cannot be opened from the chip.
- [ ] The context menu provided for the book should work for the character and the rules.
      — **the character half is done**: `CharacterScreen` wraps its sheet in
      `RulesContextDrawerProvider` + `SelectionWatcher`. The rules surfaces (`SrdCard`,
      `RulebookCard`, `SpellCard`, `RulesScreen`) have no selection watcher.
- [x] The context menu should support "ask" and "search".
- [x] Add licensing information to comply with 5.2.1 SRD
      — `backend/libs/licensing.py` holds the attribution, `GET /api/licensing` serves it,
      and `LicensingNotice` renders it as a footer in `App.tsx`. `NOTICE.md` is the
      long-form record and a test pins its sentence to the module's so the two cannot drift.
      Still open: no root `LICENSE` for _this project's own code_ — no licence has been
      chosen for it, which is a decision rather than a task.
- [x] Add licensing information for DnD-Character-Sheet-Helper
      — the same module and endpoint carry it, and `Source.present` is `ionas.available()`,
      so the notice appears only when the checkout is installed. A clone without it owes
      nothing and renders nothing.
- [ ] Add a UI for including and indexing new rulesets with dubious licensing at
      the discretion of the user. eg DnD-Character-Sheet-Helper. Or load your own
      markdown files and homebrew content
- [ ] Add a homebrew connector
- [x] Create user settings page with localstorage for API keys and models
      — the page is `frontend/app/screens/SettingsScreen.tsx` (Settings tab), and the models
      and key **are** in `localStorage`: the browser is the store of record. The server keeps
      nothing — `PUT /api/settings` holds what it is sent in memory for the life of the
      process so the model client can be built from it, and writes no file, because the key is
      a credential and a server-side copy is a liability nobody asked for. The page re-pushes
      on load, so a reload or a restart does not revert to the server's environment. One rule
      overrides the browser: a variable set when the server *started* is pinned and wins, and
      the page marks those fields so an edit that has no effect is explained. `.env` no longer
      sets any of the names. Each model carries an explicit **provider** (`openrouter`,
      `claude`, `ollama`) rather than inferring one from a slash in the name — Ollama models can
      be Hugging Face repo ids (`hf.co/mradermacher/RollMind-v1-…:Q4_K_M`) and have slashes too.
      Each remote provider has its own key field, a `key set` badge and a Clear button, and a
      save only sends the boxes that changed, so a second save no longer wipes the key.
- [ ] Add image upload for a character
- [ ] Add character importer and switcher
      — `GET /api/characters` and `service_for(name)` already exist and the UI never calls
      them; `api.characters()` is defined in the client and unused. Sheets are YAML in
      `data/characters/`, which is gitignored, so an importer writes to user data.
- [ ] Add another class that could use a loadout worker
- [x] Switch to websockets
      — `WS /api/stream` carries the five long operations (`scenario`, `refine`,
      `character`, `rules`, `selection`), multiplexed by request `id` on one shared socket.
      The HTTP routes are unchanged and remain the contract: the socket is a second
      transport over the same service methods and the same schemas, and the front end falls
      back to the route when the upgrade cannot be made.
      **The payoff is the progress.** The browser used to derive the stage from elapsed
      time, which showed "Scribing" while the server was still embedding; the stage is now
      the service's own `emit` message, bridged from the worker thread onto the event loop
      with `anyio.from_thread.run`. `timing.STAGE_KEYS` / `OPERATION_STAGES` is the one
      table tying the message the CLI prints to the key a browser switches on, and two tests
      pin it — one reading the real `emit(...)` calls out of `service.py`, one asserting no
      operation reports a stage it did not promise.
      `answering` (the model call) is now a reported stage in all four ask paths, so a panel
      cannot look finished while it is still waiting.
- [x] Stream LLM responses
      — the existing websocket now forwards provider chunks as `token` frames and the five
      long-operation panels render a throttled live Markdown draft. The service still
      assembles, parses and validates the complete response before the terminal `result`;
      cached replies and deterministic sheet lookups emit no tokens. A failed websocket
      handshake falls back to HTTP, but a mid-stream disconnect does not retry and spend a
      second model call.
- [ ] Test with fine tuned DND model like https://huggingface.co/ostamand/RollMind-v1-gemma3-12b ollama run hf.co/mradermacher/RollMind-v1-gemma3-12b-GGUF:Q4_K_M

## Technology Stack (as built)

| Component    | Decision                                              | Rationale                                                                                                 |
| ------------ | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Core         | Python 3.14 + `backend.libs.service.SpellbookService` | One implementation, two front ends                                                                        |
| CLI          | `cmd.Cmd` REPL + `rich`                               | `/slash` + TAB commands, formatted output, progress                                                       |
| API          | FastAPI + uvicorn                                     | Typed schemas, dependency injection, OpenAPI for free                                                     |
| Front end    | React + Vite + Tailwind v4 + shadcn-style components  | Fast dev loop, typed API client                                                                           |
| Vector store | ChromaDB (embedded, single collection)                | Local, no server; 544 spells, 22 items, the vendored SRD and the optional second rulebook as 4130 rows    |
| Embeddings   | Ollama (`nomic-embed-text`)                           | Local, free, no network dependency                                                                        |
| LLM          | OpenRouter or Ollama via `LLM_MODEL`                  | Swappable; the model is configuration, not architecture                                                   |
| Rules source | Vendored SRD 5.2.1 in `context/srd/`                  | Works offline, is diffable, is CC-BY-4.0 so it can be redistributed, and is indexed into the vector store |

Superseded choices, recorded so they are not reintroduced:

- **Client-side-only RAG with ChromaJS.** Planned before the retrieval logic existed; the
  two-stage retrieval now needs the spell pool, the rules validity check and the cache in
  one place, and a browser cannot hold the 544-document index cheaply.
- **GLM-4.7-flash.** Replaced by a configurable `LLM_MODEL`.
- **Zustand / SentenceTransformers.js.** Never used; React state and Ollama embeddings
  cover the same ground.

## Architecture

```
backend/libs/   rules, retrieval, prompting, caching, index, lookup, timing  (no printing)
backend/cli/    REPL, argument parsing, progress, markdown rendering
backend/api/    FastAPI routes and wire schemas
frontend/app/   React UI calling the API
```

The root is the monorepo: one Python package and one npm project side by side. There is no
`src/` - nothing here compiles, so it would only have meant a `sys.path` bootstrap.

Detailed notes are in [ARCHITECTURE.md](./ARCHITECTURE.md) and [AGENTS.md](./AGENTS.md).

## Done

### Core recommendation pipeline

- Two-stage retrieval: filter the 544 spells by what the character can legally cast, then
  rank the remainder against the scenario.
- Prompt construction with the character sheet, the rules context and the eligible pool.
- Book generation, with picks re-validated against the rules afterwards.

### Caching

- A run keyed by character, level, party, index version, **book count** and scenario hash.
  Repeating a scenario with unchanged inputs costs nothing.
- Context and inputs shared in `run.json`; one numbered file per book holding its text,
  picks and rating.
- `/history` lists runs, `/read` reopens one, `/rate` records an outcome.

### Timing

- Per-phase timings (retrieval / prompt / books) stored in `run.json`.
- Medians drive an ETA shown live in the CLI and the UI. The median is taken over the
  last few runs because a single rate-limited run poisons a naive estimate.

### Character and rules lookup

- `/c <question>` answers sheet facts exactly, with no model call, and defers anything
  explanatory to the model with the sheet in context.
- `/? <question>` retrieves from the 2024 SRD with heading-based matching, and reports an
  absent rule as absent rather than answering from memory. When no heading names the
  question, a similarity search over the indexed rulebook is the last resort, labelled
  `rules-inferred`.
- The vendored SRD is indexed alongside the spells, so the rulebook is searchable and the
  recommender is grounded in the rules a _scenario_ turns on. The Rules tab's index lane
  asks for `doc_type=all`, so a question like "how does cover work" is answered by the
  **Cover** rule as well as by spells that mention cover — the two are listed under separate
  headings, because a rule shown as a spell reads as a spell with its stats missing.

### Front ends

- CLI REPL with `/slash` + TAB completion, formatted markdown, and a live progress line.
- FastAPI backend with typed schemas and explicit error mapping.
- React UI: scenario, history, character, rules and settings screens.

### Tests

- 1307 pytest tests, including every API endpoint and error mapping.

## Next

### Recommendation quality

- **Restructure the book prompt.** Section 4 ("existing spells/features and invocations")
  is ~38% of all prose and the largest section, but measurement showed the problem is not
  duplication with "How to use" (crossover was only 1-7 names per run). It duplicates the
  character sheet instead - 29% of name mentions are repeats - and its invocation half is
  identical across every book in a run, because one numbered item mixes two scopes. Fold
  the pairings into each book, make invocations one run-level line, and promote the
  gotchas into their own visible block.
- Cap the number of pairings, so a book cannot spend half its length on item advice.

### Front end

- Streaming progress from the API, so the browser can show the real per-phase split rather
  than a heuristic derived from elapsed time.
- Book comparison view: two books side by side, for a scenario where the heuristics
  disagree.
- Rating trends: average score per spell, so a pick that keeps winning is visible.

### API

- Authentication and rate limiting before any non-local deployment.
- An endpoint for the eligible pool, so the UI can explain _why_ a spell was available.

### Testing

- A recorded-run fixture set, so the prompt and parsing can be tested without the model.

## Deliberately Not Doing

- **Server-side sessions.** The service is stateless between calls beyond the loaded sheet,
  and the cache is keyed on the request itself, so there is nothing to keep.
- **A database.** The cache is a directory tree; `run.json` and the book files are the
  schema, and they are readable without tooling.
- **A second retrieval path for the UI.** The API wraps the service, and the service is the
  only thing that talks to the index.

## Milestones

- [x] **Core pipeline**: retrieval, prompting, book generation, validation
- [x] **Caching and history**: repeat runs free, results reopenable and ratable
- [x] **CLI**: `/slash` commands, progress, formatted output
- [x] **API**: typed endpoints with explicit error mapping
- [x] **Front end**: scenario, history, character and rules screens
- [ ] **Recommendation quality**: restructure the book prompt
- [ ] **Deployment**: hosting and auth

## Resources

- [Architecture Documentation](./ARCHITECTURE.md)
- [Agent Schema](./AGENTS.md)
- [SRD 5.2.1 (PDF)](https://www.dndbeyond.com/srd) - the official document the vendored
  Markdown in `context/srd/` derives from. See `context/srd/PROVENANCE.md`.
- [React + Vite Docs](https://vitejs.dev/)
- [Tailwind v4 Docs](https://tailwindcss.com/docs)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [ChromaDB Docs](https://docs.trychroma.com/)
