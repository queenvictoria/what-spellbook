# AGENTS.md

## AI Agent Configuration for Spellbook Recommendations

This document defines the AI agents that power the spell recommendation system, and
records development learnings for anyone (human or agent) working on the repository.

### What this project actually is

A **Python core** that recommends D&D 5.5e (2024) spells for a scenario, with three
front ends over it: a `cmd.Cmd` REPL, a FastAPI HTTP API, and a React UI. Retrieval is a
local **Chroma** vector store holding the spell markdown files *and* the vendored 2024 SRD;
the model is reached through **LangChain** with OpenRouter or Ollama backends.

The TypeScript interfaces later in this file describe the **agent configuration shape**
from the original design. Where they disagree with the implementation, the
implementation wins - the wire contract the UI actually depends on is
`backend/api/schemas.py`, mirrored by hand in `frontend/app/api/types.ts`.

### Layout: one backend, three front ends

```
backend/
  libs/           rules, retrieval, prompting, caching - no terminal, no printing
    config.py       paths, models, tunables (+ resolve() for repo-relative paths)
    indexing.py     Chroma build/validate/rebuild (spells, items and the SRD)
    characters.py   sheet loading and the rules questions we ask of a sheet
    spells.py       spell parsing, eligibility filters, book-pick validation, doc types
    retrieval.py    candidate collection and prompt-block rendering
    prompts.py      prompt templates + context-file resolution
    cache.py        per-run/per-book result cache
    lookup.py       deterministic sheet answers (/c), duplicate-spell origins
    rules.py        2024 SRD retrieval for /? and the contextual menu (heading match,
                    selection match, index similarity, spell and invocation lookup, cache)
    srd.py          the SRD as browsable documents - heading tree, anchors, table
                    conversion, and the section list the index is built from
    timing.py       per-phase aggregation behind the ETA
    llm.py          backend selection, response normalisation, typed errors
    search.py       direct index search for inspection (filters, modes, facets)
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
  __main__.py     `python -m backend` runs the CLI
frontend/         React UI - its own package.json, vite.config.ts, tsconfig
  app/            the React source (not src/, because this is the front-end "app")
evals/            prompt scoring for the contextual menu - a dev tool, never imported by
                  backend/ and never run by pytest
```

There is deliberately no `src/`. Nothing here compiles, so a `src/` root only existed to
hold Python packages apart from non-Python ones - and it forced a `sys.path` bootstrap so
that `from backend import config` would work. The repo root is now the import root, which
is why every import is written in full as `backend.libs.<module>`.

**The rule that keeps this honest: `backend/libs` must not import `backend/cli` or
`backend/api`.** A test enforces it (`test_service_imports_without_a_terminal`). If the
backend ever needs a terminal or a request object, the other surfaces cannot reuse it.

`SpellbookService` is the seam. It does the work and returns dataclasses
(`Generation`, `Book`, `Answer`); it never prints, prompts or exits. The REPL renders
those objects; the API serialises them; the UI draws them. Errors are typed
(`NoEligibleSpells`, `llm.EmptyCompletion`, `llm.LLMUnavailable`,
`CharacterNotFound`, `RulesUnavailable`, `IndexUnavailable`) so each surface decides how
to report them - which is why the library no longer calls `sys.exit`.

**Import the real modules.** There is no compatibility shim any more: use
`from backend.libs import service, characters` and run with `python -m backend`.

### Separation of concerns - two different kinds of document

| Location | Contains | Does **not** contain |
| --- | --- | --- |
| `context/**/*.md` | Rules text injected into the **model prompt** | Code, architecture, sprint notes |
| `AGENTS.md` (this file) | **Development learnings** for building the scripts | Prompting context for the model |
| `data/characters/*.yaml` | A single character's actual values | Rules that apply to a whole class |

Keep these apart. A context file that knows a character's level, or an `AGENTS.md` that
carries spell rules, will both go stale in the wrong direction.

### How the three front ends relate

| Layer | May import | Must not |
| --- | --- | --- |
| `backend/libs` | stdlib, third-party, other `libs` modules | `backend/cli`, `backend/api` |
| `backend/cli` | `backend/libs` | `backend/api` |
| `backend/api` | `backend/libs` | `backend/cli` |

`api` and `cli` are **peers**, which is why `api` sits beside `cli` rather than inside
`libs`. Both are transport over `SpellbookService`; neither owns it. Nesting the API
inside the domain would have claimed the opposite, and made the layering test express
something structurally odd - a subpackage forbidden from touching its own parent.

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

### Imports must stay side-effect free

No side effects may run at import time - tests and tooling import the packages. Anything
expensive or destructive belongs inside a function called from `main()`:

- `ensure_db()` rebuilds the Chroma index. It must **not** run on import.
- `get_embeddings()` creates embeddings lazily.
- `get_observer()` is a **factory**. A second `Observer().start()` raises
  `RuntimeError: threads can only be started once`, so the watcher cannot be a
  module-level singleton.

The rebuild path deletes the index directory. When it ran at import scope, merely
importing the packages in a test could destroy the user's index. Refreshing the Chroma client
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

The original `main.py` held config, indexing, retrieval, prompting, caching, the watcher,
the LLM client, the REPL and the entry point. Splitting it surfaced traps worth recording -
and the shim kept to avoid a wide rename was itself the last one to go:

- **Moving code is not renaming it.** Helpers like `known_spells` were reached through
  `main.` by seven test files, so `main.py` became a shim re-exporting the old names. That
  bought a green suite immediately and cost a second migration later.
- **A shim rots silently.** It re-exports *names*, so it stops tracking the code the
  moment something changes behind it - and nothing fails, because the shim's copy still
  exists. When it was finally removed, three tests failed for real reasons: `main.Path`
  and `main.__file__` had never existed, and a `monkeypatch.setattr(main, ...)` had been
  patching a copy the code no longer reads. Retire a shim as soon as its reason to exist
  has passed; the longer it lives, the more of it is a lie.
- **Monkeypatching follows the module, not the shim.** Tests patched `main.CHARACTERS_DIR`
  and `main.CACHE_DIR`; once the code reads `config.CHARACTERS_DIR`, patching the shim's
  copy does nothing and the test silently hits the real directory. Fixtures must patch
  the module that *reads* the value. This is the nastiest class of refactor bug because
  the test still passes - it just stops testing anything.
- **A moved package needs its import root to move with it.** While the code lived in
  `src/`, `python -m src.cli.app` put only the repo root on `sys.path`, so `import backend`
  failed while `python main.py` worked - and `src/__init__.py` had to bootstrap `src/` onto
  the path so the three launch styles agreed. Deleting `src/` removed the problem rather
  than managing it: the repo root is the import root, and `backend.libs.x` resolves from
  any launch style. Nothing here compiles, so `src/` was never buying anything.
- **Do not add a launch form you cannot honour.** `python backend/app.py` looks reasonable
  and can never work: running a file directly puts *its own* directory on `sys.path`, not
  the repo root, so `import backend` fails. The file was deleted rather than documented,
  because a launch command that crashes is worse than one that does not exist.
- **A library must not call `sys.exit`.** Tests that asserted `SystemExit` were rewritten
  to assert the typed exception, and the exit code moved to the CLI boundary where
  `main()` can return it. That is what lets an API reuse the same code path.
- **Relative paths must resolve against the repo root, not the CWD.** `config.resolve()`
  exists so launching from another directory does not silently read a different index or
  character folder.
- **Do not keep private-name aliases for their own sake.** The shim exposed `_format_pool`,
  `_db_is_valid`, `_split_names` and friends so tests could keep using the old private
  spellings. Removing the shim proved they were only aliases: the tests now call the real
  public names (`format_pool`, `db_is_valid`, `split_names`), and nothing was lost.
- **Check a bulk rename for double substitution.** A regex pass that rewrote
  `src/backend` → `backend/libs` and then `from backend import` → `from backend.libs
  import` produced `backend.libs.libs` in prose, because the second rule re-matched the
  output of the first. Order the rules so later ones cannot match earlier results, and
  grep for the pattern (`libs.libs`) afterwards.

### Tests

- Run `.venv/bin/python -m pytest` from the repo root.
- `tests/conftest.py` fakes LangChain's LLM, retriever and vector store, so no model
  call or network access is needed.
- Fakes must match real signatures. The retriever fake takes
  `as_retriever(search_kwargs=None)` because that is what LangChain's real method
  accepts; a narrower fake lets broken calls pass.
- Opening a Chroma store rewrites metadata, so the sqlite mtime changes on every
  launch. That is normal, not corruption - do not assert on it.
- Anything that writes must be redirected. Cache tests monkeypatch `config.CACHE_DIR`;
  without that the suite writes `.cache/` into the working tree.

### Sources: 2024 only

**This project is 2024 rules only.** Every context file, prompt and ruling must cite the
2024 (5.5e) edition. The two editions disagree in ways that silently corrupt
recommendations, and a mixed corpus is worse than either one alone because the model
cannot tell which it is reading.

| Source | Edition | Note |
| --- | --- | --- |
| `context/srd/*.md` | **2024** | **The only rules source.** Vendored SRD 5.2.1, CC-BY-4.0. Also indexed into the vector store |
| `5e24srd.com` | 2024 | Superseded, and incomplete. Refused by `rules.check_source` |
| `5thsrd.org` | **2014** | **Do not use.** Its own banner points at 5e24srd.com |
| `dndbeyond.com` | mixed | Subclass text is behind a subscription |

`5thsrd.org` is the trap: it ranks well for "5e SRD" searches and looks authoritative, but
it serves the 2014 SRD 5.1. Do not cite it and do not fetch from it.

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

### Rules text is vendored, not scraped

`/?` used to fetch from `5e24srd.com` at query time. Two independent problems ended that:

- **Licensing.** SRD 5.2.1 is **CC-BY-4.0**, which explicitly permits copying,
  redistribution and adaptation with attribution. Scraping a site that republishes it gave
  no such permission. `context/srd/PROVENANCE.md` carries the required attribution;
  **do not remove it**, and do not add an SRD file without recording its source there.
- **The website is incomplete.** Verified by crawling every page for headings:
  Short Rest, Long Rest, the Grappled condition and the entire Rules Glossary were
  **absent**, and the pages that remained cross-referenced the glossary for their
  definitions. A rules answer drawn from it was systematically incomplete and could not be
  fixed by crawling harder.

**Use the PDF or the vendored Markdown; never scrape the HTML.** The official document is
<https://www.dndbeyond.com/srd>. `context/srd/` is the Markdown conversion of it.

`spells.md`, `classes.md`, `monsters*.md` and `magic-items.md` are deliberately **not**
vendored: this project's spell corpus and class rules already live in `data/` and
`context/`, and duplicating them creates two sources of truth that drift.

### The SRD is not the whole 2024 rulebook

It has no subclasses, few feats, and neither two-weapon fighting nor flanking. A rule
question can therefore have no answer, and refusing is the honest outcome - that is what
`RulesUnavailable` and an HTTP 404 report. **Do not** "improve" the matcher by lowering the
heading requirement: a plausible-looking wrong paragraph is worse than admitting the SRD
does not contain the rule, because the user cannot tell the difference.

### Browsing the SRD: a section knows where it sits

`backend/libs/srd.py` reads the vendored files as documents, and `Section.ancestors` is the
chain of headings above a section, outermost first, excluding the section itself. It is what
the breadcrumb on `SrdCard` is drawn from, and it is sent on the wire rather than left for
the client to derive: the client holds the table of contents and *could* walk it, but the
server already knows the path, and a second lookup for something already computed is a way
for the two to disagree.

- **Every vendored file has exactly one root heading, and it repeats the document title.**
  `rules-glossary.md` opens with `# Rules Glossary`, so a section directly under it would
  otherwise breadcrumb as "Rules Glossary / Rules Glossary". The root is dropped when it is
  the only ancestor *and* its text matches the title - not unconditionally, because a
  document whose root is a real subdivision would lose a crumb that means something.
- **The ancestry excludes the section itself.** The card already titles the section, so
  repeating it as the last crumb states it twice. The last crumb is the section, marked
  `aria-current="page"` and not linked, because a link to where you already are is a control
  that does nothing.
- **A crumb is a link, not a label.** Each carries the slug a click needs, so the trail is
  also the way to the parent rule - which is the other thing a reader wants from it, since
  the section that defines the terms this one uses is usually the parent.
- **`_trail` is a separate walk from `_find`.** They answer different questions and only one
  needs the path; folding them together would make a caller that wants the heading alone pay
  for a tuple it discards.
- **The trail is verified to resolve.** A test walks every ancestor of a real section and
  re-opens it by slug, so a crumb cannot point at a heading that is not there.

### How the matcher decides

The contract is that **the answer is found under a heading that names it**. A rule in the
SRD is defined under its own heading, so anything else - a mention, a cross-reference, an
equipment row - is not the rule. Three failures shaped this, all seen live:

- **A passing mention looked like the rule.** "What is a short rest?" matched *"mounts need
  a Short or Long Rest..."* in a travel-pace sentence, then *"Attune during a Short Rest"*
  in the magic-items page.
- **An equipment entry looked like a rule.** "How does grappling work?" matched
  **Grappling Hook** in a price list, because the rulebook says "Grappled" and the tool is
  named "Grappling Hook".
- **A generic word looked like the subject.** "How do I stabilize a creature" matched
  **Creature**, because a heading naming the generic *object* of the question scored the
  same as one naming its subject.

Three mechanisms now prevent these, and each is load-bearing:

1. **Heading-anchored matching** - a section qualifies only if some heading names it.
2. **Rarity weighting** (`rules.term_weight`) - terms are weighted by how many sections
   contain them, so "creature" and "spell" count for almost nothing and "cover" and
   "shove" identify the rule. Measured over section *bodies*, not headings: "creature" is
   rare in headings and everywhere in the text.
3. **A subject requirement** - the SRD must have a heading naming the question's most
   distinctive term, and that term must be distinctive enough to be a subject at all.

Two consequences worth remembering, because both look like bugs and are not:

- **A catalogue entry is excluded by its price pattern**, `Grappling Hook (2 GP)`. The
  pattern is deliberately just the price: every keyword tried (`armor`, `weapon`, `tools`)
  is also a real rule heading, and excluding those silently discarded "Armor Class",
  "Weapon Attack" and "Improvised Weapons".
- **Tables are converted, never stripped.** The rules live in them. `### Cover`'s prose
  only says "as detailed in the Cover table"; the +2 and +5 bonuses are in the markup.
  A converter that drops `<table>` leaves a confident answer with its numbers missing.

**This contract holds for questions, and only for questions.** A phrase highlighted in a
book is neither phrased in the SRD's words nor about something the SRD necessarily names
under a heading, so it takes a separate path - `rules.gather_from_selection`, which ranks by
how much of the selection's own vocabulary a section accounts for and always answers as
`rules-inferred`. Loosening the three mechanisms above to accommodate it would re-break
every failure they exist to prevent; see *A selection is not a question* below.

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
- Spell corpus: 544 markdown files, indexed as ~1280 chunks. The vendored SRD adds 2371
  more, for 3651 chunks in one collection - see *One collection, three kinds of text*.
- `markdown-it-py` needs `MarkdownIt("commonmark").enable("table")` to validate GFM
  tables; the `gfm-like` preset fails with `ModuleNotFoundError: Linkify enabled but
  not installed`.

### Front end tooling

- **Vite + React + TypeScript + Tailwind v4 + shadcn-style components**, in `frontend/`
  with its own `package.json`. It is a separate npm project, not a workspace.
- **Tailwind v4 has no `tailwind.config.js`** - the palette and base layer live in
  `frontend/app/index.css` under `@theme`. Adding a colour means adding a token there, not a
  config entry.
- **`baseUrl` is gone in TypeScript 7.** Path aliases work from `paths` alone; adding
  `baseUrl` fails the build with `TS5101`. The alias must also be mirrored in
  `vite.config.ts`, since Vite does not read `tsconfig.json` for resolution.
- **`erasableSyntaxOnly` is on**, so a constructor parameter property
  (`constructor(readonly x: T)`) is a build error. Declare the field and assign it.
- **The root `.gitignore` Node patterns are anchored with a leading `/`.** They existed to
  keep the retired root-level `node_modules` out; unanchored, they also ignored
  `frontend/package-lock.json`, which a front end must commit.
- Lint with `npx eslint app`, typecheck and build with `npm run build` (`tsc -b && vite
  build`). Both are clean and should stay that way.
- **A route that exists on disk can still 404 in the browser.** Vite serves `index.html`
  with a `?t=<mtime>` token pinned onto `main.tsx`, and that token is the key its transform
  cache is stored under. After an HMR failure the cache can keep a *pre-edit* transform
  under the token the page is still asking for, so the browser renders the old module while
  the file on disk is correct - the symptom is a nav tab that silently redirects, with no
  console error. Diagnose by comparing the two: `curl -s localhost:5173/app/App.tsx?t=<token
  from index.html>` against the same URL with a made-up token. The stale response is
  recognisable because its `createHotContext("/app/App.tsx")` has **no query string**.
  `touch` the file to force a re-transform, or restart the dev server. Do not go looking for
  a bug in the router - the router is fine.

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

### Searching the index is a different question from retrieving for a character

`backend/libs/search.py` and `GET /api/search` exist to answer "what is in the index, and
what does a query bring back" — not "what is legal for this character". It can return a
spell the character could never pick, on purpose, which is how a missing recommendation
gets explained. Nothing in the recommender calls it.

- **A class filter cannot be `$in`, and `$contains` does not work either.** `classes` is
  stored as one comma-joined string (`"Bard, Cleric, Wizard"`), so
  `{"classes": {"$in": ["Wizard"]}}` matches only the spells whose list is *exactly*
  `"Wizard"` — 119 of the 863 chunks that name Wizard. `$contains` looks like the fix and
  is worse: it returns **nothing at all**, silently, with no error. The only correct filter
  is an `$or` over the exact combinations that name the class, which is what
  `search._class_clause` builds. Verified against the live index, not assumed.
- **A filter that names a class the index never uses must match nothing.** Dropping the
  unsatisfiable clause would quietly widen the search to the whole collection, which is the
  one outcome a filter cannot have. The result says why instead.
- **`where_document` is case-sensitive and its `$and` is unreliable.** `{"$contains":
  "nonmagical"}` finds 32 chunks and `{"$contains": "Nonmagical"}` finds 5, so a text search
  must case-fold both sides — which is why text mode scans the returned documents in Python
  rather than pushing the match into Chroma. `$and` over two `$contains` clauses returned 0
  where the intersection of the two sets was also 0 but the union was 38, so the operator
  cannot be trusted to mean what it says.
- **A vector search has no relevance threshold.** `total_matching` therefore reports how
  many distinct spells the *filter* admits, not how many are relevant — and the response
  says so rather than implying a precision it does not have. Chroma's distance is not a
  percentage and its scale depends on the embedding model, so it is shown as a number only
  next to another number from the same query.
- **Echo the `where` clause back.** A filter that silently matches nothing is the commonest
  failure here, and the clause actually sent is the fastest way to see why. It is part of
  the response for that reason.
- **Text mode's AND needs an escape hatch.** A chunk is ~1200 characters, so two words can
  both be present in a spell yet never in the same chunk — "nonmagical armor" matches 0
  chunks strictly and 41 spells with `all_terms=false`. Returning an empty page that reads
  as a broken index is worse than a sentence saying which knob to turn, so the result
  carries a `note`.
- **`$in` with a large list is slow on the first call.** Filtering a query by all 544 spell
  names took 2.6s cold and 0.009s warm; the class filter's 56 `$or` clauses took 1.3s cold
  and 0.018s warm. Chroma caches the filter, so the first request after a restart is the
  slow one — do not read that as a regression.
- **The index holds 22 magic items at `level: -1`.** They share the collection with the
  spells, so `spells_only` defaults to true and `-1` is reported as "Not a spell" rather
  than leaking out as a negative level.

### One collection, three kinds of text

The index holds the spell corpus, the 22 magic items that share its directory, and the
vendored 2024 SRD. They share a collection because they are searched together, and they are
told apart by a `doc_type` of `spell`, `item` or `srd`. Every eligibility filter names the
type it wants.

- **`is_spell` cannot express "not a pick".** It was the only marker before `doc_type`, and
  it is `False` for a magic item *and* for an SRD section. A filter that asked only for
  "not a spell" would therefore have handed the recommender the rulebook. The two fields are
  kept because they disagree usefully: `doc_type` is the coarse kind, `is_spell` the narrow
  one.
- **A shared collection means a shared namespace.** An SRD section is named after its
  heading, and a heading can collide with a spell name — the SRD has a `#### Fireball` *and*
  the corpus has a Fireball spell. Keying a distinct row on the name alone folds the rule
  into the spell and reports one fewer row than exists, so the key includes `doc_type`.
- **For an SRD row the key is the section, not the heading text.** The SRD repeats headings:
  `classes.md` has six `Level 1: Spellcasting` sections, one per class. Keying on the text
  reported five of them as duplicates of the first — visible only as a count that was 108
  short of the 1274 headings on disk.
- **`Chroma.from_documents` adds to a collection; it does not replace it.** `ensure_db`
  resets first, but a direct `build_index` call did not, so building twice reported 7302
  chunks for a 3651-chunk corpus. `build_index` now resets unconditionally. A doubled index
  is invisible until a count looks wrong.
- **A placeholder value must not be reported as a real one.** An SRD row's `level` is 0
  because Chroma cannot filter on a missing key, and `level_label` would have called every
  rule a cantrip. A client cannot detect that — the row has no school either, so both fields
  that would give it away read as a cantrip's. It reports `Rule` instead, and the heading's
  own depth is kept separately as `heading_level` so a spell-level filter keeps one meaning.
- **`doc_type` supersedes `spells_only` rather than combining with it.** They are the same
  question at different resolutions, and honouring both makes `doc_type=srd` with the default
  `spells_only=true` match nothing at all.

### Indexing the SRD: chunk by heading, keep the tables

`context/srd/` is indexed one row per section, and the two conversions `rules` does for a
prompt are deliberately *not* reused:

- **Chunk by heading, not by the spell splitter.** A rule's identity is its heading:
  `### Cover` is the rule, and a chunk that began mid-table would be a fragment with no
  name. Sections longer than the chunk budget are split further, so a 1,750-line class
  chapter does not become one embedding that matches everything weakly. The heading is
  repeated in the chunk body, so a chunk split away from its heading still says what it is
  about.
- **Tables become Markdown pipe tables, never sentences.** `rules.tables_to_text` flattens a
  table into `header: cell; header: cell.` because a prompt cannot read markup. A reader can,
  and the numbers in a table *are* the rule — `### Cover`'s prose only says "as detailed in
  the Cover table", so a converter that dropped the markup would index a confident rule with
  its bonuses missing.
- **The file's own H1 is a title wrapper, not a section.** `# Classes` is immediately
  followed by `## Barbarian` and holds no text of its own, so indexing it added one row
  containing the entire 298KB chapter. Its children are indexed normally, and the document
  title is carried on every one of them anyway.
- **`srd.sections()` exists because `section()` re-reads the file.** Slicing all 1279
  headings one at a time would re-read and re-scan 880KB of Markdown 1279 times. The
  one-pass version computes each section's end with a stack, and a test asserts the two
  agree about where a section ends — if they drifted, a search hit would open a different
  rule than the one it matched.
- **A missing SRD directory is not an error.** The spell corpus is the index's reason to
  exist, so a checkout without the vendored rules still builds a usable index. It is logged,
  because a silently rule-less index is only noticed when an answer is wrong.

### The SRD is used in three places, and only one of them is a quotation

| Where | How | Labelled |
| --- | --- | --- |
| `GET /api/search?doc_type=srd` | Similarity or substring over the indexed sections | `srd` |
| `GET /api/rules` (last resort) | `rules.gather_from_index` — similarity, when both anchored paths refuse | `rules-inferred` |
| `POST /api/scenario` | `retrieval.gather_srd_context` — the rules the *scenario* turns on | retrieved context |

- **The index lane is reached last, and the anchor is left strict.** `rules.gather` and
  `rules.gather_inferred` are heading-anchored because the anchor is what stops a passing
  mention being quoted as the rule. Loosening either to accommodate a question phrased in
  other words would re-break every failure they exist to prevent. `gather_from_index` is a
  third path instead, and it is always labelled `rules-inferred` — a similarity hit is not a
  quotation, and the label is what makes answering one safe.
- **It buys recall, not precision.** "How do I stop someone running past me" shares no
  distinctive word with the heading that answers it (*Your Turn*), so no heading match will
  find it. Verified live against the rebuilt index.
- **Collapse chunks back to sections.** A chunk is a 1200-character window that can begin
  mid-table; the section is the rule, and it is what the prompt should quote. The chunk text
  is the fallback when the section is gone — the index can be older than the corpus, and a
  heading renamed since the last rebuild must not drop the hit.
- **The recommender's lane is grounding, not eligibility.** The pool decides what is legal
  and is filtered by `doc_type=spell`; the SRD block exists so the model does not supply
  "how does being grappled work" from memory, which is where a 2014 reading of it comes
  from. It is omitted entirely when empty, because a heading with nothing under it reads as
  "the rules are missing" and invites the model to fill the gap.
- **A scenario is not a question.** The heading-anchored matcher answers a question, and a
  scenario is a paragraph of prose with no single subject — requiring a heading to name it
  would return nothing. Similarity is the right shape here, and the result is labelled as
  retrieved context rather than as a quoted rule.
- **A fake that omits a method the code calls tests the fallback instead.** `FakeDB` had no
  `similarity_search_with_score`, so the vector paths silently took the retriever branch and
  the new lane looked like it worked while never being exercised. The fake now mirrors the
  real store's signature.

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
  (`CACHE_DIR_PATH`, `CONTEXT_DIR_PATH`, …).
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

### A conversation is a thread, not an answer

`.cache/conversations/<character>/<kind>-<slug>-<hash>.json` stores the ask surfaces —
`/c`, `/?`, the contextual menu and `/ask`. The rules cache answers *one question* and is
keyed on that question alone. That is the right shape for a lookup and the wrong shape for
a conversation: "and a grapple?" is only meaningful beside the question it followed. So a
file is a **thread**: the opening question, its kind, and every turn in order. The same
bargain `/history` makes for runs — a run is the unit of reading, a book the unit of
rating — applies here: a thread is the unit of reading, a turn the unit of provenance.

- **The opening question identifies the thread, not the latest one.** A follow-up joins
  the conversation it followed rather than starting a new one, so the id stays stable as
  the thread grows. The kind is part of the key because the same words asked of the sheet
  and of the rulebook are different questions with different answers.
- **A replay must be guarded, or it outlives the state it described.** The rules and
  selection surfaces already replay from their own answer caches. The character and refine
  surfaces had no cache at all, so a repeat re-ran the model. Storing the turn is what
  gives them the same behaviour — but only with a guard: a character answer carries the
  sheet's fingerprint and is a miss when the sheet changed, and a refinement carries the
  previous answer's fingerprint because refining different books with the same words is a
  different request. Without those, an edited sheet would keep serving advice for a
  character that no longer exists.
- **Second-precision timestamps cannot order a listing.** A thread's `updated_at` moves as
  it grows, and several turns are appended within the same second, so the saves tie and the
  order falls back to the id — a thread continued just now can sort below one that merely
  started just now. The conversation store uses microsecond precision for that reason; the
  run cache keeps seconds because a run is written once.
- **A replay is still a turn.** It is appended to the thread with `from_cache` set, so the
  history shows the exchange was revisited rather than pretending it never happened. The
  same reason a cached run is written before it is printed: the record is what a rating is
  attached to later.
- **Return the turn, not an `Answer`, when the caller needs more than the prose.** A
  refinement replay needs the stored `model` as well as the answer text, and rebuilding an
  `Answer` drops it. `_replay` returns the `conversations.Turn`; `_answer_from_turn`
  converts it for the surfaces that only want an `Answer`.
- **A thread is keyed on the scenario for a refinement.** `refine` is only meaningful
  beside the books it refines, so its opening is the scenario, not the question — and a
  replay lookup must pass that opening explicitly or it looks in the wrong file.

### The API is transport, and only transport

`backend/api/main.py` validates input, calls one service method, and maps a typed error to a
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
- **A client must rate by `run_id`, never by scenario text.** The backend accepts a
  scenario fragment as a convenience, and the front end used it — but `api.rate` already
  encodes its argument, so the screen's own `encodeURIComponent` double-encoded it and the
  request went to a run named `Three%2520kobolds…`. The star flashed on and off because
  the optimistic `setRating` was rolled back by the 404. The deeper problem is that a run
  is keyed on the scenario *and* the character, level and book count, so two runs can share
  a scenario and the wrong one gets rated. `POST /api/scenario` and `GET /api/runs/{id}`
  now both return `run_id`, and the UI passes it through.
- **Keep the CORS origin list explicit.** `allow_origins=["*"]` with
  `allow_credentials=True` is both rejected by browsers and a decision that should be
  made deliberately at deployment rather than inherited from a dev convenience. The list
  is derived from `FRONTEND_PORT` rather than hard-coded, because more than one copy of
  the dev server may be running on the same machine and a fixed list silently blocks the
  second one.
- **A spell name is not a filename.** Six corpus files are named after a different spell
  than they contain (`Confusion.md` holds Conjure Animals), so the page's own title is the
  authority and `spell_title` reads it. Keying the index on the filename files one spell's
  rules under another's name.
- **Never title-case a spell name.** `title()` capitalises every word, so "Ray of Frost"
  became "Ray Of Frost" and 77 spells containing a minor word stopped matching the prose —
  the mentions rendered as dead text with no error anywhere. It also breaks "Melf's Acid
  Arrow" into "Melf'S". The corpus stems are already spelled correctly.
- **An Eldritch Invocation is not a spell.** They are served by `/api/invocation` rather
  than folded into `find_spell`, because a class feature answering as if it were an SRD
  spell is a category error the caller cannot see. Their names still go in `/api/spells`,
  because the books name them in the same sentence as spells.
- **The invocation effect text is in `context/srd/classes.md`.** Our own
  `context/classes/warlock/` lists all 28 with their level and prerequisite but not what
  they do, so it is the fallback and reports `source: class-context`; the SRD is preferred
  and reports `vendored-srd-5.2.1`. The section is located by heading, because the chapter
  is 11,000 lines and the names are not distinguishable from any other `####` heading.
- **Vendoring a file can create a false positive, not just a gap.** Adding `classes.md`
  made "how does a spear work" resolve to "Eldritch Spear" — the Spear lives inside an
  equipment *table* with no heading, so the invocation was the only heading containing the
  word. `_qualifies` now rejects a heading qualified by a distinctive word the question
  never mentioned. Check what a new file *steals*, not only what it adds.
- **The UI calls the API directly rather than through a Vite proxy.** A proxy would hide
  the CORS setup from the dev loop and only fail once deployed. Testing against the real
  origin means the CORS config is exercised every day.
- **Never let a smoke test write into real user data.** Exercising `POST
  /api/runs/{id}/rate` against the live server wrote a rating into `.cache/`. Restore what
  you touched, and prefer a request that only reads.

### Browsing the SRD is not asking it a question

`rules` answers a question: it ranks sections by how well their headings name the subject
and quotes the winner. `srd` shows the rulebook, and the two needs are different enough to
be different modules.

- **A browser must be complete and stable; retrieval may be selective.** A question has one
  best answer, so ranking is fine. A table of contents that omitted a section is simply
  wrong, so `srd` walks every heading in document order and gives each a stable anchor.
- **Tables become pipe tables, not sentences.** `rules.tables_to_text` flattens a table to
  `header: cell; header: cell.` because a prompt cannot read markup. A reader can, and the
  numbers in a table *are* the rule - `### Cover`'s prose only says "as detailed in the
  Cover table", so a browser that dropped the table would show a confident rule with its
  bonuses missing.
- **Headings keep their level.** `rules.markdown_to_text` flattens every heading to `##` so
  the matcher sees one flat list. A browser needs the nesting, or `#### Attack [Action]`
  reads as a sibling of `## Actions`.

Four traps, each of which produced a plausible-looking wrong tree:

- **A BOM defeats the heading regex.** `spells.md` begins `\ufeff# Spells`, so the `#` is
  not at the start of the line. The symptom is quiet: the title falls back to the filename
  and looks right by luck, while the file's top-level sections become siblings of nothing.
  Strip the BOM before *scanning*, not just before rendering.
- **The SRD repeats headings, so a slug from the text alone collides.** `classes.md` has six
  `Level 1: Spellcasting` sections, one per class. Without de-duplication every link after
  the first opens the wrong class's feature. Slugs are numbered per document
  (`level-1-spellcasting-2`).
- **A heading inside a blockquote is not a section.** `> ### Breaking Your Oath` is quoted
  text inside a rule; anchoring it would put a Paladin's oath discussion in the table of
  contents as a sibling of the Paladin class. The scanner only matches a line that *begins*
  with `#`, which is exactly right.
- **The conversion mis-levelled three stat blocks, and the damage was 228 spells.** *Find
  Steed*, *Giant Insect* and *Summon Dragon* each carry a creature stat block whose name the
  conversion wrote as `##` while the spell owning it is `####`. `## Otherworldly Steed`
  therefore *closes* `## Spell Descriptions`, so the 121 spells after *Find Steed* - Fireball
  among them - became children of a steed's stat block. The tree still looked plausible,
  which is why this needs a test rather than a glance. `_repair_stat_blocks` fires only on
  the stat-block signature (a heading followed immediately by a deeper `#### Traits`, which
  appears nowhere else in the corpus) and moves the heading to the spell's own level. A
  general "fix the levels" pass would rewrite the class chapters, where a `###` after a
  `####` is the real structure.

Two smaller facts worth keeping:

- **Markdown has no colspan, and the class progression tables need it.** Their header has two
  rows, the second holding the spell-slot levels under a `colspan="9"` group label. Merging
  the rows column-wise keeps both - "Spell Slots per Spell Level 1" - where taking one row
  loses either the label or the levels. A span becomes its label plus empty neighbours, so
  every row stays the same width.
- **A table with no `<thead>` needs an empty header row, not a promoted first row.** The
  SRD's headerless tables are key/value blocks ("Primary Ability | Strength") and
  abbreviation grids, where the first row is data. Promoting it labels "Primary Ability" as
  a column heading.

The renderer widened with it, and the widening is shared: `Markdown.tsx` now handles pipe
tables, blockquotes (recursively, because an SRD sidebar contains its own heading) and
heading levels. That also fixed a pre-existing gap - 107 corpus files contain pipe tables
that were rendering as raw `|`-separated text.

### A printed path is an invitation to read the rule

Every answer in this app ends with the file it came from, and that path used to be dead
text. It is now a link that opens the rule in a drawer - the same affordance spells already
had, for the same reason: following a citation used to mean leaving the answer behind and
finding the heading by hand on the Rules tab.

Four things had to be true for that to work, and each was a separate bug:

- **A citation needs an anchor, not just a file.** `playing-the-game.md` is 65KB and
  `classes.md` 296KB, so a link to the file opens the book at the top and leaves the reader
  to find the rule. `rules._section_reference` derives the anchor from the heading that
  answered, and `srd.anchor` resolves a *name* to a slug because a spell's `url` is built
  from its own name. Both fall back to the bare file when there is no heading to point at -
  a promoted run-in label ("Ending a Grapple") is not a heading in the file, and a link to
  a section that does not exist is worse than a link to the book.
- **A cached citation is re-anchored on read, not trusted.** Entries written before
  citations carried anchors store the bare file, so a stored answer would open the rulebook
  at the top while a fresh one opened the rule. `_anchor_cached` derives the anchor from the
  passage's own first line, which the stored text already carries - so every existing entry
  is fixed without a `SCHEMA_VERSION` bump, which would have invalidated every cached answer
  and every rating for a cosmetic gain.
- **The service must use the re-anchored url, not the stored one.** `gather` returns the
  fixed url, but `ask_rules` read `cached["url"]` straight out of the file and threw it
  away. The symptom was a live server returning the old path while the same call in a
  Python shell returned the new one - which reads as "the reload did not happen" and is not.
- **Not every path is a rule.** A spell's footer may be `context/srd/spells.md` (the 2024
  SRD) or `data/reddit-spence_post/...` (the retrieval corpus). The corpus is not a
  rulebook page and has no headings to browse, so `srdInPath` returns null for it and the
  path stays plain text. A link that fails is worse than no link, because it looks like the
  rule is missing rather than like the path is not a rule.

The drawer is a sibling of the spell drawer rather than a child: a rule and a spell are two
readings of two different things, and nesting them would make one panel depend on the
other's state. It carries the tree as well as the rule, because the commonest next move
after reading one rule is reading the one beside it - sending the reader back to the tab to
click again would make the drawer a dead end.

### A selection is not a question

The contextual menu takes a phrase copied out of a generated book. It is the one input in
this project that is neither a question nor written in the rulebook's vocabulary, and every
existing path was built on the assumption that it is a question:

- `gather` requires a heading to *name* the subject. The SRD's heading for "2 beams" is
  **Cantrip Upgrade**; for "nonmagical plate" it is **Crafting Nonmagical Items**. In both,
  the words that identify the rule are in the section *body*, so the anchor refuses a
  selection that a reader is obviously pointing at.
- `gather_inferred` keeps the anchor and relaxes only the subject floor, so it refuses the
  same fragments.
- `ask_rules_contextual` tried those two and nothing else, so **every** realistic selection
  ended at "The 2024 SRD has no section matching…".

`rules.gather_from_selection` is a third path for exactly this, and the anchored paths are
deliberately left unloosened. What separates them is not permission but *labelling*: a
question is phrased in the rulebook's words and can be quoted, a selection names its subject
in the book's words and can only be interpreted. So a selection answer is always
`rules-inferred`, which is what makes answering one safe.

Three things were learned building it, and each changed the design:

- **Coverage is the gate, because a score threshold cannot be.** The first attempt reused
  the anchored scorer and required a minimum score. Measured against real selections, the
  right answer for "Help action" scored **1.66** and the right answer for "Thorn Whip"
  **0.58** - while a *wrong* answer for "how does two weapon fighting work" scored **0.84**.
  Any floor high enough to reject the wrong one also rejected a correct one, because the
  scorer measures how well a heading repeats the input, which is precisely the signal a
  selection does not carry. What does separate them is vocabulary: `_coverage` asks how much
  of the selection consists of words the SRD uses at all. A word it never writes weighs
  zero, so "Rust Metal" and "flanking" score near zero and are refused, while every fragment
  that needs this path clears 0.55.
- **The gate is length-sensitive, and that is a boundary worth stating.** A whole sentence
  has enough real words to clear any floor, so a sentence is let through even when the thing
  it names is absent from the SRD. Measured: "Rust Metal" alone is refused, "Rust Metal
  corrodes the fighter's plate and every other nonmagical metal object" is not. That is
  acceptable *because* it is bounded - only 400 characters of contact prose are ever sent,
  the answer is labelled `rules-inferred`, and the prompt requires naming the gap (the live
  model did: *"that part comes from your selected context, not from the retrieved SRD
  text"*). Nothing was available on 2024 - an embedding search would have the same
  property.
- **Weighted coverage beats aligned coverage for a multi-word phrase.** Scored on
  max-coverage alignment, "2 beams" preferred the honours-course **Spells** chapter - which
  contains both words once - over the **Eldritch Blast** section the words were copied from,
  since two words align equally well wherever both appear. Weighting by rarity and summing
  gives the section that accounts for *all* of the selection, which is the one that explains
  it.

### The plumbing, not the matcher, was most of the bug

Four independent failures sat between the highlight and the answer, and fixing only the
matcher would have left the feature just as dead. Each is a shape worth recognising:

- **A query parameter must match the name FastAPI declared.** The client sent
  `selectedText`, the route declared `selected_text`, and *every* request 422'd. Worse, the
  service path was correct, so any test at the service level passed; only a request through
  the real app could see it. `tests/test_api.py` now exercises the endpoint for that reason.
- **A ref read in an effect body is `null` and stays `null`.** `useSelection` did
  `const element = ref.current; if (!element) return`, and the ref object itself never
  changes - so the effect never re-ran and the hook reported "nothing selected" for every
  selection ever made. `RulesContextButton` then made it unfixable by passing
  `{ current: null }`, a ref that can never point at anything. Read the ref *inside* the
  listener. A hook that takes an element to watch also needs an element to watch: the button
  is now handed the book's prose container, and the selection is scoped to it.
- **A click that clears the selection before reading it sends an empty string.** The
  button's handler only called `clearSelection()`. The selected text has to be captured and
  handed to the drawer first; the drawer holds it, so the highlight can then be dropped
  without losing what was asked.
- **A component that renders `null` unconditionally cannot be debugged from the outside.**
  "The button never appears" had three separate causes stacked in one small component, and
  each hid the next. When a guard makes a component invisible, check the guard's input is
  ever non-empty before looking at the guard.

### A sentence about spells is not a question about a spell

The first working version of the contextual menu answered the reported session badly:

> The retrieved SRD text does not cover Thorn Whip, Repelling Blast, or forced movement…

…about a sentence that named both spells and stated what they do. Three faults stacked, and
only one was in the prompt:

- **A book writes about spells in words a spell's description does not contain.** "2d6 and
  pulls it 10 ft" is nothing like `_Level 0 Transmutation (Druid)_ ... 1d6 Piercing`, so no
  ranking over the *selection* reaches the spell. The names have to be resolved as documents.
- **Nothing told the model those documents existed.** They were not in the prompt at all.
- **No stage named the gap.** The answer confidently reported a missing rule, and there was
  nothing on screen to suggest a spell had never been attached.

`rules.mentioned_documents` and `rules.resolve_attachments` resolve a selection's mentions to
their own rules text, which is then sent as an `=== ATTACHED DOCUMENTS ===` block.
`Answer.attachments` reports the names back, and the drawer shows them as removable lozenges -
"what the model actually read" is part of the answer, because a missing attachment is
*invisible* in the answer text.

Four things this cost, each worth keeping:

- **Matching must be case-sensitive and whole-name.** 132 of the corpus's 544 spells are
  single common words, so matching against the corpus index (which is keyed on *folded* names)
  attached the **Light** cantrip to "the light of the fire". A bare substring test attached
  **Light** to "Daylight". The rule is `linkable_spell_names` (display spelling),
  case-sensitive, with letter/apostrophe boundaries and longest-name-first.
- **One mention rule, not two.** The front end already decided what a mention is - that is what
  makes a word a link. `rules._mentions` mirrors `frontend/app/lib/spellNames.ts`'s
  `buildSpellPattern` by hand, including its rule that a single-word name is rejected after a
  capitalised word (so the Celestial's *Healing Light* does not attach the Light cantrip).
  Two rules would eventually disagree about a faint mention, and the disagreement would be
  invisible. The UI passes its own resolved list so the two agree by construction, and the
  backend keeps the hand-written mirror only as a fallback for a caller that sends none.
- **The variable-width lookbehind does not port.** JS accepts `(?<![A-Z][a-z]+ )`; Python's
  `re` needs a fixed width and raises `PatternError: look-behind requires fixed-width pattern`.
  The preceding-word test is done in code instead.
- **An attached document is grounds to answer at all.** A selection made of vocabulary the SRD
  lacks ("Rust Metal corrodes the plate") used to refuse. That refusal is right for a
  *question*, but "Repelling Blast misses, so Thorn Whip pulls it" is a question about two
  spells, and their descriptions are the rules. Documents therefore rescue a refusal - and with
  no document the refusal correctly stands, which is still tested.

### Do not let a drag on a link become a click

Selecting prose across a spell mention is the *main* way this feature is used, and a browser
fires a `click` on the link when the mouse comes up on it after a drag. That navigated to the
rules tab and discarded the selection the reader was about to ask about.

There is no way to tell that click from a real one except by knowing the pointer moved, so
`SpellLink` records where the button went down and ignores a click that ended more than a few
pixels away. A few pixels of slop, because a hand on a mouse is not perfectly still.

### The prompt is an argument, so make it measurable

`evals/` scores the contextual prompts. It exists because the only feedback on a prompt change
is otherwise reading one answer and forming an impression, which is how a prompt gets worse
over time and nobody notices.

- **Each variant changes one thing**, so a moved score can be attributed. A variant that
  changed three would produce a number that moves and an explanation that does not.
- **A variant must *physically* omit a block it claims to omit.** `evals/variants.py`
  assembles from a `Blocks` switch rather than trusting a label. The first draft had a
  `Blocks` field that the builder ignored - it would have produced numbers that look like
  evidence and are not. `--dry-run` checks `must_attach` before the model runs for exactly this
  class of bug.
- **Check the answer is right about something only the attachment carries.** `1d6` for Thorn
  Whip is in that spell's text and nowhere else in the SRD, so the check cannot be satisfied by
  recall. A model-graded rubric would score better by pleasing the grader.
- **An answer that is right about a spell it was never given looks exactly like a good
  answer.** Nothing in the text can reveal it, which is why attachments are checked against the
  prompt.
- **A dry run must print no score.** The first version reported a confident `0.57` for variants
  that were never asked anything - the number was attachment checks, and the reader had no way
  to tell. It prints `(dry)` now.
- **Keep a case the current prompt fails.** `known_bad` marks one: an all-green suite measures
  nothing.

The surrounding sentence is sent with the selection, and it reaches **the prompt only, never
retrieval**. A fragment is ambiguous in exactly the way its sentence resolves it ("2 beams"
could be any spell), but the selection is what was asked about - letting a sentence steer the
search answers the book's prose instead of the phrase the reader highlighted. The *source
badge* still does the real work, and the live run shows why: the answer quoted the SRD for
the beams and then said plainly that the Repelling Blast wording came from the selection.

### A book is delimited, not inferred

The model used to write each book as prose with its own heading, and the reader had to work
out where one book ended. It now writes explicit sections:

```
=== PREAMBLE ===
=== BOOK 1 ===
Title: ...
Cantrips: ...
Rituals: ...
How to use:
<prose>
=== PAIRINGS ===
```

`cache.split_answer()` returns `{"preamble", "books", "pairings"}` and is the only parser;
`split_books()` delegates to it so the two can never disagree about where a book ends. The
title and picks are read as *data* - `Title:`, `Cantrips:` and `Rituals:` are single lines -
so the panel renders them from fields rather than stripping them out of the prose.

**The reason is a collision, not tidiness.** The model's trailing summary was written in the
same shape as a book heading - `**Book 3 pairs with:**` - so the parser read it as a fourth
book and left the real summary recited inside the last one. Book 3 literally ended with
"Book 1 pairs with... Book 2 pairs with... Book 3 pairs with...". `_is_book_heading` existed
to reject exactly those lines and was load-bearing in **6 of 12 stored runs**. A delimiter can
never be prose, so the collision is gone structurally rather than by heuristic.

- **A format change needs a fallback, and the fallback needs a parity check.** Every stored
  run is in the old format and carries real ratings, so `_legacy_split` stays. It was verified
  by parsing all 12 stored runs through both paths and comparing names, indices and picks.
- **Recover what the old format lost, but only where it is unambiguous.** A legacy summary is
  recovered when the model gave it a *markdown heading* of its own - 7 of the 12 runs did.
  A bolded label (`**4. Pairings and invocations**`) is deliberately **not** accepted: the
  vocabulary that identifies a summary ("pair", "invocation", "existing") also appears in a
  book's own prose, and the bold pattern matched `**Book 1 - Rust-Monster Triage / Armor
  Repair**` on the "pair" inside "Repair". Truncating a real book to recover one summary is
  the worse trade.
- **Derive on read rather than migrating.** A legacy run has no `pairings` key, so
  `service._stored_sections` re-splits its *response* to recover one. The books themselves are
  **not** re-cut - they were already recorded, and a parser change must not silently re-split
  an answer that was already written.
- **Deriving a field is not enough if the text it came from is still rendered.** The first
  version showed the legacy summary twice: once as the pairings card and once still inside the
  last book's recorded text. `service._trim_legacy_summary` trims it, sharing
  `cache.legacy_summary_heading` with the parser so the two cannot disagree about where the
  summary is.
- **Record the book count at write time.** `save_run` stores `book_count`, because a run saved
  without it had no record of how many books to expect - so a book deleted from the *end* of a
  set looked complete and the reader was shown fewer books than the model produced. Contiguity
  of the indices catches a deletion from the middle; only a count catches one from the end.
- **An added optional field is not a schema change.** `preamble` and `pairings` were added
  without bumping `SCHEMA_VERSION`, because a reader already treats a missing key as "no data".
  Bumping would have invalidated every cached run and every rating for nothing.
- **The prompt is where compliance is won.** The template is a worked example with the
  delimiters spelled out, and it says why they matter ("they are how the answer is split into
  books"). The live run followed it exactly on the first attempt - preamble, three books,
  pairings, no spurious fourth book.

### Where a fake would hide the thing under test, keep the real path

`test_rules_answers_are_grounded_and_cached` stubs only the model call and runs real
retrieval, because replacing `gather` (or the file reader beneath it) would replace the
cache lookup the test exists to verify - the test would pass while proving nothing. Check
what a patch removes before using it.

There is a subtler version of the same trap, and it cost real time: stubbing the *corpus*
changes the term-frequency model the matcher ranks headings with, so a test that fakes the
SRD is not testing the matcher at all. It asserts whatever a one-line corpus implies. Where
a test needs the corpus, use the real files.

The same trap in another shape: a fake `LLM` that never raises means the error-mapping
tests never run.

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

### A spell card is about a character, not just a spell

`SpellSchema.scaling` carries what the spell does at the **loaded character's** level -
`2 beams (L5)` for a level 5 Warlock's Eldritch Blast. The spell's text states its scaling
as a table ("two beams at level 5, three beams at level 11"), and a reader at the table
wants the row that applies to them.

It is a field of its own rather than folded into `text`, because it is the one value on
the card that is *this app's reading of a rule applied to a sheet* rather than the rule
itself. The card renders it as a badge beside the name, which is what says it is about the
character.

- **Read it out of the spell's own words; do not ask a model to restate it.** The value is
  already written in the file, and a model asked to restate a damage die can restate it
  wrongly. `spellstats.scaling()` parses it, and the fast model is only the fallback.
- **The label is the character's level, not the level the value was stated at.** A level 10
  caster is shown the level 5 row labelled `(L10)`, because that is what they deal.
  Labelling it `(L5)` would read as a level they are not.
- **Below the first stated level there is no note.** A cantrip at level 3 has not upgraded,
  and showing it the level 5 row states a number the character cannot cast yet. This is the
  case a "nearest level" implementation gets wrong, and it is invisible because the note
  still looks plausible.
- **A slot-scaled spell gets no note.** A Warlock's slots are all one level, so "for each
  slot level above 3rd" has a single answer for them and it is the spell's own text.
- **The gate is the gap, not "mentions a level".** Every levelled spell's header line names
  its own level, so gating on that would spend a model call on all 539 of them. Only a
  spell whose text states a level-based change that the parser could not read is worth a
  call - measured over the corpus, that is exactly two: Booming Blade and Green-Flame
  Blade, which scale in prose rather than in a table.
- **A failure to produce the note is not an error.** It is an addition to a card whose text
  is read straight from a file, so a model failure, a missing sheet or a sheet with no level
  all yield `None` rather than a 404 or a broken card. `_scaling_for` in the API makes the
  same bargain for a sheet that cannot be read.
- **Size the length cap to the real answers, not to the example.** `_MAX_NOTE` rejects a
  model that answered with a sentence instead of a phrase, and it was set to 60 characters
  from the short example ("2 beams"). Both prose cantrips this path exists for have a
  *two-part* upgrade and answer in 45-106 characters, so the cap silently discarded every
  real reply - Green-Flame Blade looked like a spell that does not scale, and nothing
  anywhere said why. The sentence it must reject runs to 149. Measure the answers before
  choosing the number, and check the badge can render the longest one: `whitespace-nowrap`
  on the badge pushed a 106-character note out of the card until it was allowed to wrap.

Two parsing traps, both found by testing against the real corpus rather than a sample:

- **A scaling list names its level once.** `levels 5 (2d10), 11 (3d10), and 17 (4d10)` -
  reading only the labelled form made every cantrip report its level 5 value at level 11
  and 17 as well. The first entry is read with its label and the rest as bare numbers.
- **The corpus omits the `Cantrip Upgrade` label on 4 of its cantrips** and writes the
  levels as ordinals (`5th level (2d6)`). A bare paragraph is accepted, but only when it
  states a level *and* a value *and* says something increases - otherwise "regains hit
  points from a spell of 1st level or higher" reads as scaling and puts a note on a spell
  that does not scale.

#### The note is cached on the character and level, and the run cache is not

`.cache/scaling/<character>/<level>-<spell>-<hash>.json` holds one small entry per spell per
level. It is a **separate store from the runs**, keyed differently on purpose, and the
difference is the whole point:

- **A run is keyed on the sheet fingerprint; a note is keyed on the name and the level.**
  `cache.character_fingerprint` exists because an edited sheet gives different advice at the
  same level, so a cached run must not be replayed. A scaling note is not like that: "Eldritch
  Blast has two beams at level 5" depends on the spell and the level and on nothing else.
  Fingerprinting the sheet here would throw away a perfectly good note every time a spell was
  prepared - the cache would miss on nearly every run and look like it was not working.
- **Only the model's answer is cached.** The deterministic read is free and is left uncached,
  because a stored copy of it would go on being served after the corpus changed underneath it.
  The cache wraps the `llm.invoke` call and nothing else.
- **A stored `None` is a hit, not a miss.** "This spell does not scale" is a real answer that
  cost a model call to obtain, so `load_scaling` tests for the *presence* of the `note` key
  rather than its truthiness. Conflating the two is what makes a cache recompute forever.
- **A failure is not cached.** Storing one bad call would make it permanent for that character
  and level, and the next attempt - which might succeed - would never happen.
- **`SCALING_VERSION` retires notes a reader fix would now read differently.** This is not
  hypothetical: the level-list bug above meant every cantrip reported its level 5 value at
  levels 11 and 17, and a stored note would have gone on doing so with nothing to notice.
- **The name is hashed whole, not slugged.** The slug is for a human browsing the directory
  (`scaling/lois/5-eldritch-blast-…`); the hash is what identifies the entry, so two names
  that slug to the same thing cannot collide.
- **Saving never raises.** A note is an addition to a card, so a cache that cannot be written
  is logged and dropped rather than failing the lookup it was meant to speed up - the same
  bargain the model call already makes.

Measured live: the first `Booming Blade` request took 1.9s and wrote one entry; the next
three took 0.01s each. A level 11 sheet and a second character each missed and wrote their
own entry, which is the key working.

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

`LLM_MODEL_FAST` is a **second, independent** setting, not a modifier on the first, and
it routes by the same name-based inference. The two do different jobs: the reasoning
model writes a whole recommendation and is worth waiting for, while the fast one answers
a one-line question about a spell. Unset means "no separate fast model" and the main
model is used, so the setting is optional. `llm._build()` is shared by both builders so
the two cannot disagree about how a backend is reached - which is exactly the bug the
single-setting version had.

### A token cap sized to the answer truncates a reasoning model to nothing

`FAST_MAX_TOKENS` cannot be as small as the answer it is meant to bound. The configured
fast model is a *reasoning* model: it spends hidden reasoning tokens before writing
anything, and `max_tokens` caps those too. Measured over 8 calls on one prompt:

| cap | empty completions | reasoning tokens observed |
| --- | --- | --- |
| 200 | **3 / 8** | 141-200 (the cap) |
| 512 | 0 / 8 | 177-657 |
| 1024 | 0 / 8 | 178-483 |

At 200 the reasoning alone consumed the whole budget and the response was truncated
before a single word of the answer, with `finish_reason: "length"` and HTTP 200. This is
the same failure as the Ollama thinking model below, reached from the other direction:
there the budget was too small for the reasoning, here the cap was. **Size a cap to the
reasoning plus the answer, and check `finish_reason` when a completion comes back
empty** - `length` means the cap, `stop` means the model genuinely said nothing.

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
`**Cantrips:**`. `backend/cli/render.py` converts them with `rich`.

- **Styling belongs to the CLI, not the backend.** The service returns markdown text;
  an API would serialise that as-is, so `render.py` is the only place that knows about a
  terminal.
- **Always degrade to plain text off a terminal.** `Console.is_terminal` is False when
  output is redirected, and printing ANSI escapes into a file or a test capture is
  worse than no styling. Both `render` and `StageProgress` check it.
- **A silent terminal is indistinguishable from a hang.** Fetching candidates embeds the
  scenario and generating an answer waits on the model, so `backend/cli/progress.py` announces
  each stage. The backend takes a plain `emit(message)` callback, so it never imports
  `rich`.
- **Stages must be closed, not just opened.** `StageProgress` completes the previous
  stage on the next call and exposes `done()`/a context manager, so a crash mid-command
  cannot leave a spinner running.
