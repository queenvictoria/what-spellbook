# Architecture

## Shape of the system

```
        ┌────────────────────┐          ┌────────────────────┐
        │  backend/cli/      │          │  frontend/app/     │
        │  the REPL          │          │  React UI          │
        └─────────┬──────────┘          └─────────┬──────────┘
                  │                                │ HTTP
                  │                                ▼
                  │                     ┌────────────────────┐
                  │                     │  backend/api/      │
                  │                     │  FastAPI           │
                  │                     └─────────┬──────────┘
                  └──────────────┬────────────────┘
                                 ▼
                    ┌─────────────────────────────┐
                    │  backend/libs/service.py    │
                    │  SpellbookService           │
                    └──────────────┬──────────────┘
                                   │
     ┌──────────┬──────────┬───────┴────┬──────────┬──────────┐
     ▼          ▼          ▼            ▼          ▼          ▼
 retrieval  characters  prompts      cache     lookup     rules
 (Chroma)    (YAML)    (context/)   (files)    (sheet)   (5e24srd)
```

The single rule this diagram encodes: **logic lives in `backend/libs/`, and only
`backend/libs/` talks to the index, the model or the disk.** The CLI and the API are both
transport, peers over the same service. A rule that lives in a route handler is a rule the
CLI does not have, and vice versa.

That is enforced by a test (`test_service_imports_without_a_terminal`) which asserts the
service imports without pulling in `cli` or `api`.

`backend/api` sits beside `backend/cli` rather than inside `backend/libs` because the
dependency direction is one-way: `api -> libs`, never the reverse. A package that may not
import its own parent would be a strange thing to write down.

## Layers

### `backend/libs/` - the core

| Module | Responsibility |
| --- | --- |
| `service.py` | `SpellbookService`: `scenario`, `refine`, `find_cached`, `replay`, `history`, `validate`, `ask_character`, `ask_rules`, plus `Timer`, `Generation`, `Book`, `Answer` |
| `retrieval.py` | Two-stage retrieval: filter the pool by what the character can legally cast, then rank against the scenario |
| `indexing.py` | The Chroma collection: build, open, version |
| `prompts.py` | Prompt construction for books, character questions and rules questions |
| `characters.py` | YAML sheet loading and rendering to prompt text |
| `cache.py` | The run cache: keys, layout, read/write, ratings |
| `lookup.py` | Deterministic sheet answers (`/c`) and duplicate-spell origins |
| `rules.py` | 2024 SRD retrieval for `/?`: host allow-list, HTML to text, heading matching, question cache |
| `timing.py` | Per-phase aggregation driving the ETA and the log summary |
| `spells.py`, `watching.py`, `llm.py`, `config.py` | Spell parsing, index staleness, model handle, environment |

Nothing here prints, prompts or exits. A failure is a typed exception:
`NoEligibleSpells`, `EmptyCompletion`, `LLMUnavailable`, `CharacterNotFound`,
`CharacterNotLoaded`, `RulesUnavailable`.

### `backend/cli/` - the terminal front end

`shell.py` is the REPL: `/scenario`, `/ask`, `/books`, `/rate`, `/history`, `/read`,
`/c`, `/?`, `/config`. `progress.py` owns the live progress line, `render.py` the
markdown-to-terminal formatting, `app.py` argument parsing.

`ALIASES` in `shell.py` maps short forms (`c` -> `character`, `?` -> `rules`) for both
dispatch and completion, so the two cannot drift apart.

### `backend/api/` - the HTTP front end

`backend/api/main.py` routes; `schemas.py` is the wire contract. No logic: each endpoint validates,
calls one service method, and maps the result or a typed error to a status code.

### `frontend/app/` - the browser front end

Hand-written typed client in `app/api/client.ts` mirroring `backend/api/schemas.py`.
Screens for scenario, history, character and rules.

The React source lives in `app/`, not `src/`. That is the Vite/Next convention for "the
web app", and it keeps the front end from being the only thing in the repo still using a
`src/` that means something different from what it meant before.

## Two decisions worth stating

### The cache key is a directory path

```
.cache/<character>/<level>-<party>-<dbversion>-<books>-<scenario hash>/
    run.json                    sheet, key, context, prompt, response, timings
    1-<book-name>.json          text, picks, rating
    2-<book-name>.json
```

The path *is* the key, so a lookup is a `stat` and there is no index to keep in sync.
`run.json` holds what is shared across the run; each book holds what belongs to it.

Consequences that have bitten before:

- **`books` must be in the key.** Without it, asking for 2 books would replay a stored
  3-book run and silently return 3.
- **An added optional field must not bump `SCHEMA_VERSION`.** Bumping it for `timings`
  invalidated a user's cached run and cost a fresh 40-second model call.
- **A rating belongs to the book *slot*, not the filename.** Regenerating renames books.
- **`.cache/` is user data.** It is git-ignored and never cleaned.

### Retrieval is two stages, not one

A single embedding query returns spells the character cannot cast - a level-9 spell is a
perfect semantic match for "stop the dragon" and completely illegal for a level-5
warlock. So:

1. **Filter** by rules: class list, level slots, pact boon, ritual access.
2. **Rank** what remains against the scenario.

Stage 1 is deterministic and cheap; stage 2 is where the model's judgement is used. This
keeps the model reasoning about *choice* rather than about *legality*, which it is bad at
and which the rules files already encode.

## Error mapping (API)

| Exception | Status | Meaning |
| --- | --- | --- |
| `ValueError` | 400 | Bad input the caller can fix |
| `CharacterNotFound` | 404 | No such character sheet |
| `rules.RulesUnavailable` | 404 | The 2024 SRD has no rule for the question |
| `CharacterNotLoaded` | 409 | The request needs a character and none is loaded |
| `NoEligibleSpells` | 422 | The character's rules allow no book picks |
| `llm.EmptyCompletion` | 502 | The model returned nothing |
| `llm.LLMUnavailable` | 503 | The model could not be reached |

4xx means "your request cannot work"; 5xx means "the server could not do it just now".
Retrying a 422 is pointless; retrying a 502 is not.

## Rules source policy

**Only 5e24srd.com.** `rules.check_host` refuses anything else before a request is made,
and `rules.load_cached` rejects a cached answer whose source is not that host.

This is not pedantry. 5thsrd.org carries the **2014** rules, whose own banner points at
5e24srd.com, and several warlock rules differ between editions: 2014 grants three
Eldritch Invocations and a free Pact of the Tome, while 2024 grants five invocations with
the Tome costing one. A recommendation built on the wrong edition is wrong in a way
nobody notices until the table.

The 2024 SRD is also **not the whole 2024 rulebook**. Verified by crawling every page:
Cover, Hiding, Difficult Terrain, Travel Pace and Dropping Prone have their own headings;
Short Rest, Long Rest, the Grappled condition and the Rules Glossary are **absent**. When
the rule is missing the honest outcome is to say so, which is why `/?` can return 404 and
why its prompt instructs the model to report the gap rather than guess.

## Model and embedding configuration

`LLM_MODEL` selects the model; OpenRouter or a local Ollama endpoint is chosen by the
model name. Embeddings run locally through Ollama, so retrieval needs no network.

The model is configuration rather than architecture: nothing in the retrieval path
depends on which model answers, so changing it changes cost and quality, not behaviour.

## Testing

657 pytest tests. The two that carry the most weight:

- `test_service_imports_without_a_terminal` - guards the layering rule above.
- An API test per error mapping - a wrong status code is a contract bug the front end
  will hit, and testing the service directly cannot catch it.

Where a fake would otherwise hide the thing under test, the real path is kept.
`test_rules_answers_are_grounded_and_cached` stubs `rules.fetch_page` rather than
`rules.gather`, because replacing `gather` would replace the cache lookup the test exists
to verify.

Tests use `create_app(vector_db=FakeDB(), backend=FakeLLM())`, so routing, serialisation
and error mapping are all real while the index and the model are not.

---

*Last updated: 2026-10-26*
