# Plan: a local-only Electron app

Goal: **the app runs entirely on the user's machine, as a desktop application.** No hosted
backend, no API keys, no network at runtime.

This is a different goal from the one [migration_guide.md](./migration_guide.md) set, and
the difference decides the plan. That guide wanted *all TypeScript* and treated the Python
core as the thing to delete. This plan wants *local-only*, and the measurements below say
the Python core is not what stands in the way.

## The finding that shapes everything

Measured across `backend/libs/` (10,612 lines, 19 modules):

| | Modules | Lines | External dependencies |
| --- | --- | --- | --- |
| **Pure logic** | 15 | **9,880** | none — stdlib only |
| Framework-bound | 4 | 732 | `chromadb`, `langchain_*`, `watchdog`, `dotenv`, `yaml` |

The 15 pure modules include every hard part of this product: `rules.py` (2,239 — the
heading-anchored matcher), `service.py` (1,126), `cache.py` (941), `ionas.py` (936),
`prompts.py` (642), `search.py` (636), `spells.py` (625), `srd.py` (526),
`spellstats.py` (490), `conversations.py` (411), `retrieval.py` (355), `lookup.py` (277),
`llm.py` (257), `timing.py` (156).

**Only four files touch anything external**, and each is a thin adapter:

| File | Lines | What it adapts |
| --- | --- | --- |
| `indexing.py` | 448 | Chroma + LangChain splitters |
| `config.py` | 284 | `.env` loading |
| `characters.py` | 186 | YAML sheet parsing |
| `watching.py` | 77 | `watchdog` file watcher |

So "port to TypeScript" is not a rewrite of the product. It is a rewrite of **732 lines of
adapter**, plus a re-implementation of 9,880 lines of rules logic that already works and
already has 1,263 tests behind it.

That is the whole argument for the staging below: **do the local-only work first, because
it is small and it is what you actually asked for. Decide about TypeScript afterwards, with
the app already local.**

## What "local-only" costs today

Three things are not local right now, and only one of them is architectural.

1. **The model is remote.** `.env` currently sets `LLM_MODEL=deepseek/deepseek-v4.1-flash-1017`
   and `LLM_MODEL_FAST=deepseek/deepseek-v4-flash-0731`, both OpenRouter ids. Every
   recommendation leaves the machine.
2. **The API is a server.** `_run.sh` starts `uvicorn` on port 8000 and the front end calls
   `http://localhost:8000`. It is loopback-only, so nothing leaves the machine — but it is a
   process to supervise, and it is the thing that makes packaging awkward.
3. **The index is built by a separate toolchain.** Chroma + LangChain, 60 MB on disk.

Everything else is already local: the corpus is vendored, the SRD is vendored, the index is
on disk, the cache is on disk, and embeddings already run through local Ollama
(`nomic-embed-text`).

## Stage 0 — make it local, today, with no rewrite

**This is the step that delivers the goal.** It is configuration plus one packaging change,
and it can be done and verified in an afternoon.

### 0.1 Point the model at Ollama

`config.select_model` already infers the backend from the name: an id containing `/` is
OpenRouter, a `name:tag` is Ollama, and **an Ollama name wins even when a key is present**.
So this is a `.env` change, not a code change:

```bash
LLM_MODEL=qwen3.8:latest        # or any local model
LLM_MODEL_FAST=qwen3.5:4b
```

Verified against the installed models: `qwen3.8:latest` (17.7 GB) and `qwen3.5:4b`
(3.4 GB) are both present locally. `qwen3.5:4b` is a *thinking* model, which this repo has
already been bitten by — it can spend its whole budget on hidden reasoning and return an
empty string with HTTP 200. `llm.explain_failure` and the empty-completion check already
handle that, but it is worth knowing before choosing it for the reasoning role.

**Acceptance:** unplug the network, run a scenario, get a recommendation. That is the whole
test, and it is the one that matters.

### 0.2 Ship the API as a sidecar, not a service

Electron starts `uvicorn` as a child process on a **random free port**, bound to
`127.0.0.1`, and passes the port to the renderer. The front end already supports this —
`frontend/app/api/client.ts` reads `VITE_API_BASE`, defaulting to `localhost:8000`:

```ts
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'
```

So the renderer needs the port injected at runtime rather than baked at build time. Two
options, in order of preference:

- **Preferred:** a preload script exposes the port on `window`, and the client reads it
  before falling back to `VITE_API_BASE`. Small change, no rebuild per launch.
- Alternative: pick a fixed high port and set `VITE_API_BASE` at build time. Simpler, but
  two copies of the app collide.

**Why a sidecar and not a rewrite:** the API is already transport-only by design — a test
enforces that `backend/libs` never imports `backend/cli` or `backend/api`
(`test_service_imports_without_a_terminal`). Nothing in the core knows it is behind HTTP.

### 0.3 Bundle the runtime

The venv is **669 MB**, which is too much to ship as-is. The heavy parts are
`onnxruntime` (68 MB), `numpy` (43 MB), `langchain_community` (25 MB),
`langchain_classic` (15 MB) — and most of that is pulled in by Chroma and LangChain, not by
the product.

Two paths:

- **PyInstaller** the backend into a single binary. Expect ~150–250 MB after excluding
  test fixtures and unused LangChain integrations.
- **Or** do Stage 1 first, which removes Chroma and LangChain entirely and takes the
  dependency set down to `fastapi`, `uvicorn`, `PyYAML`, `httpx`, `rich` — a much smaller
  bundle.

### 0.4 Bundle the data

| Asset | Size | Notes |
| --- | --- | --- |
| `data/reddit-spence_post/` | 6.6 MB | 1,575 files; the spell corpus |
| `context/srd/` | 884 KB | CC-BY-4.0, attribution in `PROVENANCE.md` |
| `context/DnD-Character-Sheet-Helper/` | 4.2 MB | **GPL-3.0 — see below** |
| `data/chroma_db/` | 60 MB | **Do not ship — build on first run** |

**The GPL problem is real and needs a decision.** `context/DnD-Character-Sheet-Helper/` is
GPL-3.0 upstream, which is why it is fetched rather than vendored and why it is gitignored.
Bundling it into a distributed desktop app is redistribution, which GPL-3.0 permits but
attaches obligations to. The app already treats it as optional — `ionas.available()` is one
`is_dir` check and every caller degrades to the SRD — so the clean answer is to **not bundle
it**, and let a user who wants it run `scripts/fetch-context.sh`. That keeps the shipped
artifact free of the obligation and costs only the second rulebook.

**Build the index on first run, not at package time.** It is 60 MB of derived data, it is
already rebuilt automatically when `INDEX_VERSION` changes, and shipping it would mean
shipping a stale copy the moment the corpus changes. First-run cost is one embedding pass
over 4,130 rows through local Ollama.

## Stage 1 — replace Chroma with Orama (optional, and smaller than it sounds)

If the goal is *all TypeScript*, this is the honest first move: it is the only part of the
Python core that is genuinely framework-bound, and it is 448 lines.

I probed Orama v3.1.18 directly rather than trusting the guide. It **can** express every
lane this app needs — but the API has traps that fail *silently*, which is the same class of
bug this repo has already paid for twice.

### What works

| Lane | Orama expression | Verified |
| --- | --- | --- |
| All spells | `{ doc_type: { eq: 'spell' } }` | 3 hits |
| Cantrips only | `{ and: [{doc_type:{eq:'spell'}}, {level:{lte:0}}] }` | 1 hit |
| Level ≤ 1 rituals | `{ and: [{doc_type:{eq:'spell'}}, {ritual:{eq:true}}, {level:{lte:1}}] }` | 1 hit |
| Rules only | `{ doc_type: { eq: 'srd' } }` | 1 hit |
| Items only | `{ doc_type: { eq: 'item' } }` | 1 hit |
| Union | `{ or: [...] }` | 4 hits |
| Nested | `{ and: [..., { or: [...] }] }` | 2 hits |
| Vector | `{ mode: 'vector', vector: { value, property } }` | score 1.000 exact |
| Hybrid | `{ mode: 'hybrid', term, vector }` | 2 hits |
| Persistence | `persist(db, 'json' \| 'dpack' \| 'binary')` | round-trips |

### The traps, all measured

1. **Boolean operators are lowercase in v3.** `AND`/`OR` throw
   `Unknown filter property "AND"`. The guide's `$and`/`$or` are Chroma's spelling.
2. **An `enum` field rejects a bare value.** `{ doc_type: 'spell' }` throws
   `You can only use one operation per filter, you requested 5`. It needs
   `{ doc_type: { eq: 'spell' } }`. A `string` field accepts the bare form — so the same
   filter is correct or fatal depending on the schema type, which is a trap that only shows
   up at runtime.
3. **A `string` field ignores `eq`, `in`, `contains`, `startsWith` and `endsWith` — all
   return 0, silently.** Only the bare form works, and it is a **token** match, not a
   substring match. Measured on `classes: 'Sorcerer, Wizard'`:

   | Filter | Result |
   | --- | --- |
   | `{ classes: { contains: 'Wizard' } }` | **0** |
   | `{ classes: { eq: 'Wizard' } }` | **0** |
   | `{ classes: { in: ['Wizard'] } }` | **0** |
   | `{ classes: 'Wizard' }` | **2** ✓ |

   This is the *same* failure `AGENTS.md` records for Chroma — "a filter that silently
   matches nothing is the commonest failure here" — and it would be re-introduced by a
   straight port. The fix is to store `classes` as a **string array** and use `containsAll`,
   or to keep the exact-combination `or` the current code builds.

4. **`similarity` is a minimum score, not a distance.** An exact match scores 1.000 and an
   orthogonal vector returns 0 hits at any threshold. Any threshold must be measured against
   the chosen embedder, not copied.

### Measured at real scale

4,130 rows, 384 dimensions, real metadata shape:

| | |
| --- | --- |
| Insert 4,130 rows | 367 ms |
| Persist `json` | 81.3 MB |
| Persist `dpack` | **74.9 MB** |
| Persist `binary` | 93.3 MB |
| Vector search, k=10 | **9.9 ms** |
| Filter + vector | **3.9 ms** |

Query latency is excellent — better than the current Chroma path. **Persistence size is the
problem: 75 MB, larger than the 60 MB Chroma index it replaces**, because JSON-encoded
float32 vectors are bulky. That is acceptable for a desktop app but it is not the win the
guide implied, and it should be a deliberate choice rather than a surprise.

### The embedding model

The guide's `Xenova/all-MiniLM-L6-v2` is a **different model** from the current
`nomic-embed-text`. Swapping it changes every distance and invalidates every tuned
threshold. Verified available with ONNX weights: `Xenova/all-MiniLM-L6-v2`,
`Xenova/bge-small-en-v1.5`, `Xenova/gte-small`. `Xenova/nomic-embed-text-v1.5` has **no ONNX
files** and cannot be used with Transformers.js.

Also note: `quantized: true` is **ignored** in transformers.js 3.8.1 — it loads the fp32
model and logs `dtype not specified for "model"`. Use `dtype: 'q8'` explicitly.

### What Stage 1 does *not* buy

It does not remove Python. `rules.py`, `service.py`, `cache.py` and the rest are still
Python, and they are 9,880 of the 10,612 lines. Replacing Chroma makes the *index* portable;
it does not make the *product* TypeScript.

## Stage 2 — port the core, if you still want to

Only worth starting once Stage 0 ships and Stage 1 has proved the index works. Port in
dependency order, and port the tests with each module — they are the specification:

| Order | Module | Lines | Why this order |
| --- | --- | --- | --- |
| 1 | `spells.py` | 625 | Pure parsing; everything downstream depends on it |
| 2 | `srd.py` | 526 | Section tree, anchors, breadcrumbs |
| 3 | `rules.py` | 2,239 | The matcher. Largest and highest-risk; port its 99 tests first |
| 4 | `spellstats.py` | 490 | Scaling notes |
| 5 | `retrieval.py` | 355 | Pool assembly |
| 6 | `prompts.py` | 642 | Prompt templates |
| 7 | `cache.py` | 941 | Run/rating/conversation stores |
| 8 | `service.py` | 1,126 | The seam; port last, it ties the rest together |

**Do not port `ionas.py` (936 lines) unless the GPL question is settled.** It is the
optional second rulebook, and it is the one module whose inclusion has licensing
consequences.

**The LLM call stays out of the browser.** A local-only desktop app should talk to Ollama
over `http://127.0.0.1:11434` from the main process, not from the renderer — the renderer
should not hold a network client, and Ollama's CORS behaviour is not something to depend on.

## What I would actually do

1. **Stage 0.1 today.** Change two lines in `.env`, unplug the network, run a scenario. That
   is the goal you asked for, and it is nearly free.
2. **Stage 0.2–0.4 next.** Sidecar + PyInstaller + first-run index build. Now you have a
   desktop app that is genuinely local.
3. **Then decide.** With the app local, "all TypeScript" is a separate question about
   maintainability, not about locality. Stage 1 is worth doing on its own merits — Orama's
   4 ms queries are better than Chroma's — but it is a *performance* change, not a
   local-only change.
4. **Stage 2 only if the answer to "do we want one language?" is yes**, and only with the
   1,263 tests as the acceptance criteria.

## Risks

| Risk | Mitigation |
| --- | --- |
| A local model is worse at the book format than DeepSeek | The prompt is a worked example with explicit delimiters; test with the real corpus before committing |
| `qwen3.5:4b` returns empty completions | Already handled — empty is treated as failure, and `finish_reason` is checked |
| Orama's silent filter traps | Port `search.py`'s tests first; they exist precisely to catch a filter that matches nothing |
| 75 MB persisted index | Accept for desktop, or store vectors separately from metadata |
| GPL-3.0 second rulebook | Do not bundle it; keep `fetch-context.sh` as the opt-in |
| PyInstaller bundle size | Do Stage 1 first to drop Chroma and LangChain |

## Appendix: how to reproduce

```bash
# The dependency split
for f in backend/libs/*.py; do
  deps=$(grep -hoE "^(from|import) (langchain|chromadb|ollama|watchdog|yaml|dotenv)[a-z_]*" "$f" | sort -u)
  [ -z "$deps" ] && echo "PURE $(wc -l < "$f") $(basename "$f")" || echo "IO   $(wc -l < "$f") $(basename "$f")"
done

# The packaging footprint
du -sh .venv data/chroma_db data/reddit-spence_post context/srd

# Orama's filter semantics (the traps)
#   { doc_type: 'spell' }            -> throws on an enum field
#   { doc_type: { eq: 'spell' } }    -> works
#   { classes: { contains: 'Wizard' } } -> 0, silently
#   { classes: 'Wizard' }            -> token match, works
#   AND/OR                           -> throws; v3 uses and/or

# Orama at real scale: 4130 rows x 384 dims
#   insert 367ms | dpack 74.9MB | vector k=10 9.9ms | filter+vector 3.9ms
```
