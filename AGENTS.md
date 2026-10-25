# AGENTS.md

## AI Agent Configuration for Spellbook Recommendations

This document defines the AI agents that power the spell recommendation system, and
records development learnings for anyone (human or agent) working on the repository.

### What this project actually is

A **Python CLI** (`main.py`, `cmd.Cmd`-based REPL) that recommends D&D 5.5e (2024)
spells for a scenario. Retrieval is a local **Chroma** vector store of spell markdown
files; the model is reached through **LangChain** with OpenRouter or Ollama backends.

The TypeScript interfaces later in this file describe the **intended web app shape**
(see `ARCHITECTURE.md` / `ROADMAP.md`, both aspirational - no front end exists yet).
Treat them as the target interface, not as the current implementation.

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

Prompting context lives in `context/`, laid out as `context/[class]/[pact|subclass]/`:

```
context/
  spells.md                       # class-agnostic casting economy
  warlock/
    base.md                       # class-wide: progression, Pact Magic, invocations
    pact/tome.md                  # Pact of the Tome / Book of Shadows
    subclass/celestial.md         # Celestial Patron
```

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

### Tests

- Run `.venv/bin/python -m pytest` from the repo root.
- `tests/conftest.py` fakes LangChain's LLM, retriever and vector store, so no model
  call or network access is needed.
- Fakes must match real signatures. The retriever fake takes
  `as_retriever(search_kwargs=None)` because that is what LangChain's real method
  accepts; a narrower fake lets broken calls pass.
- Opening a Chroma store rewrites metadata, so the sqlite mtime changes on every
  launch. That is normal, not corruption - do not assert on it.

### Sources: 2014 vs 2024 SRD

The editions disagree in ways that silently corrupt recommendations:

| Source | Edition | Note |
| --- | --- | --- |
| `5e24srd.com/classes/warlock.html` | **2024** | Correct. The `.html` extension is required - the extension-less URL 403s |
| `5thsrd.org` | **2014** | Its own banner points at 5e24SRD.com |
| `dndbeyond.com` | both | Subclass text is behind a subscription |

Concrete divergence at level 5: 2014 gives **3 invocations and Pact of the Tome free**;
2024 gives **5 invocations with Pact of the Tome costing one**. The progression shape
differs too - 2014 grants **0 invocations at level 1** and uses "Spells Known", while
2024 grants **1 invocation at level 1** and uses "Prepared Spells". Cite the edition
whenever a rule is written into a context file.

The 2024 SRD contains **only the Fiend Patron**. Other 2024 subclasses (Celestial,
Archfey, Great Old One) have no free SRD page; use the 2024 class data (`XPHB` source)
rather than a wiki. Note that patron features do move between editions - the 2014
Celestial lists Healing Light at level 1 and Searing Vengeance as self-only, whereas
2024 moves Healing Light to level 3 and lets Searing Vengeance rescue an ally.

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
- `context/` is currently **not loaded into any prompt** by `main.py`. The files are
  inert until retrieval/loading is wired up. Do not assume editing them changes output.
- Spell corpus: 544 markdown files, indexed as ~1280 chunks.
- `markdown-it-py` needs `MarkdownIt("commonmark").enable("table")` to validate GFM
  tables; the `gfm-like` preset fails with `ModuleNotFoundError: Linkify enabled but
  not installed`.

## Future Enhancements

- **Multi-Agent System**: Separate agents for different subsystems (DM assistant, item finder, etc.)
- **Context Learning**: Agents that learn from user preferences over time
- **Offline-First**: Agents that work without internet access
- **Collaborative Play**: Shared history between players in a party
