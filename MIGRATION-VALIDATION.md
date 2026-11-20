# Validation: the TypeScript/Orama migration guide

A review of [migration_guide.md](./migration_guide.md) against this repository as it
actually is. The guide is a *generic* specification for a document-search app; this
project is a D&D spell recommender. That mismatch is the finding, and everything below is
evidence for it.

Every claim here was checked by running something, not by reading the guide. The probe
commands and their raw results are recorded so they can be re-run.

## Verdict

**Recommendation: do not execute this plan.**

| | |
| --- | --- |
| Guide's core proposal | Replace Python + ChromaDB with client-side TS + Orama + Transformers.js |
| Effect on this repo | Deletes ~43,000 lines (13.2k backend, 9.5k front end, 11.3k tests) and rewrites it |
| Hard blockers found | 9 (4 of them fatal to the guide's own code as written) |
| Fatal on first command | `npm install` fails outright with the guide's pinned versions |
| Prior decision | This repo already rejected this approach, in writing, for reasons that still hold |
| What is worth keeping | 2 of 13 steps — see [Steps worth doing](#steps-worth-doing) |
| What the review did find | A real index defect: **544 content-free rows**, fixed — see [Defect found while validating](#defect-found-while-validating) |

The plan is not "ambitious but correct". Four of its own files do not compile or do not
run, one of its central invariants is impossible per the library's own documentation, it
would produce a **worse** product than the one that exists today, and it would destroy a
recorded month of user data on the way. Details follow.

## 1. The plan targets a different project

The guide opens by naming its target as "local Python + ChromaDB backend" for a
"client-side, local-first search system". It never names this repository, its domain or
its features.

The mismatch is visible immediately in its fixtures:

```python
TEST_FILES = ["sample1.pdf", "sample2.md", "sample3.json"]
TEST_QUERIES = [
    "What is the system architecture?",
    "Error 10000 resolution steps",
    "Database schema definition",
    "Deployment instructions for desktop",
]
```

None of these exist, and none can. `sample1.pdf`, `sample2.md` and `sample3.json` are not
in the tree; there is no `tests/fixtures/` at all. "Error 10000" appears nowhere in this
project, and there is no error-code table to search. This is a fixture set copied from a
documentation-search product and it describes a different corpus.

Measured against the live index (Chroma, 4,674 chunks), **none** of the four document
kinds is covered:

| Real corpus | Chunks | Distinct names | Covered by the guide |
| --- | --- | --- | --- |
| Spells (`data/reddit-spence_post/Spells/`, 544 files) | 1,232 | 522 | No — no spell-specific parsing |
| 2024 SRD rules (`context/srd/`, 7 files) | 2,371 | 1,166 | No — Markdown flattening only |
| Second rulebook (`context/DnD-Character-Sheet-Helper/`) | 1,023 | 956 | No — not mentioned at all |
| Magic items (`data/reddit-spence_post/Magic Items/`) | 48 | 22 | No |
| PDF documents | 0 | 0 | **Yes — `pdfjs-dist`** |
| JSON documents | 0 | 0 | **Yes** |

The guide's two supported formats are the two this project has none of.

The guide's document model is `{text, source, chunkIndex, embedding}`. The real rows
carry `classes`, `doc_type`, `filename`, `is_spell`, `level`, `ritual`, `school`, `source`,
`spell_name`, `tags` — plus `document`, `document_title`, `heading_level` and `slug` on SRD
rows. **Every eligibility filter reads one of those fields** to decide what a character may
legally cast, and the source badge reads `doc_type`. Flattening a row to
`{text, source, chunkIndex}` deletes exactly the metadata the recommender is built on.

## 2. Hard blockers in the guide's own code

These are defects in the guide, independent of whether the migration is desirable. Each
was reproduced.

### 2.1 `npm install` fails

`npm install` with the guide's pinned versions aborts in a dependency's postinstall:

```
npm error path /tmp/probe/node_modules/onnxruntime-node
npm error command failed
npm error command sh -c node ./script/install
npm error Downloading ".../onnxruntime-linux-x64-gpu-1.21.0.tgz"...
npm error `nvcc` not found. Assuming CUDA 12.
npm error Error: Failed to download the binaries: 404 Not Found.
```

The CUDA installer probes for `nvcc`, guesses a CUDA build, and 404s. The guide's
`package.json` has no workaround; the install only completes with
`ONNXRUNTIME_NODE_INSTALL_CUDA=skip` in the environment. A documented, unexplained install
command that cannot run is a poor first step for an agent to be handed.

### 2.2 The guide's `parser.ts` does not compile

`src/utils/parser.ts` as printed, type-checked with the guide's own `tsconfig.json`:

```
src/utils/parser.ts(52,7): error TS2552: Cannot find name 'text'. Did you mean 'ext'?
```

The PDF branch accumulates into `text` but declares and returns `fullText`. Under
`"strict": true` this is a hard error, so `npm run build` — the guide's own step 6 and its
declared verification gate — fails. Note the file was presumably never compiled by whoever
wrote the guide.

### 2.3 The persistence API is used wrongly, and IndexedDB is unsupported

The guide specifies, and its checklist depends on:

```ts
await persist(db, 'idb', DB_STORE_NAME);
dbInstance = await restore('idb', DB_STORE_NAME);
```

Invariant 3 requires `IndexedDB`. Neither works. The installed
`@orama/plugin-data-persistence` declares:

```ts
export type PersistenceFormat = 'json' | 'dpack' | 'binary';
export type Runtime = 'deno' | 'node' | 'bun' | 'browser' | 'unknown';
```

- `'idb'` is not a format. Called with it, the library throws
  `Unsupported serialization format: idb`.
- `restore`'s second parameter is `data: string | Buffer` — serialized content, not a
  store name. The guide's `restore('idb', ...)` is therefore wrong twice over.
- The package's own name for the browser adapter is a **separate entry point**, and
  nothing in the guide imports it.

So the guide's storage design is unimplementable as written. A working version must
serialize to `'json' | 'dpack' | 'binary'` and then put that blob in IndexedDB by hand.

### 2.4 `similarity: 0.65` is an unmeasured constant, and `self.onmessage` is disallowed in a module worker

- The guide sets `similarity: 0.65` with no derivation. Probing the API, Orama's
  `similarity` is a **minimum score** — `1.000` for an exact match, and no hits at all for
  an orthogonal vector at any threshold. The value is a cut-off whose meaning depends
  entirely on the embedding model, and 0.65 is asserted rather than measured. This repo
  has explicit notes on exactly this failure mode (see *A similarity reading is not a
  confidence* in `AGENTS.md`).
- `src/worker.ts` sets `self.onmessage` while being loaded with
  `new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })`. In a module
  worker the global scope is a `WorkerGlobalScope`, not a `DedicatedWorkerGlobalScope`
  (per the HTML spec — the `DedicatedWorker` mixin is excluded in modular workers), so
  `onmessage` is not the right entry point; `self.addEventListener('message', …)` is.

## 3. It would make the product worse, measurably

This is the argument that does not depend on any implementation defect.

**(a) It throws away the headline feature.** The app recommends *which spells to prepare*,
subject to what a character may legally cast. That is a rules-eligibility question: class,
pact, subclass and level. The guide's retrieval is a single `vector` search with a score
threshold. `AGENTS.md` records why this repo separates the two stages:

> **Eligibility** decides what is *legal* for the character … This is a rules question and
> the scenario must never widen it. **Ranking** uses the scenario to order an already-legal
> pool.

and

> **A similarity search cannot enumerate.** Book of Shadows takes exactly 3 cantrips and 2
> level 1 rituals, so those lanes are fetched exhaustively from Chroma metadata, not by
> vector search. Relying on similarity would silently omit legal options.

An exact-count lane ("fetch all 3 cantrips") is not expressible as a similarity search.
The migration replaces correctness with recall, silently.

**(b) It swaps a working embedder for an untested 22M-parameter one.** 384 dimensions is
retained, but the model changes from `nomic-embed-text` to `Xenova/all-MiniLM-L6-v2`. Two
different embedders produce different distances and a different neighbour ordering, so every
retrieval behaviour tuned in this repo — heading-anchored matching, term rarity weighting,
the coverage gate for selections — would need re-deriving from scratch. Measured, the
quantized ONNX file is **~23 MB per client**.

**(c) The SRD's structure is load-bearing and would be destroyed.** `AGENTS.md` documents
that the SRD is indexed **one row per section, chunked by heading**, because "a rule's
identity is its heading: `### Cover` is the rule, and a chunk that began mid-table would be
a fragment with no name". The guide's `chunkText` is a sliding 400-word window with 40 words
of overlap over whitespace-collapsed text. A rule would be split across chunks with its
heading detached, and the heading-anchored matcher — three separate mechanisms that each
exist to stop a passing mention being quoted as a rule — would have nothing to anchor to.
This is a direct regression on documented, tested behaviour.

Measured, the flattening also loses information before the model does anything: **2,371
SRD chunks collapse to 1,166 heading names**, and those names are the anchors that let a
citation open the rule it came from.

**(d) It breaks the source-attribution contract.** Every answer in this app carries a
source badge (`sheet` / `model` / `rules` / `rules-inferred`) that tells the reader whether
a sentence is *quoted from the 2024 SRD* or *generated*. That distinction is the reason the
rules matcher is strict. The guide has no schema field for provenance; its result rows are
`{text, source, chunkIndex}`.

**(e) Half the product has no counterpart.** The guide's UI is one file input, one search
box, and a list of chunks. The current front end is 61 files / 9,455 lines covering the
character sheet, spell cards and drawers, the rules browser with breadcrumbs and anchors,
run history and ratings, conversations, plus the accessibility and layout work recorded in
`AGENTS.md`. The guide does not mention a character, a spell, a book, a cheatsheet, a
rating or a history — and the API it would replace serves 26 endpoints behind those
screens. Call it 1 screen against the app's ~8.

**(f) The current index already holds the whole corpus in memory cheaply.** The ROADMAP's
reason ("a browser cannot hold the 544-document index cheaply") is worth re-testing rather
than repeating, and the measurement backs it only for the *embedding* cost: 4,674 chunks ×
384 float32 dimensions is ~7 MB of vectors, which is not the obstacle. The obstacles are
the eligibility rules, the SRD structure and the cache, none of which get cheaper by
moving.

## 4. It would destroy user data and prior decisions

**(a) `.cache/` is the training set, and the guide deletes it.** The checklist's step 3 is
"Delete all Python backend files, requirements files, and Chroma configs". `AGENTS.md` is
emphatic that this directory is not a build artefact:

> **Clean up with `rm -rf .cache` and you destroy the user's history.** It looks like a
> build artifact, but it is the record of every run and rating … **never delete the real
> one during development.**

The cache holds runs, per-book ratings, conversations and the scaling-note store. Deleting
the Python backend orphans all of it, because the key derivation lives in `.cache.py`. No
step in the guide migrates or backs it up.

**(b) The corpus stops being redistributable.** `context/srd/` is SRD 5.2.1 under
CC-BY-4.0, vendored with attribution in `context/srd/PROVENANCE.md`. Indexing it
client-side and shipping it to a browser changes redistribution rather than removing it,
and the guide has no licensing step at all.

**(c) It re-litigates a settled decision.** `ROADMAP.md` already records this approach as
superseded, in the repository's own words:

> - **Client-side-only RAG with ChromaJS.** Planned before the retrieval logic existed; the
>   two-stage retrieval now needs the spell pool, the rules validity check and the cache in
>   one place, and a browser cannot hold the 544-document index cheaply.

The guide proposes the same thing with a different vector store. The stated reason — the
two-stage pipeline needs the pool, the validity check and the cache in one place — is not
addressed anywhere in it. The size claim has also since moved in the other direction:
measured, the index is **4,674 chunks in a 65 MB directory**, not the "544-document index"
the ROADMAP described when the decision was taken, because the SRD and the second rulebook
have been added. The problem has grown, and the guide's answer to it is a single vector
search.

## 5. Scope, and what "done" would mean

The guide's checklist has 7 items and presents the work as a straight substitution. A
faithful port of the current backend's user-visible behaviour needs, at minimum: the
eligibility rules for 544 spells and 22 items; the book generator and its prompt
contract; `validate_book_picks`; the run/rating/conversation caches with their key
derivation; the rules matcher with its three anti-false-positive mechanisms; SRD section
parsing, anchors and breadcrumbs; and the class-context and optional-second-rulebook
lanes. That is ~13,000 lines of Python with ~11,250 lines of tests behind it.

The guide's parity test cannot tell whether any of that survived. Its assertion is:

```ts
expect(intersection.length).toBeGreaterThan(0);
```

**At least one hit in the top 5 out of a known-good set**, per query — over four queries
against a fixture file that does not exist. A backend that returns one correct chunk out
of five passes. Recall alone cannot detect the loss of a *filter*, and the filter is the
product. This test is not a gate; it is a smoke test presented as one.

## 6. Defect found while validating

Validating the plan against the live index turned up a real defect that has nothing to do
with the migration, and it is fixed on this branch.

Measured, the index held **4,674 rows of which 544 carried no content** — one per spell
page. `_spell_documents` injects an authoritative `Spell Name: <name>` line into each page's
body (six corpus files are named after a different spell than they contain, so the body is
the only place the real name can live). But `MarkdownHeaderTextSplitter` splits on `#`, and
the injected line sits *above* the page's own heading — so it became a chunk of its own,
containing nothing but the name:

```
chunks for Fireball: 4
--- chunk 0 len=20: 'Spell Name: Fireball'
--- chunk 1 len=830: '#Level3 #Evocation ( #Sorcerer, #Wizard) ...'
--- chunk 2 len=689: 'Spells > Fireball ...'
--- chunk 3 len=655: 'Fireball (spell) ...'
```

Every one was an embedded row eligible to return as a search hit that shows a spell's name
and no text — a plausible-looking result that answers nothing. The fix folds the line into
the first real chunk, which keeps the name in the body the mis-named-file fix needs it in.
Measured after: 544 stubs → **0**, spell rows 1,280 → 736, every row still carrying its
level and doc type.

This is why the review is worth doing even though the verdict is negative. The guide's
document model would have flattened these rows into `{text, source, chunkIndex}` and lost
the *evidence* — no count, no `doc_type`, no name — while leaving the defect in place.

`INDEX_VERSION` is bumped to 5, because `ensure_db` only rebuilds when `db_is_valid`
rejects what is on disk, and `sources_match` compares the *shape* of the rows — removing
rows is not a shape change, so the version is the only guard that reaches an existing index.
The tradeoff the surrounding comments warn about was weighed: the cost is a rebuild plus one
fresh model call per character (`db_version` joins the run cache key), while the benefit is
retiring 544 dead rows. Runs are not deleted — `cache.load_runs` globs every version — so
history and ratings survive and stay readable.

Coverage added in `tests/test_indexing.py`: 12 tests, where the module previously had none
of its own. The last of them asserts the defect against the real 544-file corpus, because a
row-count defect is invisible in a single-page fixture.

## 7. Steps worth doing

Two of the guide's 13 steps are worth keeping, and they are worth keeping *because* they do
not depend on the migration:

- **§5/§6, docs split** — an `ARCHITECTURE.md` and a `README.md` are already present and
  maintained. The guide's versions are generic and would replace domain documentation with
  filler, so the *content* is not reusable; the *idea* of a separate architecture doc is
  already satisfied.
- **§6 hardening, if and only if the migration is chosen** — the four code defects in
  [§2](#2-hard-blockers-in-the-guides-own-code) are fixable in an afternoon. Fixing them
  does not change the verdict, because the verdict rests on §1, §3 and §4.

Everything else is either a rewrite of working code or the deletion of recorded user data.

## 8. If a client-side deployment is genuinely required

The requirement the guide appears to be serving is *"deploy as a static Vercel PWA **and**
an offline Electron desktop app"*. That is achievable without deleting the backend, and
the architecture is already shaped for it:

1. **Keep `backend/libs`.** It is already terminal-free and request-free — a test enforces
   it (`test_service_imports_without_a_terminal`) — so it is the reusable core.
2. **Bundle the Python core for desktop.** Electron ships the Python runtime and
   `backend/` as a sidecar process, or the core is packaged with PyInstaller. `backend/api`
   already exists as the transport, so the Electron renderer can be the existing React app
   pointed at a loopback port.
3. **Ship the front end as the PWA** against a hosted instance of the same API.
4. **Move retrieval, not the product.** If part of search must be local-first, port the
   *retrieval* layer behind the existing `SpellbookService` seam, keep `doc_type` and the
   eligibility filters, and evaluate it against the **existing 1,251 pytest tests** rather
   than a four-query smoke test.

That path reuses the 43,000 lines instead of deleting them, keeps every documented
invariant, and still ends with a static bundle and a desktop app.

## Appendix: how to reproduce

Each claim below corresponds to a section above.

```bash
# §2.1 npm install fails
mkdir -p /tmp/probe && cd /tmp/probe   # with the guide's package.json
npm install                            # fails in onnxruntime-node postinstall

# §2.2 parser.ts does not compile
npx tsc --noEmit -p tsconfig.json      # error TS2552: Cannot find name 'text'

# §2.3 formats and arguments
node -e "import('@orama/plugin-data-persistence').then(m=>console.log(Object.keys(m)))"
grep -n "PersistenceFormat" node_modules/@orama/plugin-data-persistence/dist/types.d.ts
#   -> type PersistenceFormat = 'json' | 'dpack' | 'binary'
# persist(db, 'idb', 'name')  ->  Unsupported serialization format: idb
# restore('idb', 'name')      ->  second parameter is data, not a store name

# §2.4 similarity semantics
# exact match -> score 1.000; orthogonal vector -> 0 hits at any threshold

# §1 fixture mismatch and real corpus shape
ls tests/fixtures        # No such file or directory
grep -rn "Error 10000" . # no matches
.venv/bin/python - <<'PY'
from backend.libs import config
import chromadb, collections
col = chromadb.PersistentClient(path=str(config.DB_DIR_PATH)).get_collection("langchain")
meta = col.get(include=["metadatas"])["metadatas"]
for dt, n in sorted(collections.Counter(m["doc_type"] for m in meta).items()):
    print(dt, n, "distinct:", len({m["spell_name"] for m in meta if m["doc_type"] == dt}))
print("total:", len(meta))
PY
# spell 1232/522  srd 2371/1166  ionas-politis 1023/956  item 48/22  total 4674

# §4c index and model sizes
du -sh data/chroma_db    # 65M
du -sh /tmp/probe/.hfcache/Xenova/all-MiniLM-L6-v2/onnx/model_quantized.onnx   # ~23M

# §5 existing suite
.venv/bin/python -m pytest --collect-only   # 1251 tests collected

# §6 the 544 content-free rows, in the index as it was before the fix
.venv/bin/python - <<'PY'
from backend.libs import config
import chromadb
col = chromadb.PersistentClient(path=str(config.DB_DIR_PATH)).get_collection("langchain")
d = col.get(include=["documents"])
stub = [t for t in d["documents"]
        if t.strip().startswith("Spell Name:") and len(t.strip().split("\n")) == 1]
print("total:", len(d["documents"]), "name-only rows:", len(stub))
PY
# -> total: 4674 name-only rows: 544   (before INDEX_VERSION 5)
# -> `_spell_documents` over the real corpus now reports 736 rows and 0 stubs
```
