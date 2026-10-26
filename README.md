# What spellbook?

This project is designed to recommend spells to suit a scenario or encounter given a prompt and grounded in a ruleset and spell list.

The first proof-of-concept is for a D&D 5.5e (2024) Celestial Warlock with Pact of the Tome. Pact of the Tome enables rewriting of the spell-book after a short or long rest. And the class combo means spells can be selected from _any class_ if it has the [xxxx?] tag.

Given markdown (or similar) formatted spell lists, a character's level, and any other relevant information, and provided with a prompt (a scenario or encounter) it will recommend the cantrips and spells the new spellbook should contain, a rationale, and a cheatsheet of how to deploy them (possibly in combination with other prepared spells).

This project will store all settings in localstorage exportable to JSON and the cloud. The prompt and scenario history will be stored along with a rating from the player as to how well the recommendation performed (including an updated scenario or encounter prompt).

It will run as a webapp optimised for mobile. The interface should be minimal: character selection and storage, a history of scenarios, an editor for the character.

## Sources

5.5e SRD has 339 spells. DNDBeyond 400+ (includes legacy and trademarked spells).

https://github.com/downfallx/dnd-5e-srd-markdown/blob/master/spells.md
https://drive.google.com/drive/folders/16T2y1UaSgLQtEBWXmSU3zc0L7L6TKVT8
https://5e24srd.com/spells/spell-descriptions.html
https://toolsandtaverns.com/spells
https://dungeonmister.com/guides/classes-in-dungeons-dragons/celestial-warlock-dnd-2024-guide/
https://www.dndbeyond.com/classes/2190885-warlock#CelestialPatron

## Versions

### Front end

Framework: React + Vite
Status: not started. Planned in ARCHITECTURE and ROADMAP

### Backend

None as yet

### CLI

Framework: Python and langchain
Status: Backend/CLI split complete; API not built

Run it with:

```bash
python main.py                      # loads data/characters/lois.yaml
python -m src.cli.app               # same, without the shim
python main.py --character vax      # loads data/characters/vax.yaml
CHARACTER=vax python main.py        # same, via environment variable
python main.py --refresh            # ignore cached books, regenerate everything
```

Character sheets are plain YAML in `data/characters/<name>.yaml`; keys are
rendered as `Key: value` lines for the prompt, and list values are joined with
commas.

While it works, the CLI reports each stage and styles the answer:

```
... Fetching spells from the grimoire
    done: Fetching spells from the grimoire
... Crafting the prompt
    done: Crafting the prompt
... Scribing the Books of Shadows
    done: Scribing the Books of Shadows
```

Headings, bold and lists are rendered rather than shown as raw markdown, and the
styling is skipped automatically when output is redirected.

### Layout

```
src/backend/    rules, retrieval, prompting, caching, index, watcher
src/cli/        REPL, arguments, progress, markdown rendering
main.py         compatibility shim (re-exports the old names)
```

The rule that keeps the split honest: **`src/backend` never imports `src/cli`**, so the
same code can power an API. `backend.service.SpellbookService` is that seam — it does
the work and returns `Generation`/`Book` dataclasses, and never prints, prompts or exits.
The REPL just renders those objects; an HTTP handler could serialise the same ones
(`dataclasses.asdict()`). See `ROADMAP.md` for the remaining API work.

### How a recommendation is built

Two stages, deliberately separated:

```mermaid
flowchart LR
    A[Character sheet] --> C
    B[Scenario] --> D
    C[Eligibility filter<br/>class + pact + subclass] --> E[Legal pool<br/>cantrips + L1 rituals]
    E --> D
    D[Prompt builder] --> F[Model]
    G["context/ rules files"] --> D
    F --> H[3 book loadouts]
    H --> I{Book pick<br/>validation}
    I -->|legal| J[Cheatsheet]
    I -->|illegal| K[Warning to user]
```

**Stage 1 — build a legal pool.** What a character may prepare is a *rules*
question, so the scenario is never allowed to widen it. Books of Shadows take
exactly 3 cantrips and 2 level 1 rituals, so both lanes are fetched
**exhaustively** from indexed metadata rather than by similarity search — a
vector search cannot be trusted to return all 48 cantrips. Levelled spells are
excluded from the pool entirely: a Warlock's prepared list does not change on a
short rest, so offering them only invited the model to mis-file them as picks.

**Stage 2 — let the model rank.** The scenario ranks the shortlist (deciding
which spells get their full text included) and drives the tactical write-up.

**Rules grounding.** `context/` is laid out as `context/[class]/[pact|subclass]/`
and injected by prompt builders, not hard-coded:

| Context file | Applies to |
| --- | --- |
| `context/spells.md` | Every character (casting economy) |
| `context/classes/warlock/base.md` | Any Warlock |
| `context/classes/warlock/pact/tome.md` | Pact of the Tome |
| `context/classes/warlock/subclass/celestial.md` | Celestial Patron |

Context files hold **rules only** and never a character's name or level; the
sheet holds the character's values. Development learnings live in `AGENTS.md`.

**Book pick validation.** After the model answers, every entry in each book's
cantrip and ritual lists is checked against the eligible pool. Models reliably
mis-file spells that appear in the rules context but not the pool — a Celestial
Warlock's always-prepared `Guiding Bolt` is the recurring example — and a wrong
book is only discovered at the table.

**Spells the character already has.** A sheet spreads them across several fields,
so they are read as a union: Warlock picks, the patron's always-prepared list,
species and feat cantrips, and free casts. The book cannot duplicate anything the
character already has, so all of them are excluded from the pool and listed
explicitly in the prompt. The book's *current* loadout is deliberately **not**
excluded — the book is conjured fresh each rest, so re-picking remains legal.

### Result cache and ratings

A run is written to `.cache/` before it is printed, and a repeat of the same
scenario is then served straight from disk — no embedding call, no prompt
assembly, no model call:

```
.cache/
└── lois/
    └── 5-barbarian-fighter-druid-3-098f6d563801/
        ├── run.json                      # shared: sheet, context, prompt, response
        ├── 1-illuminated-kill-zone.json  # one book: its markdown, picks, rating
        ├── 2-ambush-breaker.json
        └── 3-bridge-hold-defense.json
```

The directory path _is_ the cache key: character, level, party, database version,
and a hash of the scenario. A rebuilt index (`INDEX_VERSION`) lands in a new
directory, so stale entries can never be mistaken for current ones.

**Shared inputs are stored once.** The prompt, sheet and pool are identical across
the three books, so they live in `run.json` rather than being copied into each book
(~47KB once instead of three times). **Each book gets its own file** because a book
is the unit of rating, so rating one never rewrites its siblings.

A hit requires the *whole* key plus a fingerprint of the character sheet, so editing
the sheet between runs regenerates instead of replaying advice for a character that
no longer exists. Cached answers are re-validated against the eligibility rules
rather than trusted, since an entry may predate a rules change. A partial directory
(a hand-deleted book) is treated as a miss, so you never see fewer books than the
model produced.

```json
// run.json — written once per run
{ "key": { "character": "lois", "level": 5, "party": "barbarian-fighter-druid",
           "db_version": 3, "scenario": "098f6d563801",
           "scenario_text": "We are ambushed crossing a narrow stone bridge at night.",
           "character_fingerprint": "1f3c…" },
  "prompt": { "prompt": "..." },
  "response": "...",
  "context": { "pool_cantrips": ["..."], "rule_context_files": ["spells.md"] } }

// 1-illuminated-kill-zone.json — one per book, the unit of rating
{ "run": "run.json",
  "output": { "book_index": 1, "book_name": "Illuminated Kill Zone",
              "picks": { "cantrips": ["Mind Sliver"], "rituals": ["Alarm"] } },
  "rating": { "score": null, "rated_at": null, "notes": null, "outcome": null } }
```

```bash
/rate 5                  # rate every book from the latest answer
/rate 4 bridge denial    # rate one book by name fragment
/history                 # list cached books and their ratings
python main.py --refresh # ignore the cache, regenerate every scenario
```

A rating is attached to a book _slot_ and carried across a regeneration, so a
`--refresh` that renames all three books does not discard the scoring you already
did. Because the prompt and response are stored alongside the rating, a rated book
is labelled training data: it records what was asked, what was suggested, and how
well it actually went.

Tests:

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers `/slash` command parsing and TAB completion, character sheet
loading, spell parsing and eligibility rules, prompt assembly, the retrieval
lanes, book-pick validation, the result cache, the service layer, and terminal
rendering/progress. It never builds a vector index, contacts a model, or touches
`data/chroma_db`; anything that writes is redirected to a temp directory.

Two tests guard the layering rather than the behaviour: one asserts `backend`
imports without `cli` (so an API stays possible), and one asserts the CLI turns a
missing character into an exit code (so the library stays exception-based).

- [x] Switch to /slash+TAB style commands like Claude CLI and Discord
- Add /test command
- [x] Add /help command
- [x] Move character/s to JSON/YAML file in `data/characters`
- [x] Filter retrieval by what the character can legally prepare
- [x] Ground prompts in `context/` rules files
- Move remaining config to .env file
- [x] Cache input, context, and responses so we can learn from the previous outputs
- [x] Reuse the cache when the character and scenario are unchanged
- [x] Rate a generated book after the scenario is played
- [ ] Report on rating patterns once enough books are rated
- [ ] Add /character command to switch characters
- [x] Refactor the python main.py and supporting files into the src/backend directory as a proper Class/module/OOP pattern so that it can power both the cli and a future front end via an API. Don't build the api but do keep your own notes about this in AGENTS and/or ROADMAP. Pull the cli functions out into their own file.
- [x] Expand the CLI to have progress meter like Claude: fetching spells from Grimoire, crafting prompt, scribing Books of Shadow. When printing markdown to the console please format it rather than raw markdown. Bold, italics, headings could be coloured.
- [ ] Add a command to ask anything about a character: rule clarification, reason why they have two spells the same, where the stats are being boosted. Could extend to simple retrieval of a roll eg: /c perception or /? short rest

LLM backend: OpenRouter (`deepseek/deepseek-v4.1-flash-1017`) via `OPENROUTER_API_KEY` in a gitignored `.env`, falling back to local Ollama (`qwen3.5:4b`) when no key is present.

Note: `qwen3.5:4b` is a _thinking_ model. It can spend its whole token budget on
internal reasoning and return an empty response, so the CLI reports an empty
completion as a failure rather than printing nothing. For local work a slightly
larger non-thinking model gives more reliable structured output.
