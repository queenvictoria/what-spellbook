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
 (Chroma)    (YAML)    (context/)   (files)    (sheet)  (context/srd)
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
| `rules.py` | 2024 SRD retrieval for `/?` and spell descriptions: source guard, Markdown to text, heading matching, question cache |
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

**Only the vendored SRD**, in `context/srd/`. It is a copy of SRD 5.2.1 converted to
Markdown, redistributed under **CC-BY-4.0**, which explicitly permits copying and
redistribution with attribution. `context/srd/PROVENANCE.md` carries the required
attribution and the exact source.

Three guards are kept as real code rather than comments, because there are now two ways to
introduce the wrong rules - a URL and a file:

* `rules.check_source` refuses a known-wrong source before any text is read, so a 2014 file
  added by mistake fails loudly instead of answering silently.
* `rules.load_cached` rejects a cached answer whose `source` is not the vendored corpus.
* `test_rules.py` asserts both.

The edition guard is not pedantry. 5thsrd.org carries the **2014** rules, whose own banner
points at 5e24srd.com, and several warlock rules differ between editions: 2014 grants three
Eldritch Invocations and a free Pact of the Tome, while 2024 grants five invocations with
the Tome costing one. A recommendation built on the wrong edition is wrong in a way nobody
notices until the table.

### Why vendored files rather than the website

`/?` previously fetched from `5e24srd.com`. That site serves SRD 5.2 but **omits large
parts of it** - verified by crawling every page for headings. Short Rest, Long Rest, the
Grappled condition and the entire Rules Glossary were **absent**, and the pages that
remained cross-referenced the glossary for their definitions. So a rules answer drawn from
the website was systematically incomplete, and could not be fixed by crawling harder.

`context/srd/` removes that gap and the network dependency with it. Scraping is gone:
`html_to_text`, `fetch_page`, `candidate_pages` and `section_pages` no longer exist.

### How a question is matched

The matcher's contract is that **the answer is found under a heading that names it**. This
is what keeps a catalogue entry from answering a rule question, and it took several
measured corrections to make it true:

* Headings are promoted from Markdown `##`-`####`, from `<summary>` groups, and from
  run-in labels (`_Shove._ The target...`) - the last of which the SRD uses 240-odd times
  for the parts and cases of a rule.
* **Tables are converted, not stripped.** The rules genuinely live in them: the degrees of
  cover are a table, the actions are a table, and the surrounding prose only says "as
  detailed in the Cover table". Stripping the markup would leave a confident answer with
  the +2 and +5 bonuses missing.
* Terms are weighted by how many sections of the SRD contain them, so a heading match on a
  word the book uses everywhere ("creature", "spell") counts for almost nothing while one
  on a distinctive word ("cover", "shove") identifies the rule.
* A question is answerable only when the SRD has a heading naming its most distinctive
  term. Terms the SRD never uses weigh nothing, because treating absence as maximal rarity
  would turn "not found" into "found".

The SRD is still **not the whole 2024 rulebook** (no subclasses, few feats, neither
two-weapon fighting nor flanking), so a rule can legitimately be missing. When it is, the
honest outcome is to say so, which is why `/?` can return 404 and
why its prompt instructs the model to report the gap rather than guess.

### Spell descriptions

Every spell mention in the UI links to `/rules?spell=Name`, which is served by
`GET /api/spell`. The SRD is the authority and is searched first, but it carries only 339
spells while the retrieval corpus carries 517, and the difference is exactly the
supplements a Pact of the Tome Warlock leans on: Thorn Whip, Lightning Lure, Gust, Mold
Earth, Mind Sliver and Sapping Sting are all absent from the SRD. A link that 404s for the
cantrips the app itself just recommended is worse than no link, so `find_spell` falls back
to the corpus and the response's `source` says which one answered.

`GET /api/spells` returns the **union** of both sources, not the corpus alone. The SRD has
22 spells the corpus does not, and they are the 2024 generic renames of the 2014 branded
ones — the SRD's *Hideous Laughter* against the corpus's *Tasha's Hideous Laughter*,
*Floating Disk* against *Tenser's Floating Disk*. A model writing 2024 prose may use either
name, so offering only the corpus's names leaves the 2024 name as dead text. The SRD's
spelling wins where the two disagree, because that is what the lookup resolves to first.

Two things about the corpus are worth knowing before trusting a filename:

* **The page's title is the authority, not the filename.** Six files are named after a
  different spell than they contain — `Confusion.md` holds Conjure Animals — and
  `Meld Into Stone.md` capitalises a minor word the page does not. `spell_title` reads the
  first heading, so a lookup and a link agree with the text the reader is shown.
* **Names are never title-cased.** `title()` capitalises every word, so "Ray of Frost"
  became "Ray Of Frost" and 77 spells containing a minor word silently stopped matching the
  prose. It also breaks "Melf's Acid Arrow" into "Melf'S". The stems are already spelled
  correctly, so the only correct transformation is to undo the `_s` apostrophe escape and
  normalise the typographic apostrophe to the straight one the SRD uses.

The two sources describe the same thing in different dialects, and `normalise_corpus_spell`
rewrites the corpus's into the SRD's so one renderer handles both. The corpus's quirks are
not uniform, which is why the normaliser is measured against all 517 files rather than a
sample:

* Three title spellings - a markdown link, a bare `# Name`, and one indented tags line.
* 343 spells link rules terms inline (`[Concentration](https://...)`), 73 cross-reference
  another spell wiki-style (`[[Wall of Force]]`), and the wiki form must be unwrapped
  *first* or the markdown pattern matches the inner brackets and leaves the outer behind.
* Run-in labels are bolded as well as italicised, with the full stop inside the emphasis
  and a non-breaking space after it.
* 22 magic items - Glamerweave, Armblade, Docent - sit in the corpus's `Spells/` directory
  and are told apart by their stats line: a spell names a level or a cantrip, an item names
  a rarity.

The SRD side needs one conversion of its own: 13 spells carry their table inline as HTML,
and Confusion's entire behaviour table is one of them. `tables_to_text` renders them as
sentences, so the numbers survive and no markup reaches the reader.

### Eldritch Invocations

Invocations are a Warlock class feature, not spells, so they are looked up separately rather
than folded into `find_spell` — a class feature answering as if it were an SRD spell would
be a category error the caller could not see.

They come from the **Eldritch Invocation Options** section of the vendored
`context/srd/classes.md`, which is the only place their effect text exists. The section is
located by heading, because the chapter is 11,000 lines of class features and the
invocation names are not distinguishable from any other `####` heading without it.

Our own `context/classes/warlock/` is the fallback. It lists all 28 invocations with their
level and prerequisite but not what they do, so it can answer "may I take this?" and not
"what does it do?" — which is exactly why the class chapter was vendored. The response's
`source` says which one answered (`vendored-srd-5.2.1` or `class-context`), because the two
are not equally authoritative. The fallback's columns are located by header name rather
than position, since the pact files order them differently from the base class file, and a
table's `-` is read as "no value" rather than the literal string.

The response shape is a spell's, because the same card renders both. The names are added to
`GET /api/spells` because the books name invocations in the same sentence as spells —
"Agonizing Blast on Eldritch Blast" — and a mention that does not link is the same defect
either way. The front end tries `/api/spell` and falls back to `/api/invocation` on a 404,
so the list does not need to say which is which.

Vendoring the chapter widened what `/?` can answer — multiclassing and the wizard's
spellbook are rules the SRD carries that were previously refused as absent — and it
surfaced one false positive, now guarded. "how does a spear work" was answered with
"Eldritch Spear", because the Spear itself lives inside an equipment *table* with no
heading of its own, leaving the invocation as the only heading containing the word. A
heading qualified by a distinctive word the question never mentioned is now rejected, which
is a fourth condition on `_qualifies` alongside the three that were already there.

## Model and embedding configuration

`LLM_MODEL` selects the model; OpenRouter or a local Ollama endpoint is chosen by the
model name. Embeddings run locally through Ollama, so retrieval needs no network.

The model is configuration rather than architecture: nothing in the retrieval path
depends on which model answers, so changing it changes cost and quality, not behaviour.

## Testing

808 pytest tests. The two that carry the most weight:

- `test_service_imports_without_a_terminal` - guards the layering rule above.
- An API test per error mapping - a wrong status code is a contract bug the front end
  will hit, and testing the service directly cannot catch it.

Where a fake would otherwise hide the thing under test, the real path is kept.
`test_rules_answers_are_grounded_and_cached` stubs only the *model call* and runs real
retrieval, because the cache is downstream of retrieval - a stubbed retrieval would fake
the very thing the test exists to verify. An earlier version went further and stubbed the
file reader too; with a one-line stub corpus the term-frequency model the matcher ranks
headings with collapses, and the test began asserting a 404 instead of the answer.

Tests use `create_app(vector_db=FakeDB(), backend=FakeLLM())`, so routing, serialisation
and error mapping are all real while the index and the model are not.

---

*Last updated: 2026-10-26*
