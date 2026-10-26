# Spellbook Recommendation System - Roadmap

## Project Overview

A RAG-based intelligent spell recommender for Dungeons & Dragons players powered by GLM-4.7-flash. The system helps players find relevant spells for their characters and scenarios based on rulesets, class constraints, and real-time context.

## Technology Stack Decisions

| Component | Decision | Rationale |
|-----------|----------|-----------|
| Frontend Framework | React + Vite | Mature ecosystem, TypeScript support, fast dev |
| Backend | Client-side only (MVP) | Simpler deployment, data privacy |
| Vector Database | ChromaDB (embedded) | Browser-compatible, easy to use |
| Embeddings | SentenceTransformers.js | Lightweight, good quality |
| LLM Model | GLM-4.7-flash | Fast inference, good RAG capabilities |
| State Management | Zustand | Simple, TypeScript-friendly |
| API Client | Direct fetch | No server overhead needed |

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed RAG pipeline, components, and implementation notes.

## Roadmap

### Phase 0: Foundation (DONE)
- ✅ Agent schema documentation (`AGENTS.md`)
- ✅ Initial project structure
- ✅ Tech stack decisions
- ✅ RAG architecture design

### Phase 1: Setup & Configuration (NEXT)
**Goal**: Initialize the development environment

Tasks:
- [ ] Initialize React + Vite project with TypeScript
- [ ] Set up project structure and dependencies
- [ ] Configure TailwindCSS for UI styling
- [ ] Set up ESLint and Prettier
- [ ] Configure ChromaDB browser environment
- [ ] Set up SentenceTransformers.js embedding pipeline
- [ ] Create base component structure

**Deliverables**:
- Running React + Vite development server
- Project structure with all subdirectories
- Development environment ready for code

**Est. Time**: 2-3 hours

### Phase 2: Data & Storage (Week 2)
**Goal**: Implement data structures and local storage

Tasks:
- [ ] Define TypeScript interfaces (Character, Spell, Ruleset, Scenario)
- [ ] Create spell parser for markdown rulesets
- [ ] Implement localStorage service
- [ ] Create data export/import utilities
- [ ] Add sample rulesets and spell lists
- [ ] Build character editor component

**Deliverables**:
- TypeScript type definitions
- Ruleset parser working
- LocalStorage sync working
- Sample character with spells
- JSON export/import functionality

**Est. Time**: 4-5 hours

### Phase 3: RAG Pipeline Implementation (Week 3)
**Goal**: Build embeddings, vector store, and retrieval

Tasks:
- [ ] Set up SentenceTransformers.js embedding model
- [ ] Implement ChromaDB vector store
- [ ] Build spell embedding pipeline
- [ ] Create similarity retrieval function
- [ ] Add rule-based filtering (level, class, tags)
- [ ] Test with sample queries
- [ ] Optimize retrieval performance

**Deliverables**:
- Working embeddings pipeline
- Vector store with spell embeddings
- Retrieval function returning relevant spells
- Performance benchmarks

**Est. Time**: 5-6 hours

### Phase 4: LLM Integration (Week 4)
**Goal**: Connect to GLM-4.7-flash API

Tasks:
- [ ] Set up ZhipuAI API key configuration
- [ ] Implement direct fetch to GLM-4.7-flash API
- [ ] Build RAG prompt construction
- [ ] Handle LLM response parsing and validation
- [ ] Add caching for frequent queries
- [ ] Implement error handling and fallbacks
- [ ] Test with various scenarios

**Deliverables**:
- Working LLM API integration
- RAG prompt templates
- Response parser
- Caching mechanism

**Est. Time**: 4-5 hours

### Phase 5: UI Implementation (Week 5-6)
**Goal**: Build user interface and user flows

Tasks:
- [ ] Create main layout and navigation
- [ ] Build character selector component
- [ ] Create scenario input form
- [ ] Implement spell recommendation display
- [ ] Add cheat sheet display
- [ ] Build history view component
- [ ] Add export functionality
- [ ] Implement theme toggle

**Deliverables**:
- Complete UI with all major components
- Character selection working
- Scenario input working
- Recommendations displayed with context
- History tracking

**Est. Time**: 8-10 hours

### Phase 6: Polish & Testing (Week 7)
**Goal**: Refine UX, add testing, finalize MVP

Tasks:
- [ ] Mobile responsive testing and fixes
- [ ] Error handling improvements
- [ ] Loading states and feedback
- [ ] Unit tests for core functions
- [ ] Integration tests for RAG pipeline
- [ ] Performance optimization
- [ ] User documentation
- [ ] Build and deployment setup

**Deliverables**:
- Responsive UI working
- Comprehensive error handling
- Unit and integration tests
- Optimized performance
- README with setup instructions
- Production build ready

**Est. Time**: 6-8 hours

### Phase 7: Launch (Week 8)
**Goal**: Deploy and share with community

Tasks:
- [ ] Final testing on various browsers
- [ ] Create HTML export (no build needed)
- [ ] Set up GitHub repository
- [ ] Create deployment instructions
- [ ] Write usage guide
- [ ] Initial community testing

**Deliverables**:
- Deployable HTML version
- GitHub repo with documentation
- Setup and usage guides

**Est. Time**: 2-3 hours

## Migration Path: MVP → Full System

### Backend/CLI split (done)

The Python code is now layered so an API can reuse it without a terminal:

```
src/backend/    rules, retrieval, prompting, caching, index, watcher  (no printing)
src/cli/        REPL, argument parsing, progress, markdown rendering  (no logic)
main.py         compatibility shim re-exporting the old names
```

`backend.service.SpellbookService` is the intended API surface. It takes a vector index
and a character sheet, exposes `scenario()` / `refine()` / `find_cached()` / `validate()`
/ `history()` / `replay()`, and returns `Generation` and `Book` dataclasses. It never
prints, prompts or exits, and a test asserts it imports without pulling in `cli`.

```python
@dataclass
class Generation:
    scenario: str
    answer: str
    books: list[Book]
    prompt: str
    warnings: list[str]      # book picks that are not actually legal
    from_cache: bool
    model: str | None
    pool: dict               # the eligible candidates the model chose from
    timings: dict            # per-phase seconds: retrieval / prompt / books
```

**To add an API, do not move code - wrap the service.** The remaining work is transport,
not logic:

| Task | Where |
| --- | --- |
| Endpoints (`POST /scenario`, `POST /ask`, `GET /history`, `GET /runs/{id}`) | new `src/api/`, calling the service |
| Serialisation | `dataclasses.asdict(generation)` already produces a JSON-ready dict |
| Errors -> status codes | map `NoEligibleSpells`->422, `EmptyCompletion`->502, `CharacterNotFound`->404 |
| Progress | pass a callback, or accept the no-op default (the service takes one either way) |
| Per-request index/client | the service holds its own index, so one instance per request/session |

Deliberately **not** built yet: no web framework, no auth, no server-side persistence.

### Future Enhancements

1. **Server-Side RAG**
   - Move vector database to server
   - Handle larger spell lists
   - Cross-device sync

2. **API Gateway**
   - REST API for external integrations
   - Authentication and rate limiting
   - Usage analytics

3. **Cloud Sync**
   - Encrypted cloud storage
   - Multi-device sync
   - Backup and restore

4. **Knowledge Graph**
   - Neo4j integration
   - Complex spell relationships
   - Pattern recognition

5. **Multi-Agent System**
   - Separate agents for different tasks
   - Chain-of-thought reasoning
   - Multi-step recommendation

6. **Advanced Features**
   - Item spell synergy
   - Background-specific recommendations
   - Rule variation handling
   - Campaign context awareness

## Milestones

- [ ] **MVP v1.0**: Core RAG + UI working
- [ ] **Release v1.1**: Full polish and documentation
- [ ] **Beta v2.0**: Server-side RAG and sync
- [ ] **Stable v3.0**: Knowledge graph and advanced features

## Dependencies

### External APIs
- **ZhipuAI GLM-4.7-flash**: For LLM recommendations
- Need API key for testing and production

### Open Source Dependencies
- React 18 + Vite
- TypeScript
- Zustand (state)
- ChromaDB (vector DB)
- SentenceTransformers.js (embeddings)

## Notes

- All development can be done client-side for MVP
- No backend server needed initially
- Data privacy by design (local storage)
- Easy to distribute as single HTML file

## Resources

- [Architecture Documentation](./ARCHITECTURE.md)
- [Agent Schema](./AGENTS.md)
- [React + Vite Docs](https://vitejs.dev/)
- [ChromaDB Browser](https://docs.trychroma.com/)
- [SentenceTransformers.js](https://www.huggingface.co/docs/transformers/tasks/model_summary)
- [GLM-4.7-flash API](https://open.bigmodel.cn/dev/api)

---

*Last updated: 2024-10-22*
