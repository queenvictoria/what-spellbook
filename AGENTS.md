# AGENTS.md

## AI Agent Configuration for Spellbook Recommendations

This document defines the AI agents that power the spell recommendation system.

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

1. **Feature Development**: Update relevant agent config in this file
2. **Testing**: Use the provided interfaces as test fixtures
3. **Documentation**: Keep agent prompts in sync with actual implementation
4. **Iteration**: Modify system prompts based on user feedback

## Future Enhancements

- **Multi-Agent System**: Separate agents for different subsystems (DM assistant, item finder, etc.)
- **Context Learning**: Agents that learn from user preferences over time
- **Offline-First**: Agents that work without internet access
- **Collaborative Play**: Shared history between players in a party
