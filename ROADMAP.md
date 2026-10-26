# Spellbook Recommendation System - Roadmap

## Project Overview

A spell recommender for Dungeons & Dragons 5.5e (2024) players. Given a scenario, a
character sheet and a ruleset, it retrieves the spells that character can legally cast
and asks a model to compose them into *books* - small, self-contained sets of picks with
advice for using them.

The system is built as a Python core with two front ends: a terminal REPL and an HTTP
API driving a browser UI. Both call the same `backend.libs.service` layer, so a rule lives in
one place.

## Technology Stack (as built)

| Component | Decision | Rationale |
|-----------|----------|-----------|
| Core | Python 3.14 + `backend.libs.service.SpellbookService` | One implementation, two front ends |
| CLI | `cmd.Cmd` REPL + `rich` | `/slash` + TAB commands, formatted output, progress |
| API | FastAPI + uvicorn | Typed schemas, dependency injection, OpenAPI for free |
| Front end | React + Vite + Tailwind v4 + shadcn-style components | Fast dev loop, typed API client |
| Vector store | ChromaDB (embedded, single collection) | Local, no server, 544 spells as chunks |
| Embeddings | Ollama (`nomic-embed-text`) | Local, free, no network dependency |
| LLM | OpenRouter or Ollama via `LLM_MODEL` | Swappable; the model is configuration, not architecture |
| Rules source | 5e24srd.com only | The 2014 SRD differs in ways that silently corrupt advice |

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
  absent rule as absent rather than answering from memory.

### Front ends
- CLI REPL with `/slash` + TAB completion, formatted markdown, and a live progress line.
- FastAPI backend with typed schemas and explicit error mapping.
- React UI: scenario, history, character and rules screens.

### Tests
- 657 pytest tests, including every API endpoint and error mapping.

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
- An endpoint for the eligible pool, so the UI can explain *why* a spell was available.

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
- [2024 SRD](https://5e24srd.com/) - the only rules source used
- [React + Vite Docs](https://vitejs.dev/)
- [Tailwind v4 Docs](https://tailwindcss.com/docs)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [ChromaDB Docs](https://docs.trychroma.com/)
