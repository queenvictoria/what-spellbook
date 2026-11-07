# What spellbook?

This project is designed to recommend spells to suit a scenario or encounter given a prompt and grounded in a ruleset and spell list.

The first proof-of-concept is for a D&D 5.5e (2024) Celestial Warlock with Pact of the Tome. Pact of the Tome enables rewriting of the spell-book after a short or long rest. And the class combo means spells can be selected from _any class_ if it has the [xxxx?] tag.

Given markdown (or similar) formatted spell lists, a character's level, and any other relevant information, and provided with a prompt (a scenario or encounter) it will recommend the cantrips and spells the new spellbook should contain, a rationale, and a cheatsheet of how to deploy them (possibly in combination with other prepared spells).

This project will store all settings in localstorage exportable to JSON and the cloud. The prompt and scenario history will be stored along with a rating from the player as to how well the recommendation performed (including an updated scenario or encounter prompt).

It will run as a webapp optimised for mobile. The interface should be minimal: character selection and storage, a history of scenarios, an editor for the character.

## Repository layout

A monorepo: one Python package and one npm project, side by side at the root.

```
backend/          the Python package
  libs/             rules, retrieval, prompting, caching - the domain, no printing
  cli/              the terminal front end
  api/              the HTTP front end
  __main__.py       `python -m backend` runs the CLI
frontend/         the npm project
  app/              the React source
context/          rules text injected into the model prompt
  srd/              the vendored 2024 SRD, also indexed into the vector store
data/             character sheets and the Chroma index (untracked)
tests/            pytest
```

There is no `src/`. Nothing here compiles, so a `src/` root would only have meant inserting
`src/` onto `sys.path` so that `from backend import config` resolved - a directory's _name_
doing work its contents did not. The repo root is the import root instead, which is why
every import is written in full as `backend.libs.<module>`.

Within `backend/`, `libs` is the domain and `cli`/`api` are peers over it. The dependency
direction is one-way and a test enforces it: **`backend/libs` never imports `backend/cli`
or `backend/api`**. That is the whole reason the API could be added without touching the
recommendation logic.

## Sources

5.5e SRD has 339 spells. DNDBeyond 400+ (includes legacy and trademarked spells).

Rules text (`/?`) is grounded in the vendored SRD 5.2.1 Markdown under `context/srd/`,
which is CC-BY-4.0. See `context/srd/PROVENANCE.md` for attribution. The same files are
indexed into the vector store, one row per section, so the rulebook is searchable alongside
the spells.

- https://github.com/downfallx/dnd-5e-srd-markdown/blob/master/spells.md
- https://drive.google.com/drive/folders/16T2y1UaSgLQtEBWXmSU3zc0L7L6TKVT8
- https://www.dndbeyond.com/srd
- https://toolsandtaverns.com/spells
- https://dungeonmister.com/guides/classes-in-dungeons-dragons/celestial-warlock-dnd-2024-guide/
- https://www.dndbeyond.com/classes/2190885-warlock#CelestialPatron

## Versions

### Front end

Framework: React + Vite + Tailwind v4 + shadcn-style components
Status: working — scenario, history, chats, character, rules and search screens

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

The API must be running first (below). The dev server talks to `http://localhost:8000`
directly rather than proxying, because the API allows that origin explicitly — a proxy
would hide the CORS setup from the dev loop and only fail in a real deployment.
`VITE_API_BASE` overrides the address for a build.

Both ports are overridable, because more than one copy of each may be running on the same
machine. `VITE_PORT` moves the dev server and `FRONTEND_PORT` tells the API which origin to
allow; they must be set to the same value or the browser will block the request. `API_PORT`
is documentation only — uvicorn takes `--port` — and `CORS_ORIGINS` adds any further
origins as a comma-separated list.

```bash
VITE_PORT=5273 VITE_API_BASE=http://localhost:8100 npm run dev
API_PORT=8100 FRONTEND_PORT=5273 uvicorn backend.api.main:get_app --factory --reload \
  --reload-dir backend --reload-dir context --port 8100
```

The dev server is already live: Vite replaces a changed module in place, so an edit to
anything under `frontend/app/` appears without a reload and without losing the scenario
typed into the form. Only the API needs the flag, and only because uvicorn does not watch
by default.

`.vscode/tasks.json` starts both, one terminal each, with `⌘⇧B`. The pairs are `Vite: dev`
and `API: dev` for the default ports, and `Vite: dev (5273)` and `API: dev (8100)` for a
second copy running alongside someone else's.

The one thing the UI is careful about: an answer's `source` is always visible. A `sheet`
answer is read verbatim from the character file and cannot be wrong, a `model` answer is
generated and can be, and a `rules` answer is quoted from the 2024 SRD. Showing one as
another would let a plausible guess look like a recorded fact.

A spell mentioned in a book opens in a pull-out drawer rather than navigating away, so the
recommendation stays on screen while you compare. The link is still a real `<a href>` to
`/rules?spell=…`: only an unmodified left click is intercepted, so Ctrl/Cmd/Shift-click and
middle-click still open a new tab. The panel is Base UI's `Drawer` (what shadcn's current
drawer wraps, `@base-ui/react`), which supplies the focus trap, Escape handling and
`aria-*` wiring.

### Backend API

Framework: FastAPI + uvicorn
Status: working

```bash
uvicorn backend.api.main:get_app --factory --reload \
  --reload-dir backend --reload-dir context --port 8000
```

`--reload` is what makes the API live: an edit to a module under `backend/` restarts it
within about a second, and the front end picks up the new routes on its next request with
no restart of its own. The two `--reload-dir` flags matter more than they look. Without
them uvicorn watches the whole repository, and `.cache/` is written on _every run_ — so
each generated book would restart the server, terminating the request that was writing it.
Watching `context/` as well means editing a vendored SRD file or a class context file takes
effect without a manual restart, which is the other half of the rule text this app reads.

Interactive docs are at `http://localhost:8000/docs`. The API contains no logic: every
route validates its input, calls one `SpellbookService` method, and maps the result or a
typed error to a status code. That is what keeps the CLI and the API from drifting apart.

| Endpoint                           | Purpose                                                    |
| ---------------------------------- | ---------------------------------------------------------- |
| `GET /api/health`                  | Liveness, loaded model, index version                      |
| `GET /api/characters`              | Sheet names on disk, for a picker                          |
| `GET /api/character`               | The loaded sheet                                           |
| `GET /api/character/ask?question=` | The `/c` command                                           |
| `GET /api/sheet-keys`              | Every value `/c` can look up                               |
| `POST /api/scenario`               | Generate, or replay the stored run for the same key        |
| `GET /api/cached?scenario=`        | The stored run, or `null` — a miss is not an error         |
| `POST /api/ask?scenario=`          | The `/ask` command                                         |
| `GET /api/history`                 | Every stored run, newest first                             |
| `GET /api/runs/{id}`               | One run reopened for reading                               |
| `POST /api/runs/{id}/rate`         | Record an outcome rating                                   |
| `GET /api/rules?question=`         | The `/?` command, grounded in the 2024 SRD                 |
| `GET /api/spell?name=`             | One spell's description, for every spell mention in the UI |
| `GET /api/invocation?name=`        | One Eldritch Invocation, from the SRD's class chapter      |
| `GET /api/spells`                  | Every name the UI should link — spells and invocations     |
| `GET /api/srd`                     | The vendored SRD as a table of contents, file by file      |
| `GET /api/srd/{name}?slug=`        | One section of one SRD file, quoted; omit `slug` for the whole file |
| `GET /api/search`                  | Search the vector index directly, for inspection           |
| `GET /api/search/facets`           | Every class, school, level and document type the index holds, with counts |

Errors are mapped deliberately, because the distinction a client acts on is whether
retrying could help:

| Exception                               | Status                                                |
| --------------------------------------- | ----------------------------------------------------- |
| `ValueError`                            | 400 — bad input the caller can fix                    |
| `CharacterNotFound`, `RulesUnavailable` | 404                                                   |
| `CharacterNotLoaded`                    | 409                                                   |
| `NoEligibleSpells`                      | 422 — the rules allow no picks; retrying is pointless |
| `EmptyCompletion`                       | 502 — the model returned nothing; retrying may help   |
| `LLMUnavailable`                        | 503                                                   |

A run is identified by an opaque `id` (the cache directory name), never by a filesystem
path: a browser cannot use a server path, and publishing the cache layout leaks
information for no gain. Reopening also accepts a scenario fragment, so a caller that
already knows what it wants can skip the listing.

`POST /api/scenario` and `GET /api/runs/{id}` both return that `id` as `run_id`, and it is
the only handle a client should rate with. Rating by scenario text is ambiguous, because a
run is keyed on the scenario _and_ the character, level and book count — two runs can share
a scenario, and the wrong one gets rated.

#### Browsing the SRD

`GET /api/srd` returns the vendored rulebook as a table of contents — seven files, ~1280
headings, no text — so the Rules tab can draw its tree in one request. `GET
/api/srd/{name}?slug=` returns one section's Markdown, quoted from the file, so a rule read
here cannot be a paraphrase of a bonus. Omitting `slug` returns the whole file.

A section carries `ancestors`: the chain of headings above it, outermost first, excluding
the section itself. That is what the breadcrumb on the rule card is drawn from, and it is
sent rather than left for the client to derive — the client holds the tree and _could_ walk
it, but the server already knows the path, and a second lookup for something already
computed is a way for the two to disagree. Each crumb carries the slug a click needs, so the
trail is also the way to the parent rule.

Every vendored file opens with a single root heading that repeats the document title, so a
section directly under it would breadcrumb as "Rules Glossary / Rules Glossary". The root is
dropped when it is the only ancestor _and_ its text matches the title.

#### The Rules tab's ask box: three readings, in parallel

One typed question is answered three ways at once, each column filling in as it resolves
rather than waiting for the others:

| Lane             | What it reads                                | When it answers       |
| ---------------- | -------------------------------------------- | --------------------- |
| Keyword filter   | The 1274 SRD headings, client-side           | Synchronously         |
| Index search     | `GET /api/search` over the spell corpus      | After a 400 ms pause  |
| The answer       | `GET /api/rules` — the SRD's own matcher     | After a 400 ms pause  |

None of the three short-circuits the others. A rule can be named under a heading, absent
from the spell index, and answerable by interpretation all at once, and the reader picks
which reading answered their question from the badges.

The keyword lane is deliberately **not** debounced. It is synchronous and cheap, and its
whole value is that it answers while the two requests are still in flight — the tab is
browsable during a model call because of it. The two requests share one debounce, so typing
a sentence costs one ask rather than one per word; nothing already on screen is cleared
while typing, so each column is replaced when its own answer lands.

Filtering matches headings only, because a rule's text is not in the table of contents. Two
measurements shaped it, and both are recorded in `frontend/app/lib/srdFilter.ts`:

- Requiring **every** word of `how does cover work` to appear in a heading's path matched
  **nothing**: "how", "does" and "work" are not rulebook vocabulary, so the word that
  mattered was discarded with them. Hence a stop list, and hence the card saying which words
  were ignored.
- Weighting terms by how few headings contain them scores "work" (1 heading) as nine times
  more informative than "cover" (9 headings) — exactly backwards in a question. The words a
  question can afford to lose are its _function_ words, and only a stop list knows those.

A word no heading contains ("stabilize", "privilege") is reported as **unknown** and dropped
from the requirement rather than counted as a miss, because "the SRD never names this" is a
different finding from "I matched nothing", and only one means the rule is absent. When not
every term can be matched the card says the rows are the closest headings rather than the
answer — a filter that quietly softens its own rule is how a reader concludes a rule is
missing when their phrasing was merely unusual.

The whole path to each match is kept in the tree, and its branches are drawn open, because
the matches are deep: **Cover** is three levels under _Playing the Game_, and **Grappled
[Condition]** four under _Rules Glossary_. A mark on the match alone would be no help if it
were two collapsed levels below the fold.

#### Three columns, and why the best answer was at the bottom

The three readings used to stack, which put the answer — the longest reading, and usually the
one being asked for — below two panels that could each be a screen tall. The reading a reader
most wanted was therefore the one furthest from the box that produced it. They are now three
columns at the same height, side by side.

A column with nothing to show is **dropped**, not rendered empty. That is not only about
width: the lanes resolve independently, so for the first few hundred milliseconds two of them
have nothing in them, and an empty bordered box reads as a failure rather than as a request
still in flight. The three are:

| Column             | Shows                                                                | Hidden when             |
| ------------------ | -------------------------------------------------------------------- | ----------------------- |
| Filtered titles    | The matched headings, each with the trail that says where it lives   | Nothing matched         |
| The spell index    | Up to 12 titles, each a link, plus one line of the matched chunk     | No hits and no error    |
| The answer         | The RAG response, its source badge and its citations                 | No answer and no error  |

The title column lists **matches only**, without their ancestors, which is the opposite of
what the tree does. The two answer different questions: the tree says _where_ a rule lives, so
it keeps the whole path and opens the branches down to the match; the list says _which_
headings name the words, which is the only thing a scan can answer faster than the tree. Each
row carries its trail on a second line, because `Cover` is a different rule in _Rules Glossary_
and in _Playing the Game_ and the trail is what tells them apart without expanding anything.

The index column shows a title rather than the full hit card the Search tab renders. Twelve
expandable cards beside two other columns is not a glance; the Search tab is the surface for
reading a hit in full. Each title is a real link to `/rules?spell=<name>`, so a plain click
opens the drawer and a modified one opens the tab.

One line of context is extracted rather than rendered, because the chunks are markdown and
their own markup is what a reader would otherwise see. The extraction strips headings, bold
and links, repairs the corpus's tight citations (`you[Half Cover](…)against` reads as
`youHalf Coveragainst` otherwise), and **skips stat-block field lines** — every corpus file
opens with `Spell Name: X` and `Casting Time: X`, so a chunk cut at a boundary can be nothing
but those, and a dozen hits would all preview as `Spell Name: Nondetection`.

#### The clear button, and abandoning a request

The box has a clear button (and Escape), and it does more than empty the input. The two
requests are in flight independently, so a reply landing a second after the clear would refill
the panels with an answer to a question no longer on screen — which is worse than a blank
panel, because it looks current.

Each lane therefore keeps a **counter** of the request it is waiting for, bumped on every
request and compared on arrival; a stale reply is discarded rather than rendered. A boolean
loading flag cannot do this: it says "something is loading", not "this reply is the one being
waited for". The counters are **per lane**, not shared — the two requests are fired together
and share no ordering, so one counter between them would make whichever resolved second
invalidate the other's reply and one panel would silently never fill.

#### Searching the index

`GET /api/search` is the diagnostic surface, not the recommender. `retrieval` answers "what
is legal for this character"; this answers "what is in the index, and what does a query
bring back" — which is how a missing recommendation gets explained. It can return a spell
the character could never pick, on purpose. The Search tab drives it.

| Parameter                 | Meaning                                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------------------- |
| `query`                   | Text to search for. May be empty in `text` mode, which then lists everything the filters admit |
| `mode`                    | `vector` (similarity), `text` (substring), or `hybrid` (vector, word matches first)            |
| `doc_type`                | `all`, `spell`, `item` or `srd`. Default `all`; takes precedence over `spells_only`            |
| `class`                   | Repeatable; matches any of the named classes                                                   |
| `school`                  | Exact school name                                                                              |
| `level_min` / `level_max` | Inclusive level bounds, 0–9                                                                    |
| `ritual`                  | `true` to require a ritual                                                                     |
| `spells_only`             | Default `true`; `false` includes the 22 magic items the collection also holds                  |
| `all_terms`               | `text` mode: require every word (default) rather than any one                                  |
| `limit` / `offset`        | Page size (max 100) and page start                                                             |

Three modes, because they fail differently. A vector search that returns nothing means the
embedding did not surface it; a text search that returns nothing means the words are not in
the corpus. Telling those apart is most of the work, so the mode is explicit rather than
inferred.

The response carries the Chroma `where` clause it actually sent, because a filter that
silently matches nothing is the commonest failure here and the clause is the fastest way to
see why. `total_matching` counts the distinct documents the _criteria_ admit — filters
always, plus the words in text mode — so it says whether a filter is too narrow. A vector
search has no relevance threshold, so it cannot say how many spells are relevant. `note`
explains a result that needs it: an unsatisfiable filter, an AND that found nothing, or a
candidate cap that truncated the ranking.

`class` is applied as an `$or` over the exact class-list strings the index stores, because
the field is one comma-joined value (`"Bard, Cleric, Wizard"`) and Chroma's `$contains` does
not match inside it — `{"classes": {"$in": ["Wizard"]}}` would miss the 863 chunks whose list
is `"Sorcerer, Wizard"`. A class the index never uses matches nothing rather than being
dropped, because a filter must never widen the search.

#### One collection, three kinds of text

The index holds the spell corpus, the 22 magic items that share its directory, and the
vendored 2024 SRD — 3651 chunks in total, of which 1274 are rulebook sections. They share a
collection because they are searched together: a reader asking "what does cover do" wants
the rule _and_ the spells that grant it.

They are not interchangeable, so every row carries a `doc_type` of `spell`, `item` or `srd`,
and every eligibility filter names the type it wants. Before `doc_type` existed the only
marker was `is_spell`, which cannot distinguish "not a spell" from "not a spell _and_ not a
pick" — an SRD row is `is_spell=False` exactly like a magic item, so a filter that asked only
for "not a spell" would have handed the recommender the rulebook.

`doc_type` takes precedence over `spells_only`, which is the same question at a coarser
resolution. Honouring both would make `doc_type=srd` with the default `spells_only=true`
match nothing at all.

An SRD row is keyed by its _section_, not its heading text, because the SRD repeats headings:
`classes.md` has six `Level 1: Spellcasting` sections, one per class, and keying on the text
would report five of them as duplicates of the first. Its `level_label` reads `Rule` rather
than `Cantrip` — `level` is 0 as a placeholder, and calling that a cantrip is a lie a client
cannot detect, since the row has no school either.

#### The SRD in the vector store

`context/srd/` is indexed one row per section, chunked by heading rather than by the spell
splitter, because a rule's identity is its heading: `### Cover` is the rule, and a chunk that
began mid-table would be a fragment with no name. Sections longer than the chunk budget are
split further, so a 1,750-line class chapter does not become one embedding that matches
everything weakly. The heading is repeated in the chunk body, so a chunk split away from its
heading still says what it is about.

Tables are converted to Markdown pipe tables, never stripped. The numbers in a table _are_
the rule — `### Cover`'s prose only says "as detailed in the Cover table", so a converter
that dropped the markup would index a confident rule with its bonuses missing.

The SRD is used in three places:

| Where | How | Labelled |
| ----- | --- | -------- |
| `GET /api/search?doc_type=srd` | Similarity or substring over the indexed sections | `srd` |
| `GET /api/rules` (last resort) | `rules.gather_from_index` — similarity, when both heading-anchored paths refuse | `rules-inferred` |
| `POST /api/scenario` | `retrieval.gather_srd_context` — the rules the _scenario_ turns on | retrieved context |

The rules lane is the only retrieval path that is not heading-anchored, and it is reached
only after `rules.gather` and `rules.gather_inferred` have both refused. The anchor is what
stops a passing mention being quoted as the rule, so it is deliberately left strict; the
index lane buys recall for a question phrased in words the SRD does not use in a heading
("how do I stop someone running past me" finds _Your Turn_). It is always labelled
`rules-inferred`, because a similarity hit is not a quotation.

The recommender's lane is separate from its eligibility pool. The pool decides what is
_legal_ and is filtered by `doc_type=spell`; the SRD block is grounding, so the model does
not supply "how does being grappled work" from memory — which is where a 2014 reading of it
comes from. It is omitted entirely when empty, because a heading with nothing under it reads
as "the rules are missing" and invites the model to fill the gap.

### CLI

Framework: Python and langchain
Status: working

Run it with:

```bash
python -m backend                  # loads data/characters/lois.yaml
python -m backend.cli              # same thing, spelled differently
python -m backend --character vax  # loads data/characters/vax.yaml
CHARACTER=vax python -m backend    # same, via environment variable
BOOKS=2 python -m backend          # generate 2 alternatives instead of 3
python -m backend --refresh        # ignore cached books, regenerate everything
```

Run from the repo root: the imports are `backend.*`, so the root is the import root. There
is deliberately no `python backend/app.py` - running a file directly puts _its own_
directory on `sys.path`, so that command can never work, and a launch form that crashes is
worse than one that does not exist.

Character sheets are plain YAML in `data/characters/<name>.yaml`; keys are
rendered as `Key: value` lines for the prompt, and list values are joined with
commas.

While it works, the CLI reports each stage and styles the answer:

```
... Fetching spells from the grimoire... (~2.5s)
    done: Fetching spells from the grimoire (2.5s)
... Crafting the prompt... (~0.2s)
    done: Crafting the prompt (0.2s)
... Scribing the Books of Shadows... (~68.5s)
    done: Scribing the Books of Shadows (1m 08s)
```

Each stage is timed, and once a couple of runs are stored the typical duration of each
is known, so a running stage advertises roughly how long it will take. With no history
no estimate is invented. After each run the timings are logged, both for that run and
across all runs. See [Timings](#timings).

Headings, bold and lists are rendered rather than shown as raw markdown, and the
styling is skipped automatically when output is redirected.

### Layout

```
backend/libs/   rules, retrieval, prompting, caching, index, watcher, lookup, timing
backend/cli/    REPL, arguments, progress, markdown rendering
backend/api/    FastAPI routes and wire schemas
frontend/app/   React UI calling the API
```

The rule that keeps the split honest: **`backend/libs` never imports `backend/cli` or
`backend/api`**. `backend.libs.service.SpellbookService` is the seam — it does the work and
returns `Generation`/`Book`/`Answer` dataclasses, and never prints, prompts or exits.
The REPL renders those objects; the API serialises the same ones. A test asserts the
layering holds, so a rule that leaked into a transport layer would fail the suite rather
than quietly existing in only one front end.

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

**Stage 1 — build a legal pool.** What a character may prepare is a _rules_
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

| Context file                                    | Applies to                        |
| ----------------------------------------------- | --------------------------------- |
| `context/spells.md`                             | Every character (casting economy) |
| `context/classes/warlock/base.md`               | Any Warlock                       |
| `context/classes/warlock/pact/tome.md`          | Pact of the Tome                  |
| `context/classes/warlock/subclass/celestial.md` | Celestial Patron                  |

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
explicitly in the prompt. The book's _current_ loadout is deliberately **not**
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

A hit requires the _whole_ key plus a fingerprint of the character sheet, so editing
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
/history                 # list cached runs, newest first, numbered
/read 2                  # open run 2 from that listing and print its books
/read bridge denial      # same, by a fragment of its scenario
python -m backend --refresh # ignore the cache, regenerate every scenario
```

A rating is attached to a book _slot_ and carried across a regeneration, so a
`--refresh` that renames all three books does not discard the scoring you already
did. Because the prompt and response are stored alongside the rating, a rated book
is labelled training data: it records what was asked, what was suggested, and how
well it actually went.

`/history` lists **runs**, not books, because a book is ambiguous on its own — reading
one means reading the scenario it was written for. Each run is numbered so `/read <n>`
reopens it without typing a path, and `/read` restores the current answer, so `/rate`
and the legality warnings work exactly as they do after a fresh generation.

### Ask and chat history

The ask surfaces — `/c` (character), `/?` (rules), the contextual menu and `/ask`
(refine) — store their conversations in `.cache/conversations/`, so an exchange can be
read back rather than asked again:

```
.cache/
└── conversations/
    └── lois/
        ├── rules-how-does-cover-work-3f9a1c2b7d4e.json
        ├── character-why-do-i-have-two-light-spells-8b2e5f0a1c93.json
        └── refine-a-rust-monster-eats-the-fighter-s-plate-4d7c9e1a6b02.json
```

A file is a **thread**, not an answer: the opening question, its kind, and every turn
that followed. A follow-up ("and a grapple?") is only meaningful beside the question it
followed, so the thread is the unit — the same reason `/history` lists runs rather than
books. The thread is keyed on the character and a hash of its opening question, so a
repeat of the same opening question *replays* rather than re-asks.

```bash
/chats                   # list stored conversations, newest first, numbered
/chat 1                  # read conversation 1, every turn in order
/chat cover              # same, by a fragment of its opening question
```

The same store is served over HTTP: `GET /api/conversations` lists threads,
`GET /api/conversations/{id}` reads one, and every ask endpoint returns a `thread_id`
that a client passes back to continue the conversation. The **Chats** screen in the UI is
that listing: filter by surface, then open a thread to read every turn with its
provenance. It is the read side of the store, so nothing on it costs a model call.

**A replay is guarded, not blind.** A character answer is only replayed while the sheet
is unchanged — an edited sheet gives a different answer to the same question, so a
fingerprint mismatch is a miss. A refinement is only replayed against the same previous
answer, because refining different books with the same words is a different request. The
rules and selection surfaces keep their own answer cache and replay from that; the thread
is what gives the character and refine surfaces the same behaviour.

### Timings

Each run records how long its three phases took, in `run.json`:

```json
"timings": {
  "phases": { "retrieval": 2.558, "prompt": 0.0, "books": 38.379 },
  "total_seconds": 40.937,
  "unaccounted_seconds": 0.0
}
```

Per phase rather than one number, because they fail independently and want different
fixes: retrieval embeds the scenario locally, prompting is CPU work, and the model call
is network-bound. `unaccounted_seconds` is whatever the phases do not explain — if that
grows, the measurement is missing something rather than the work being free.

Two choices worth knowing when reading the numbers:

- **The estimate is a median over a short recent window** (5 runs), not the last value and
  not the whole history. A single sample is fragile — one rate-limited run skews every
  estimate after it until the next run lands (observed live: an estimate of `~1m 08s` for
  a run that took `43.2s`). A median over the recent window shrugs off one outlier while
  still following a real trend such as a model change. `median_seconds` is also reported
  across all runs for context.
- **A missing phase is kept, not discarded.** A run that died in the model call still
  has a valid retrieval time.

Phase names are shared with `backend/timing.py`; renaming one in the service without
renaming it there yields an empty breakdown rather than an error, which is why
`test_phase_names_match_the_service_and_the_labels` exists.

### Number of books

`BOOKS` sets how many Book of Shadows loadouts to ask for (1–9, default 3). It is not a
rules number — a book holds 3 cantrips and 2 level 1 rituals and is _one_ loadout per
short rest, so this is how many alternatives to compare. Each one lengthens the answer
and the wait.

```bash
BOOKS=2 python -m backend      # two alternatives, roughly two thirds of the output
```

The count is part of the cache key, so asking for two is a different request from asking
for three and will not replay a stored three-book run. An out-of-range or non-numeric
value is clamped with a warning rather than failing the run — a typo in an untracked
`.env` should not cost you a scenario.

Tests:

```bash
pip install -r requirements-dev.txt
pytest
```

657 tests. The suite covers `/slash` command parsing and TAB completion, character
sheet loading, spell parsing and eligibility rules, prompt assembly, the retrieval lanes,
book-pick validation, the result cache, the service layer, sheet and rules lookup, timing
aggregation, every API endpoint and its error mapping, and terminal rendering/progress.
It never builds a vector index, contacts a model, or touches `data/chroma_db`; anything
that writes is redirected to a temp directory.

Three tests guard structure rather than behaviour, because these are the failures that
would otherwise go unnoticed:

- `backend` imports without `cli` or `api`, so the layering stays intact.
- The CLI turns a missing character into an exit code, so the library stays
  exception-based.
- The API's error mappings hold. A wrong status code is a contract bug the front end
  hits, and testing the service directly cannot catch it.

Where a fake would hide the thing under test, the real path is kept. The rules cache test
stubs only the model call: replacing `gather`, or the file reader beneath it, would replace
the cache lookup the test exists to verify. Stubbing the corpus is worse than useless - it
changes the term-frequency model the matcher ranks headings with, so the test asserts
whatever a one-line fake SRD implies rather than what the real one does.

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
- [ ] Add /character command to switch characters
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
- [x] when the read books is open it should show all the content--so grid is probably the wrong thing to do .. Use flex and flex wrap probably and the open one should be full width.
- [x] Opening in the scenario screen should show the results as well as the prompt.
- [x] When reading a book open clicked local context spell descriptions in a pull out drawer.Keep the original link so that CTRL CLICK still opens in a new tab but add an onclick handler to trigger the drawer (for local links).
- [x] The pull out drawer of spells should have a search box at the top to search all spells.
- [x] Spells display parsing: Expand Components to their full meaning (V, S, D, M), add Damage (if any) to the description at the top next to Casting time, add icons to duration, casting time, damage, components, range.
- [x] Asking a question in the rules search like "explain the initiative system to me like I'm 12yo" should respond with a generative answer based on the rules if it can't find a precise rule not "The 2024 SRD has no section matching 'explain the initiative system to me like I'm 12yo'. The SRD covers the core rules, not every option in the Player's Handbook."
- [x] Highlighting a piece of text should bring up a contextual window with search in it. Search should use RAG to find out what the selected text means in context of the game.
- [x] Percentage (in timing) shouldn't stop at 99% if the process is running longer.
- [ ] When showing spells or other information contextualise it to the current character: "Goodbye, Warlock" should be "Goodbye Louis", "Eldritch blast" should show "2 beams (L5)". Use a small fast model for contextualising rules to levels.
- [x] When you press the "read books" button it flashes some other text briefly (Open something) and then flips back only changing the caret. It should say something like "hide books".
- [ ] We have 'Fetching spells from [the] Grimoire' in multiple places. It should be a const or enum.
- [x] Switch to Lucide icons
- [ ] When switching "tabs" keep the running processes going. eg Scenario planning, question asking. Update the tabs with progress meters.
- [ ] Let's write evals for the scenario planning
- [x] Reduce duplication in the display of books: in the scenario view book, title, and spells are all duplicated
- [x] Replace the model's prose book format with explicit `=== BOOK n ===` sections, so splitting a book no longer relies on heuristics. This also removes the spurious extra "books" the trailing summary produced (`**Book 3 pairs with:**` was read as a fourth book and recited inside the last one).
- [ ] Clean out the runs stored in the old prose format, and delete the legacy parser and the front end's `withoutBookHeader`/`reasoningOnly` once they are gone.
- [x] In the book listing at the top both cantrips are in one lozenge and rituals in another. They should be in 5 separate lozenges with a label between the groups.
- [ ] As we have a local copy of the rules list them out on the rules page
- [ ] Rules list: enable a quick UI only search on titles.
- [ ] Rules list: Then enable a vector search over the documents.
- [x] "Ask" box on the Rules tab should: filter rules by title, heading, subheading; search the text using vector search; and ask the question of the LLM. — the three run in parallel, each panel updating as it resolves. The filter matches headings client-side and opens the path to each match; the search is `GET /api/search`; the ask is unchanged.
- [ ] Provide a history search.
- [ ] Rules list: Context documents and attachments should be links to the rules.
- [ ] The context menu provided for the book should work for the character and the rules.
- [ ] The context menu should support "ask" and "search".

### Choosing the model

`LLM_MODEL` in `.env` selects the reasoning model for both backends. Which backend it
means is inferred from the name, because the two conventions are unambiguous — an
OpenRouter id is `vendor/model` (contains `/`), an Ollama name is `name:tag` (does not):

| `LLM_MODEL`                         | Backend used                                    |
| ----------------------------------- | ----------------------------------------------- |
| unset, `OPENROUTER_API_KEY` set     | OpenRouter, `deepseek/deepseek-v4.1-flash-1017` |
| unset, no key                       | Ollama, `qwen3.5:4b`                            |
| `deepseek/deepseek-v4.1-flash-1017` | OpenRouter                                      |
| `qwen2.5-coder:7b-instruct`         | Ollama — **even with a key present**            |

That last row is the point: it lets a key stay in `.env` for occasional use while
running locally by default. A remote model id with no key falls back to Ollama and says
so, rather than silently swapping models.

```bash
LLM_MODEL=qwen2.5-coder:7b-instruct python -m backend   # local, one-off
LLM_MODEL=openai/gpt-4o-mini python -m backend          # OpenRouter, one-off
```

`OLLAMA_MODEL` also overrides the local default (`qwen3.5:4b`) when `LLM_MODEL` is unset.
The embeddings model stays on Ollama regardless — `nomic-embed-text` is local-only.

`LLM_MODEL_FAST` is a second, independent setting for the small model that answers
one-line questions — currently reading a spell's scaling at the character's level when the
spell states it in prose rather than in a table. It routes by the same name-based
inference, and **unset means the main model is used**, so it is optional:

```bash
LLM_MODEL_FAST=deepseek/deepseek-v4-flash-0731   # OpenRouter
LLM_MODEL_FAST=qwen2.5-coder:1.5b-base           # local
```

Its output is capped (`llm.FAST_MAX_TOKENS`), and the cap has to cover the model's *hidden
reasoning* as well as the answer — a cap sized to the phrase alone truncates a reasoning
model to an empty reply.

Its answers are cached under `.cache/scaling/<character>/<level>-<spell>-<hash>.json`, keyed
on the character's name and level, so opening the same spell twice costs one call rather than
two. Only the model's answers are cached; the ones read straight out of the spell's text are
free and are recomputed each time.

Note: `qwen3.5:4b` is a _thinking_ model. It can spend its whole token budget on
internal reasoning and return an empty response, so the CLI reports an empty
completion as a failure rather than printing nothing. For local work a slightly
larger non-thinking model gives more reliable structured output
(`LLM_MODEL=qwen2.5-coder:7b-instruct`).
