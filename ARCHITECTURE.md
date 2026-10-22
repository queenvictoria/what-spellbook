# RAG-Based Architecture for Spellbook Recommendations

## Overview

This document outlines the architecture for the RAG-based MVP implementation of the D&D spell recommender system.

## Frontend: React + Vite

### Why React + Vite?

1. **AI/Accelerated Development**: React has the largest ecosystem for AI/ML web apps
2. **TypeScript Support**: Strong typing for complex spell recommendation logic
3. **Component-Based**: Easy to build modular spell/character UI components
4. **Vite**: Lightning-fast dev server and build tool
5. **Mobile-Optimized**: React Native alternatives exist if needed later

### Project Structure

```
what-spellbook/
├── src/
│   ├── components/
│   │   ├── CharacterSelector.tsx
│   │   ├── SpellRecommender.tsx
│   │   ├── SpellList.tsx
│   │   ├── HistoryView.tsx
│   │   ├── Editor.tsx
│   │   └── ui/ (common UI components)
│   ├── services/
## Backend Strategy: Client-Side Only (MVP)

### Why No Backend?

1. **Simpler Deployment**: Single HTML file, no server setup
2. **Faster Development**: Remove API gateway and server orchestration
3. **Data Privacy**: User's spell list and scenarios never leave their device
4. **Easier for Players**: No server configuration needed
5. **Lower Latency**: Direct browser API calls for RAG

### Architecture: Browser-First RAG

```
┌─────────────────────────────────────────────────────────────┐
│                         Browser                             │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │ Character   │───▶│ Spell Parser │───▶│ Ruleset     │    │
│  │ Selection   │    │              │    │ Manager     │    │
│  └─────────────┘    └──────────────┘    └──────────────┘    │
│         │                                                      │
│         │                                                      │
│  ┌──────────────────────────────────────────────────────┐    │
│  │               RAG Pipeline                           │    │
│  │  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐│    │
│  │  │ Embeddings  │───▶│ Vector Store │───▶│ Retrieval   ││    │
│  │  │ (ST.js)     │    │ (ChromaDB)   │    │ (Similarity)││    │
│  │  └─────────────┘    └──────────────┘    └─────────────┘│    │
│  └──────────────────────────────────────────────────────┘    │
│         │                                                      │
## RAG Components

### 1. Embeddings Layer

**Tool**: SentenceTransformers.js (onnxruntime-web or @xenova/transformers)

```typescript
// src/services/rag/embeddings.ts
import { pipeline, env } from '@xenova/transformers';

// Auto-download models once
env.allowLocalModels = false;
### 2. Vector Store

**Tool**: ChromaDB (browser version via jsbindings)

```typescript
// src/services/rag/vectorStore.ts
import { ChromaClient } from 'chromadb';

const client = new ChromaClient({ path: '/chromadb' });

export async function createSpellCollection(spells: Spell[]) {
  const collection = await client.getOrCreateCollection({
    name: 'spells',
    metadata: { description: 'D&D spells with embeddings' }
  });

  const embeddings = await Promise.all(
    spells.map(async (spell) => {
      const embedding = await getEmbedding(spell.description, embeddingModel);
### 3. Retrieval Strategy

**Hybrid Approach**: Semantic + Rule-based

```typescript
// src/services/rag/retriever.ts
import { retrieveSpells } from './vectorStore';

export async function retrieveRelevantSpells(
  query: string,
  context: {
    character: Character;
    ruleset: Ruleset;
    availableSpells: Spell[];
  }
) {
  // 1. Semantic retrieval for context
### 4. LLM Integration

**API**: GLM-4.7-flash (via ZhipuAI SDK or direct fetch)

```typescript
// src/services/rag/llmService.ts
interface LLMConfig {
  apiKey: string;
  model: 'glm-4.7-flash';
}

interface RAGPrompt {
  query: string;
  retrievedContext: string;
  characterContext: string;
  ruleset: string;
}

export async function generateRecommendations(prompt: RAGPrompt) {
  const messages = [
    {
      role: 'system',
## Knowledge Graph Considerations

### Notes for Future Enhancement

The following knowledge graph concepts are noted for future consideration:

| Concept | Description | Implementation Approach |
|---------|-------------|--------------------------|
| **Spell Ontology** | Hierarchical structure of spells (cantrips, 1st level, etc.) | RDF/JSON-LD with properties like `is_child_of`, `belongs_to_class` |
| **Rule Relationships** | Dependencies between rules and spell effects | Graph nodes with edge types: `causes`, `prevents`, `modifies` |
| **Class/Background Graph** | Connections between classes and backgrounds | Knowledge graph with `character_of`, `background_of`, `subclass_of` |
| **Item Spell Synergy** | How magic items affect spell selection | Edge types: `enables`, `requires`, `enhances`, `limits` |
| **Scenario Clustering** | Group similar scenarios for template recommendations | Graph clustering for pattern recognition |

### Potential Graph Schema

```
[Spell] --(has_level)--> [Level]
[Spell] --(of_class)--> [Class]
[Spell] --(with_tag)--> [Tag]
## Development Priorities (MVP)

### Phase 1: Core RAG Setup
1. Initialize React + Vite project
2. Set up TypeScript configuration
3. Configure ChromaDB in browser
4. Load SentenceTransformers.js embedding model
5. Create spell parser for markdown rulesets

### Phase 2: RAG Pipeline
1. Build vector store with spell embeddings
2. Implement similarity retrieval
3. Create retrieval filters (level, class, tags)
4. Test with sample spell lists

### Phase 3: LLM Integration
1. Set up GLM-4.7-flash API calls
2. Build RAG prompt construction
3. Handle response parsing and validation
## Storage Strategy

### LocalStorage Schema

```typescript
// src/services/storage.ts
interface StorageData {
  characters: Character[];
  rulesets: Ruleset[];
  spellLists: SpellList[];
  scenarios: ScenarioHistory[];
  userPreferences: {
    theme: 'light' | 'dark';
    defaultRuleset: string;
## Key Files to Create

- `package.json` - Dependencies and scripts
- `src/services/rag/` - RAG implementation
- `src/components/` - UI components
- `src/stores/` - State management
- `src/utils/` - Utilities and constants
- `.env.example` - API key configuration

## Migration Path

### From MVP to Full System

1. **Server-Side RAG**: Move vector database to server for larger spell lists
2. **API Gateway**: Create REST API for client-server communication
3. **Cloud Sync**: Implement encrypted sync with cloud storage
4. **Knowledge Graph**: Add Neo4j for complex spell relationships
5. **Multi-Agent**: Separate agents for different recommendation tasks

---

*Last updated: 2024-10-22*
## Dependencies (Proposed)

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "zustand": "^4.4.7",
    "@xenova/transformers": "^2.15.0",
    "chromadb": "^0.4.22",
    "@tanstack/react-query": "^5.12.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "@types/react": "^18.2.0",
    "typescript": "^5.3.0"
  }
}
```
    maxHistory: number;
  };
}
```

### JSON Export/Import

```typescript
export function exportData() {
  const data = getStorageData();
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  // Trigger download
}

export async function importData(file: File) {
  const text = await file.text();
  const data = JSON.parse(text);
  // Validate and save to localStorage
}
```
4. Implement caching for frequent queries

### Phase 4: UI Integration
1. Character selector and editor
2. Scenario input and history
3. Recommendation display with cheatsheets
4. Storage (localStorage) with JSON export

### Phase 5: Polish
1. Mobile optimization
2. Error handling and fallbacks
3. Performance tuning
4. Documentation and testing
[Class] --(has_subclass)--> [Subclass]
[Class] --(compatible_with)--> [Background]
[Background] --(affects)--> [Ability]
[Item] --(with_tag)--> [Tag]
[Item] --(affects)--> [Spell]
[Rule] --(applies_to)--> [Spell]
```
      content: `You are a D&D 5.5e spell recommendation assistant...

Your task: Analyze the scenario and recommend appropriate spells.

Context from RAG: ${prompt.retrievedContext}
Ruleset: ${prompt.ruleset}
Character: ${prompt.characterContext}

Format your response as JSON with:
- recommendations: array of spells
- rationale: string
- cheatsheet: object
`
    },
    {
      role: 'user',
      content: prompt.query
    }
  ];

  const response = await fetch('https://open.bigmodel.cn/api/paas/v4/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: 'glm-4.7-flash',
      messages,
      temperature: 0.3,
      max_tokens: 4000
    })
  });

  return await response.json();
}
```
  const retrieved = await retrieveSpells(query, 10);

  // 2. Rule-based filtering
  const availableIds = context.availableSpells.map(s => s.id);
  const matchedSpells = retrieved.filter(spell => 
    availableIds.includes(spell.id)
  ).slice(0, 5);

  // 3. Apply character-level constraints
  return matchedSpells.filter(spell => 
    canCharacterCast(spell, context.character)
  );
}
```
      return { id: spell.id, embedding, metadata: spell };
    })
  );

  await collection.add({ embeddings });
}

export async function retrieveSpells(query: string, k: number = 5) {
  const queryEmbedding = await getEmbedding(query, embeddingModel);
  const results = await collection.query({ queryEmbeddings: [queryEmbedding], nResults: k });
  return results.documents[0];
}
```
env.useBrowserCache = true;

export async function loadEmbeddingModel() {
  return await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2');
}

export async function getEmbedding(text: string, model: any): Promise<number[]> {
  const output = await model(text, { pooling: 'mean', normalize: true });
  return output.data as number[];
}
```
│         │                                                      │
│  ┌──────────────────────────────────────────────────────┐    │
│  │               LLM Integration                         │    │
│  │  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐│    │
│  │  │ RAG Context │───▶│ Prompt      │───▶│ LLM API     ││    │
│  │  │ (Retrieved) │    │ Construction│    │ (GLM-4.7)   ││    │
│  │  └─────────────┘    └──────────────┘    └─────────────┘│    │
│  └──────────────────────────────────────────────────────┘    │
│         │                                                      │
│         ▼                                                      │
│  ┌─────────────┐                                              │
│  │   Response  │                                              │
│  └─────────────┘                                              │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌─────────────┐
  │ LocalStorage│
  └─────────────┘
```
│   │   ├── rag/
│   │   │   ├── embeddings.ts (SentenceTransformers.js)
│   │   │   ├── vectorStore.ts (ChromaDB)
│   │   │   ├── retriever.ts
│   │   │   └── llmService.ts (GLM-4.7-flash API)
│   │   ├── storage.ts (localStorage)
│   │   └── types.ts
│   ├── stores/
│   │   ├── characterStore.ts
│   │   ├── historyStore.ts
│   │   └── uiStore.ts
│   ├── utils/
│   │   ├── spellParser.ts
│   │   ├── rulesetManager.ts
│   │   └── constants.ts
│   └── App.tsx
├── public/
│   ├── rulesets/
│   └── embeddings/
├── package.json
└── vite.config.ts
```
## Architecture Decision Summary

| Decision | Recommendation | Rationale |
|----------|----------------|-----------|
| **Frontend Framework** | React + Vite | Mature ecosystem, great TypeScript support, fast dev experience |
| **Backend** | Client-side only (MVP) | Simpler deployment, faster iteration, data privacy |
| **Vector Database** | ChromaDB (embedded) | Easy to use, browser-compatible, good performance |
| **Embeddings** | SentenceTransformers.js | Lightweight, good quality, runs in browser |
| **LLM API** | GLM-4.7-flash directly from client | No server needed, simple integration |
| **State Management** | Zustand | Simple, TypeScript-friendly, no boilerplate |