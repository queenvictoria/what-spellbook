# AGENTS.md

## AI Agent Configuration for Spellbook Recommendations

This document defines the AI agents that power the spell recommendation system, and
records development learnings for anyone (human or agent) working on the repository.

### What this project actually is

A **Python core** that recommends D&D 5.5e (2024) spells for a scenario, with three
front ends over it: a `cmd.Cmd` REPL, a FastAPI HTTP API, and a React UI. Retrieval is a
local **Chroma** vector store of spell markdown files; the model is reached through
**LangChain** with OpenRouter or Ollama backends.

The TypeScript interfaces later in this file describe the **agent configuration shape**
from the original design. Where they disagree with the implementation, the
implementation wins - the wire contract the UI actually depends on is
`src/api/schemas.py`, mirrored by hand in `frontend/src/api/types.ts`.

### Layout: one backend, three front ends

```
src/
  backend/        rules, retrieval, prompting, caching - no terminal, no printing
    config.py       paths, models, tunables (+ resolve() for repo-relative paths)
    indexing.py     Chroma build/validate/rebuild
    characters.py   sheet loading and the rules questions we ask of a sheet
    spells.py       spell parsing, eligibility filters, book-pick validation
    retrieval.py    candidate collection and prompt-block rendering
    prompts.py      prompt templates + context-file resolution
    cache.py        per-run/per-book result cache
    lookup.py       deterministic sheet answers (/c), duplicate-spell origins
    rules.py        2024 SRD retrieval for /? (host allow-list, heading match, cache)
    timing.py       per-phase aggregation behind the ETA
    llm.py          backend selection, response normalisation, typed errors
    service.py      SpellbookService - the application layer
    watching.py     corpus file watcher
  cli/            terminal only - parsing, completion, progress, formatting
    app.py          argument parsing, startup, clean shutdown
    shell.py        the cmd.Cmd REPL
    progress.py     Claude-style stage display
    render.py       markdown -> styled terminal output
  api/            HTTP only - routing and wire schemas
    main.py         create_app(), the routes, error mapping
    schemas.py      the wire contract (pydantic)
frontend/         React UI - its own package.json, vite.config.ts, tsconfig
main.py           compatibility shim (re-exports the old names)
```

**The rule that keeps this honest: `src/backend` must not import `src/cli` or
`src/api`.** A test enforces it (`test_service_imports_without_a_terminal`). If the
backend ever needs a terminal or a request object, the other surfaces cannot reuse it.

`SpellbookService` is the seam. It does the work and returns dataclasses
(`Generation`, `Book`, `Answer`); it never prints, prompts or exits. The REPL renders
those objects; the API serialises them; the UI draws them. Errors are typed
(`NoEligibleSpells`, `llm.EmptyCompletion`, `llm.LLMUnavailable`,
`CharacterNotFound`, `RulesUnavailable`, `IndexUnavailable`) so each surface decides how
to report them - which is why the library no longer calls `sys.exit`.

**Prefer the packages over the shim.** `main.py` exists so existing habits,
`python main.py` and older imports keep working; new code should use
`from backend import service, characters` and `python -m src.cli.app`.

### Separation of concerns - two different kinds of document

| Location | Contains | Does **not** contain |
| --- | --- | --- |
| `context/**/*.md` | Rules text injected into the **model prompt** | Code, architecture, sprint notes |
| `AGENTS.md` (this file) | **Development learnings** for building the scripts | Prompting context for the model |
| `data/characters/*.yaml` | A single character's actual values | Rules that apply to a whole class |

Keep these apart. A context file that knows a character's level, or an `AGENTS.md` that
carries spell rules, will both go stale in the wrong direction.

## Agent: Spell Recommender

**Purpose:** Analyze scenarios and recommend appropriate spells based on ruleset, character level, and spell lists.

### Responsibilities

1. Parse and understand the scenario/encounter prompt
2. Extract key parameters (level, class, pact boon, magic item tags)
3. Filter spells from the available spell list based on:
   - Available spell slots per level
   - Pact of the Tome flexibility (select from any class)
   - Tag-based filtering (e.g., `[fire]`, `[heal]`, `[save]`)
4. Rank spells by relevance and effectiveness
5. Generate a rationale explaining why each spell is recommended
6. Create a deployment cheatsheet with:
   - Spell slots per level breakdown
   - Recommended combinations for different encounter phases
   - Quick-reference notes for combat

### Input Format

```typescript
interface RecommenderInput {
  scenario: string;           // The scenario/encounter description
  spellList: Spell[];         // Available spells from ruleset
  character: Character;       // User's character info
  ruleset: Ruleset;           // Ruleset configuration
}

interface Character {
  name: string;
  level: number;
  class: string;
  background: string;
  pactBoon?: 'pact_of_the_tome' | 'pact_of_the_chain' | 'pact_of_the_blade' | 'pact_of_the_wayfarer';
  subclass?: string;
  tags: string[];             // User's magic item tags
}
```

### Output Format

```typescript
interface RecommenderOutput {
  recommendations: RecommendedSpell[];
  rationale: string;
  cheatsheet: Cheatsheet;
  summary: string;
}

interface RecommendedSpell {
  id: string;
  name: string;
  class: string;
  level: number;
  isCantrip: boolean;
  description: string;
  rationale: string;
  tags: string[];
}

interface Cheatsheet {
  spellSlots: { level: number; slots: number; spells: string[] }[];
  encounterPrep: {
    phase: 'initiative' | 'short_rest' | 'combat' | 'exploration';
    recommendations: RecommendedSpell[];
    notes: string[];
  };
  quickRef: {
    damageType?: string;
    defenseType?: string;
    utilityType?: string;
  };
}
```
### Configuration

```json
{
  "agent": "spell_recommender",
  "model": "claude-3-5-sonnet-20241022",
  "temperature": 0.3,
  "maxTokens": 4000,
  "systemPrompt": `You are a D&D 5.5e spell recommendation assistant specialized in helping players optimize their spell selection based on scenarios and encounters.

Your recommendations should:
1. Grounded in the provided ruleset and spell list
2. Account for character level and class restrictions
3. Leverage Pact of the Tome flexibility when applicable
4. Consider tag-based filtering for magic item effects
5. Prioritize versatility and effectiveness
6. Provide clear rationales for each choice

Generate actionable cheatsheets for in-combat use.`
}
```

## Agent: History Manager

**Purpose:** Manage scenario history, store user ratings, and support scenario refinement.

### Responsibilities

1. Store completed scenarios with user feedback
2. Allow users to rate recommendation quality (1-5 stars)
3. Capture updated scenario prompts after review
4. Maintain temporal ordering of recommendations
5. Provide access to historical context for learning patterns

### Input Format

```typescript
interface HistoryInput {
  scenarioId: string;
  scenario: string;
  recommendations: RecommenderOutput;
  rating: number;              // 1-5 stars
  feedback: string;            // Optional notes
  updatedScenario?: string;    // If user modified the scenario
  date: string;
}

interface QueryHistoryInput {
  characterId?: string;
  startDate?: string;
  endDate?: string;
  minRating?: number;
}
```

### Output Format

```typescript
interface HistoryOutput {
  history: HistoryEntry[];
  stats: {
    totalScenarios: number;
    averageRating: number;
    mostUsedTags: string[];
  };
}
```

## Agent: Storage Manager

**Purpose:** Handle local storage persistence, JSON export/import, and cloud sync.

### Responsibilities

1. Persist character data, scenarios, and settings to localStorage
2. Export complete data to JSON for backup
3. Import JSON data for migration or restoration
4. Implement encrypted cloud sync when ready
5. Provide diff-view for what changed during export/import

### Storage Schema

```typescript
interface StorageData {
  characters: Character[];
  rulesets: Ruleset[];
  spellLists: SpellList[];
  scenarios: HistoryEntry[];
  settings: {
    theme: 'light' | 'dark';
    exportFormat: 'json' | 'json-compact' | 'json-with-comments';
  };
  lastSync?: string;
}

interface Character {
  id: string;
  name: string;
  level: number;
  class: string;
  subclass?: string;
  background: string;
  pactBoon?: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}
```

## Agent Workflow

### Recommendation Flow

1. **User Input** → Scenario description, character info, spell list
2. **Parse & Validate** → Extract parameters, check compatibility
3. **Agent Processing** → Spell Recommender analyzes and ranks spells
4. **User Review** → View recommendations, rate quality
5. **Feedback Loop** → History Manager stores results
6. **Refinement** → Optional scenario update based on feedback

### State Transitions

```
[Idle] → [Analyzing] → [Ready] → [Reviewed] → [Stored]
        ↓               ↓           ↓           ↓
    [Error]       [Processing] [Dismissed]  [Refined]
```

## Development Workflow

For developers working on this project:

1. **Feature Development**: Update the relevant agent config in this file
2. **Testing**: Use the provided interfaces as test fixtures
3. **Documentation**: Keep agent prompts in sync with actual implementation
4. **Iteration**: Modify system prompts based on user feedback

## Context files

Prompting context lives in `context/`, laid out as `context/classes/[class]/[pact|subclass]/`
plus a class-agnostic `context/spells.md`:

```
context/
  spells.md                          # class-agnostic casting economy
  classes/
    warlock/
      base.md                        # class-wide: progression, Pact Magic, invocations
      pact/tome.md                   # Pact of the Tome / Book of Shadows
      subclass/celestial.md          # Celestial Patron
```

Resolution lives in `prompts.context_files_for()`, which derives the paths from the
sheet's `Class`/`Pact`/`Subclass` and skips any file that is missing — so a character
with no subclass yet still gets the class-wide rules.

Rules for context files:

- **`base.md` holds class-wide rules; pact and patron files hold only their own.**
  Do not repeat the progression table in a pact file.
- **Never write a level or a character name into a context file.** Context files
  describe rules; `data/characters/*.yaml` describes a character. A context file that
  says "at level 5 you have 2 slots" is wrong the moment the character levels up.
- A pact file must not assume the character's pact. State what the file covers, then
  tell the reader to check the character sheet.
- Cross-reference sibling files by path instead of duplicating their content.

## Development learnings

Hard-won facts about this codebase. Each of these cost real debugging time.

### `main.py` must stay import-safe

No side effects may run at import time - tests and tooling import the module. Anything
expensive or destructive belongs inside a function called from `main()`:

- `ensure_db()` rebuilds the Chroma index. It must **not** run on import.
- `get_embeddings()` creates embeddings lazily.
- `get_observer()` is a **factory**. A second `Observer().start()` raises
  `RuntimeError: threads can only be started once`, so the watcher cannot be a
  module-level singleton.

The rebuild path deletes the index directory. When it ran at import scope, merely
importing `main` in a test could destroy the user's index. Refreshing the Chroma client
cache (`SharedSystemClient.clear_system_cache()`) is required before removing the
directory, or the rebuild reuses a stale handle and fails with
`attempt to write a readonly database`.

### `cmd.Cmd` + readline completion quirks

The `/slash` command completion is fragile. Three separate traps:

1. **`cmdloop()` rebinds the completer after `__init__`**, discarding any completer set
   there. Completion must be injected through the `completenames()` hook.
2. **`/` must be removed from `readline.get_completer_delims()`**, not added. While `/`
   is a delimiter, TAB on `/s` yields `text='s'` at `begidx=1`, which routes to argument
   completion and bypasses `completenames` entirely. Removing it yields `text='/s'` at
   `begidx=0`.
3. `cmd.Cmd.completenames("")` also returns cmd's own built-ins (`help`, `EOF`, ...).
   Assert a **superset**, never equality.

`cmd.complete()` reads readline's terminal-global `get_begidx()` / `get_line_buffer()`,
which are meaningless outside a TTY. Unit tests that call `complete()` directly only
appear to pass because `begin`/`end` are 0 and `lstrip('')` fails. **Only a PTY test
actually validates completion** - run one when touching this code.

Adding a command means editing `COMMANDS`, `intro` and `do_<name>`; completion and
`/help` both derive from `COMMANDS`, so they cannot drift from it. Bump
`tests/test_repl_commands.py` only where it asserts an exact completion list - the
command surface itself is asserted as a superset by design.

### Splitting a god module without breaking the suite

`main.py` held config, indexing, retrieval, prompting, caching, the watcher, the LLM
client, the REPL and the entry point. Pulling it apart surfaced traps worth recording:

- **Moving code is not renaming it.** Helpers like `known_spells` were reached through
  `main.` by eight test files, so `main.py` stayed as a shim re-exporting the old names
  rather than being deleted. A shim is cheaper than a sed across the suite, and it keeps
  `python main.py` working for the user.
- **Monkeypatching follows the module, not the shim.** Tests patched `main.CHARACTERS_DIR`
  and `main.CACHE_DIR`; once the code reads `config.CHARACTERS_DIR`, patching the shim's
  copy does nothing and the test silently hits the real directory. Fixtures must patch
  the module that *reads* the value. This is the nastiest class of refactor bug because
  the test still passes - it just stops testing anything.
- **`python -m src.cli.app` puts only the repo root on `sys.path`,** so `import backend`
  fails while `python main.py` works. `src/__init__.py` therefore bootstraps `src/`
  onto the path itself, so all three launch styles agree.
- **A library must not call `sys.exit`.** Tests that asserted `SystemExit` were rewritten
  to assert the typed exception, and the exit code moved to the CLI boundary where
  `main()` can return it. That is what lets an API reuse the same code path.
- **Relative paths must resolve against the repo root, not the CWD.** `config.resolve()`
  exists so launching from another directory does not silently read a different index or
  character folder.
- **Keep the private-name aliases.** `_format_pool`, `_db_is_valid`, `_split_names` etc.
  are still exercised by name; deleting them would have meant touching tests for no
  behavioural gain.

### Tests

- Run `.venv/bin/python -m pytest` from the repo root.
- `tests/conftest.py` fakes LangChain's LLM, retriever and vector store, so no model
  call or network access is needed.
- Fakes must match real signatures. The retriever fake takes
  `as_retriever(search_kwargs=None)` because that is what LangChain's real method
  accepts; a narrower fake lets broken calls pass.
- Opening a Chroma store rewrites metadata, so the sqlite mtime changes on every
  launch. That is normal, not corruption - do not assert on it.
- Anything that writes must be redirected. Cache tests monkeypatch `main.CACHE_DIR`;
  without that the suite writes `.cache/` into the working tree.

### Sources: 2024 only

**This project is 2024 rules only.** Every context file, prompt and ruling must cite the
2024 (5.5e) edition. The two editions disagree in ways that silently corrupt
recommendations, and a mixed corpus is worse than either one alone because the model
cannot tell which it is reading.

| Source | Edition | Note |
| --- | --- | --- |
| `5e24srd.com/classes/warlock.html` | **2024** | Correct. The `.html` extension is required - the extension-less URL 403s |
| `5e24srd.com/spells/spell-descriptions.html` | **2024** | The spell text `/?` is grounded in |
| `5thsrd.org` | **2014** | **Do not use.** Its own banner points at 5e24SRD.com |
| `dndbeyond.com` | mixed | Subclass text is behind a subscription |

`5thsrd.org` is the trap: it ranks well for "5e SRD" searches and looks authoritative,
but it serves the 2014 SRD 5.1. Do not cite it and do not fetch from it.

The divergence is not cosmetic. At level 5, 2014 gives **3 invocations with Pact of the
Tome free**, while 2024 gives **5 invocations with Pact of the Tome costing one**. The
progression shape differs too - 2014 grants **0 invocations at level 1** and uses
"Spells Known", while 2024 grants **1 invocation at level 1** and uses "Prepared
Spells". A single 2014 number silently invalidates a whole recommendation.

The 2024 SRD contains **only the Fiend Patron**. Other 2024 subclasses (Celestial,
Archfey, Great Old One) have no free SRD page; use the 2024 class data (`XPHB` source)
rather than a wiki. Patron features do move between editions - the 2014 Celestial lists
Healing Light at level 1 and Searing Vengeance as self-only, whereas 2024 moves Healing
Light to level 3 and lets Searing Vengeance rescue an ally.

### The 2024 SRD is not the whole 2024 rulebook

`5e24srd.com` carries SRD 5.2, and large parts of the 2024 rules are *not in it*. Verified
by crawling every page and checking headings directly:

| Rule | In the SRD? |
| --- | --- |
| Cover, Hiding, Difficult Terrain, Travel Pace, Dropping Prone | yes, under its own heading |
| **Short Rest / Long Rest** | **no** - mentioned only in passing, including "Attune during a Short Rest" |
| **The Grappled condition** | **no** |
| **The Rules Glossary** | **no** - pages cross-reference it, but it is absent |

This matters for `/?`: the SRD is not a reference the model can ask questions of and
expect answers to. Two failure modes were observed live and both are now handled:

- **A passing mention looked like the rule.** "What is a short rest?" matched *"mounts
  need a Short or Long Rest before they can move"* in a travel-pace sentence, and later
  *"Attune during a Short Rest"* in the magic-items page. A sentence using the term is
  not the rule.
- **An equipment entry looked like a rule.** "How does grappling work?" matched
  **Grappling Hook** in a price list, because the rulebook says "Grappled" and the tool
  is named "Grappling Hook".

The fix is structural, not a better score: **match on sections and require the section
heading to be about the question.** A rule in the SRD is defined under a heading that
names it. Anything else - a mention, a cross-reference, an equipment row - is refused.
Excluding equipment headings also needs the price pattern (`Grappling Hook (2 GP)`), or
the tool still wins on heading text alone.

Refusing is the honest outcome and is what `RulesUnavailable` reports. Do not "improve"
the matcher by lowering the heading requirement: a plausible-looking wrong paragraph is
worse than admitting the SRD does not contain the rule, because the user cannot tell.

### Verify rule numbers programmatically

Do not transcribe a rules table by hand. Pull the source, parse it, and diff it against
the markdown - every progression row, every level gate. Manual transcription errors in
these tables are invisible on review and fatal in play.

Watch for checker bugs too: a prerequisite parser that skips dict-valued `level` fields
silently reports wrong level gates. When a check fails, confirm the checker is right
before "fixing" the document.

### Working in this repo

- **Files may change between turns.** Re-read a file before concluding a failure is a
  bug in your code; the user edits during the session.
- `data/` is gitignored, so the character sheet and the Chroma index are untracked.
- `.cache/` is gitignored too, and is **user data** - never delete it, and never let a
  test write into it.
- Spell corpus: 544 markdown files, indexed as ~1280 chunks.
- `markdown-it-py` needs `MarkdownIt("commonmark").enable("table")` to validate GFM
  tables; the `gfm-like` preset fails with `ModuleNotFoundError: Linkify enabled but
  not installed`.

### Front end tooling

- **Vite + React + TypeScript + Tailwind v4 + shadcn-style components**, in `frontend/`
  with its own `package.json`. It is a separate npm project, not a workspace.
- **Tailwind v4 has no `tailwind.config.js`** - the palette and base layer live in
  `src/index.css` under `@theme`. Adding a colour means adding a token there, not a
  config entry.
- **`baseUrl` is gone in TypeScript 7.** Path aliases work from `paths` alone; adding
  `baseUrl` fails the build with `TS5101`. The alias must also be mirrored in
  `vite.config.ts`, since Vite does not read `tsconfig.json` for resolution.
- **`erasableSyntaxOnly` is on**, so a constructor parameter property
  (`constructor(readonly x: T)`) is a build error. Declare the field and assign it.
- **The root `.gitignore` Node patterns are anchored with a leading `/`.** They existed to
  keep the retired root-level `node_modules` out; unanchored, they also ignored
  `frontend/package-lock.json`, which a front end must commit.
- Lint with `npx eslint src`, typecheck and build with `npm run build` (`tsc -b && vite
  build`). Both are clean and should stay that way.

### Retrieval: filter first, rank second

The recommender runs in two stages and they must stay separate:

1. **Eligibility** decides what is *legal* for the character (class, pact, subclass,
   level). This is a rules question and the scenario must never widen it.
2. **Ranking** uses the scenario to order an already-legal pool.

Specific traps hit while building this:

- **A similarity search cannot enumerate.** Book of Shadows takes exactly 3 cantrips
  and 2 level 1 rituals, so those lanes are fetched exhaustively from Chroma metadata
  (`db.get(where=...)`), not by vector search. Relying on similarity would silently
  omit legal options.
- **One chunk is not one spell.** The index holds 1280 chunks for 544 spells, so a raw
  `k=30` returned roughly 13 distinct spells. Always dedupe by spell name.
- **Do not put ineligible spells in the pool as "context".** Listing castable levelled
  spells for "synergy advice" caused a model to file Misty Step (level 2) and Daylight
  (level 3) as *book picks*. A flat spell list reads as pickable. Only pool-eligible
  spells belong in the pool; a Warlock's prepared list does not change on a short rest
  anyway, so those suggestions are not actionable.
- **Chroma's `$and` rejects a single child**, and numeric operators (`$lte`) only work
  on numeric metadata. Hence `build_where()` unwrapping one clause, and `level` stored
  as an `int` rather than a tag string.
- **Bump `INDEX_VERSION` when metadata changes.** Without the guard a stale index keeps
  serving old fields and every metadata filter silently returns nothing.
- **`Collection.get(include=["embeddings"])` returns a numpy array.** `not payload[...]`
  raises `ValueError: truth value of an array ... is ambiguous`, which an `except` will
  swallow — making the validator always report "invalid" and rebuild every launch. Use
  `len(...) == 0`.

### Validate the model's output, do not trust it

The pool is filtered before the model sees it, and models still mis-file picks. The
recurring real failure: **a Celestial Warlock's always-prepared `Guiding Bolt`** appears
in the rules context, so the model puts it in a book — where it is illegal, because
always-prepared spells are not book options. `spells.validate_book_picks()` parses the
answer and checks every entry against the pool; the shell warns when it finds a
mismatch. Keep that guard: a wrong book is only discovered at the table.

Two parsing details that matter when writing such a guard:

- Models copy the pool's annotation into the bolded name
  (`**Light (Cantrip; Evocation; Bard)**`). Strip it, or every pick looks illegal.
- When normalising a spell name, do not collapse whitespace —
  `"Detect Magic"` becomes `"DetectMagic"` and matches nothing.
- Normalise apostrophes to ASCII. Models write `Tenser’s Floating Disk` with a
  typographic `’` while the corpus uses `'`, so a legal ritual was reported as
  illegal. The same applies to hand-written sheets, where an unmatched name is
  silently dropped from the pool.

A third, found later and worse than either: **the guard can pass on an answer it could
not read.** The parser originally only understood bulleted lists, but the model usually
writes picks inline (`**Cantrips:** Light, Sacred Flame, Message`). Zero parsed picks
means zero problems reported, so the validator vouched for an answer it never examined.
Two rules follow:

- When a guard finds *nothing*, check it can still find something. Assert on a real
  model answer, not on a tidy format you wrote yourself.
- Never let a second parser re-implement the same reading. `cache.parse_picks()` now
  delegates to `spells._book_picks()`; two implementations would eventually disagree
  about what was chosen, and only one of them would be guarded.

### A sheet is a union, not a field

`known_spells()` must union **every** field that grants a spell: Warlock picks, the
patron's always-prepared list, species and feat cantrips, and free casts. Reading only
`Known/Prepared Base Spells` left `Light` and `Sacred Flame` in the pool for a Celestial
Aasimar that always has both, so the model spent book picks on spells the character
already had. The pool now excludes them and the prompt states the list explicitly.

But the book's *current* loadout (`Book of Shadows Cantrips` / `Rituals`) must **not**
be excluded: the book is conjured freshly at each rest, so re-picking is legal.
Excluding it would also let this tool's own previous answer permanently constrain the
next one. Both the exclusion set and the "still legal" note are deliberate.

Also strip a trailing parenthetical from sheet entries — sheets record provenance there
(`Light (Aasimar)`), and it is not part of the name.

### The cache is the training set

`.cache/` stores a run as a shared `run.json` plus one file per book, keyed by
character, level, party, database version and a scenario hash. It is written **before**
the answer is printed, because it is the record used for post-play ratings, and it is
**read before any work** so a repeated scenario costs nothing.

- **A write-only cache is not a cache.** The first version stored everything and never
  looked it up, so re-running a scenario re-ran the whole pipeline. Store *and* read.
- **Look the cache up before the retrieval stage**, not just before the model call. The
  ranking lane embeds the scenario, so a lookup placed after it still pays for an
  embedding request.
- **The key includes `INDEX_VERSION`.** A rebuilt index changes the pool, so old
  entries are incomparable and must land in a new directory.
- **Name and level do not identify a character.** A sheet edited between runs (spells,
  subclass, items) gives different advice at the same level, so the entry stores a
  fingerprint of the whole sheet. It is compared on read but kept out of the path, so a
  re-run overwrites in place instead of littering directories.
- **Keep shared inputs in one file.** The prompt is ~33KB and identical for all three
  books; storing it per book copied it three times.
- **A book file is the unit of rating**, so its rating lives there and rating one book
  never rewrites its siblings.
- **Key carried ratings by book slot, not by filename.** A regeneration renames the
  books, so matching on the name silently discarded every rating. This was only caught
  by regenerating a real run and looking at the files.
- **Never let a cache failure lose the answer.** Reads and writes are wrapped and
  reported, not raised.
- **Treat a partial directory as a miss.** A hand-deleted book would otherwise show the
  user fewer books than the model produced.
- **Re-validate on a hit.** A cached answer may predate a rules change, so the
  eligibility guard runs again rather than being trusted.
- **The scenario is hashed, but also stored.** The hash makes a valid path component;
  the text has to survive somewhere or a rating cannot be interpreted later.
- **Parsing the model's books is harder than it looks.** A real answer ends with a
  summary whose bullets start `**Book 1 pairs with:** Hex, ...`. An unanchored book
  regex treated those as headings, producing six books and stealing picks from the real
  ones. Require a heading to be short and to not read like prose; dedupe by book number.
  Heading labels are also case-unstable (`**Level 1 rituals:**`), so look section names
  up casefolded.
- **Anchor a label regex to the line start.** An unanchored `Cantrip` also matches
  inside a pick's annotation (`1. **Light** (Cantrip; Evocation; Bard)`) and was read as
  a new label, discarding that pick.

`.cache/` is gitignored: it is user data, like `data/`.

- **A relative path resolves against the process CWD, not the repo.** `.cache` and
  `context` were the only configured paths never passed through `config.resolve()`,
  while the index, docs and character directories were. So launching the CLI from
  anywhere other than the repo root silently wrote books into *that* directory and
  loaded an empty rules context — the symptom was "the cache isn't being created",
  because it was being created elsewhere. Prefer the resolved constants
  (`CACHE_DIR_PATH`, `CONTEXT_DIR_PATH`, …); the bare names still exist for the
  import-compatibility shim only.
- **Test the CWD, not just the code.** No unit test could catch this: every test ran
  with the repo root as `cwd`. The regression test launches a real subprocess from a
  `tmp_path` and asserts no `.cache` appears there.
- **Clean up with `rm -rf .cache` and you destroy the user's history.** It looks like a
  build artifact, but it is the record of every run and rating — the thing the whole
  project is trying to accumulate. Verify against a throwaway `--cache-dir`/temp path,
  and never delete the real one during development.
- **An added optional field is not a schema change.** Adding `timings` does not need
  `SCHEMA_VERSION` bumped, because readers already treat a missing key as "no data".
  Bumping invalidates *every* cached run and *every* rating, and costs the user a fresh
  model call for nothing — which is exactly what happened here. Bump for a renamed
  field, a changed meaning, or a new *required* key. If you do bump, expect to migrate
  the existing entries rather than silently discarding the user's data.
- **A new input belongs in the cache key.** `BOOKS` changes the answer, so it had to join
  `db_version` in `key_parts` and `key_dir` — otherwise a `BOOKS=2` request replays a
  stored three-book run and the caller silently gets the wrong number of books. The
  rule: if it would change the output, it is part of the key. Directory shape changed
  from `<level>-<party>-<db>-<hash>` to `<level>-<party>-<db>-<books>-<hash>`.
- **Time the phases, not the run.** Retrieval, prompting and the model call fail
  independently and want different fixes, so a single total says "it is slow" and
  nothing else. Keep an `unaccounted_seconds` too: growth there means the measurement is
  missing work, not that the work is free.
- **Estimate from a median over a short recent window, not the last value.** A single
  latest sample is fragile: one rate-limited or otherwise slow run poisons every estimate
  after it until the next run lands. Observed live — an estimate of `~1m 08s` for a run
  that took `43.2s`, because the previous run had been slow. A median over the last few
  runs (5) shrugs off one outlier while still following a real trend; a median over the
  whole history would lag a model change forever. A mean is worse than either, since
  outliers dominate it.
- **Do not invent an estimate.** With fewer than `timing.MIN_SAMPLES` samples no ETA is
  shown at all, rather than one derived from a single run, and phase names are shared
  constants so a renamed stage loses its estimate instead of showing someone else's.
- **Keep a sample that is missing a phase.** A run that died in the model call still has
  a valid retrieval time; discarding it throws away a real measurement.
- **Progress time is measured in the CLI, not the service.** The backend takes an
  `emit(message)` callback and knows nothing about stages; timing is presentation, so it
  belongs with the display. It also stays correct if a stage is reordered.
- **A run is the unit of reading; a book is the unit of rating.** `/history` lists runs
  because a book is ambiguous on its own — reading one means reading the scenario it was
  written for. `/read` returns a full `Generation` (the same shape a cache hit produces)
  so the REPL has one rendering path, and it restores `book_files` so `/rate` and the
  legality warnings work as they do after a fresh generation. Before this, the only route
  back into a result was a cache path, which is unusable to type.
- **Reading must not depend on this session.** `/read <n>` falls back to resolving the
  number against the store when `/history` has not been run yet, because requiring a
  listing first would make the common case ("read the last one") fail confusingly.

### The API is transport, and only transport

`src/api/main.py` validates input, calls one service method, and maps a typed error to a
status code. Nothing else. A rule that lived in a route handler would be a rule the CLI
does not have, and the two front ends would drift within a week.

- **The real work is testable without a server.** `create_app(vector_db=, backend=,
  character_name=, cache_dir=)` takes its collaborators, so `TestClient(create_app(...))`
  exercises real routing, real serialisation and real error mapping against a fake index
  and a fake model. Without injection every API test would need the live index.
- **A wrong status code is a contract bug the front end hits**, and testing the service
  directly cannot catch it. There is one API test per error mapping for that reason.
- **4xx means "your request cannot work"; 5xx means "try again".** Retrying a 422
  (`NoEligibleSpells`) is pointless; retrying a 502 is not. Collapsing them into one code
  throws away the only thing the caller acts on.
- **Do not hand a browser a filesystem path.** `/api/history` first returned the run's
  cache directory, which a browser cannot use and which publishes the cache layout for no
  gain. A run is now identified by an opaque `id` (the directory name) that `GET /api/runs`
  resolves back. Reopening still accepts a scenario fragment too, so a caller that already
  knows what it wants can skip the listing.
- **Keep the CORS origin list explicit.** `allow_origins=["*"]` with
  `allow_credentials=True` is both rejected by browsers and a decision that should be
  made deliberately at deployment rather than inherited from a dev convenience.
- **The UI calls the API directly rather than through a Vite proxy.** A proxy would hide
  the CORS setup from the dev loop and only fail once deployed. Testing against the real
  origin means the CORS config is exercised every day.
- **Never let a smoke test write into real user data.** Exercising `POST
  /api/runs/{id}/rate` against the live server wrote a rating into `.cache/`. Restore what
  you touched, and prefer a request that only reads.

### Where a fake would hide the thing under test, keep the real path

`test_rules_answers_are_grounded_and_cached` stubs `rules.fetch_page`, not
`rules.gather`, because replacing `gather` would replace the cache lookup the test exists
to verify - the test would pass while proving nothing. Check what a patch removes before
using it. The same trap in another shape: a fake `LLM` that never raises means the
error-mapping tests never run.

### A front end must show where an answer came from

The most important piece of chrome in the UI is the source badge. A `sheet` answer is read
verbatim from the character YAML and cannot be wrong; a `model` answer is generated and
can be; a `rules` answer is quoted from the 2024 SRD. Showing one as another would let a
plausible guess look like a recorded fact, which is the exact failure the two-stage lookup
exists to prevent. `Answer.source` carries it and every screen renders it.

Two consequences worth keeping:

- **Do not fabricate data to satisfy a form.** The outcome row originally defaulted a
  rating to 3 when none was set, so selecting "won" recorded a score the user never gave.
  It now requires the rating first and says so.
- **Render the model's markdown; do not print it.** A history preview showing
  `**Book 1 — “X”**` reads as corruption, not as a preview. The renderer is hand-written
  for the subset actually emitted (headings, bold, italics, lists) rather than pulling in
  a general parser, because a general parser needs `dangerouslySetInnerHTML` and would put
  raw model output into the page as HTML.

### Choosing the model: one setting, inferred backend

`LLM_MODEL` picks the reasoning model for both backends. Which backend it means is
**inferred from the name**, not configured separately, because the conventions are
unambiguous: an OpenRouter id is `vendor/model` and always contains `/`, an Ollama name
is `name:tag` and never does.

- One setting is less to explain and less to get wrong than `LLM_MODEL` +
  `LLM_BACKEND`, which can contradict each other.
- An Ollama name wins **even when `OPENROUTER_API_KEY` is set**. That is the feature:
  a key can stay in `.env` for occasional use while local runs stay local and free.
- A remote id with no key cannot work, so it falls back to Ollama **and logs why**.
  Silently swapping models makes a typo look like a backend failure.
- `.env` values get stripped of quotes and whitespace - hand-edited files are commonly
  quoted, and a quoted name would otherwise be sent to the server verbatim.

The bug this replaced is worth remembering: the OpenRouter branch read the requested
model but the Ollama branch hard-coded `config.OLLAMA_MODEL`, so `LLM_MODEL` worked for
one backend and was **silently ignored** for the other. When one function handles two
paths, check both - and prefer threading the resolved value through over letting each
branch re-read the config.

Embeddings deliberately stay on Ollama: `nomic-embed-text` is local-only, so changing
the reasoning model must not change how the index was built.

### Ollama thinking models return empty responses

`qwen3.5:4b` is a *thinking* model. On a large prompt it can emit thousands of tokens
of hidden reasoning and return an **empty** `response` with `done_reason: "stop"` and
HTTP 200. The CLI therefore treats an empty completion as a failure and says so; a
silent empty print looks like a successful run. `_extract_text()` reads `content`,
which is empty, so an explicit check is required.

### Prompt size is a real limit

`context/` plus the pool is already ~8k tokens; the rule files alone are ~17k
characters. `prompts.prompt_budget_warning()` exists because overshooting a local
model's window shows up as an empty reply, not an error.

## Future Enhancements

- **Multi-Agent System**: Separate agents for different subsystems (DM assistant, item finder, etc.)
- **Context Learning**: Agents that learn from user preferences over time
- **Offline-First**: Agents that work without internet access
- **Collaborative Play**: Shared history between players in a party

### Terminal output: progress and markdown

The answers are markdown and were being printed raw, so the user saw `### Book 1` and
`**Cantrips:**`. `cli/render.py` converts them with `rich`.

- **Styling belongs to the CLI, not the backend.** The service returns markdown text;
  an API would serialise that as-is, so `render.py` is the only place that knows about a
  terminal.
- **Always degrade to plain text off a terminal.** `Console.is_terminal` is False when
  output is redirected, and printing ANSI escapes into a file or a test capture is
  worse than no styling. Both `render` and `StageProgress` check it.
- **A silent terminal is indistinguishable from a hang.** Fetching candidates embeds the
  scenario and generating an answer waits on the model, so `cli/progress.py` announces
  each stage. The backend takes a plain `emit(message)` callback, so it never imports
  `rich`.
- **Stages must be closed, not just opened.** `StageProgress` completes the previous
  stage on the next call and exposes `done()`/a context manager, so a crash mid-command
  cannot leave a spinner running.
