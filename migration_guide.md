# Specification: Migration from Python/ChromaDB to Local TypeScript/Orama

**Target:** Migrate a local Python + ChromaDB backend to a 100% client-side, local-first search system (TypeScript + Orama + Transformers.js) deployable as both a static Vercel PWA and an offline Electron desktop application.

---

## 1. Architectural Invariants (Strict)

1. **Zero Server / Zero API Routes:** Never create Next.js API routes, Express servers, or Python microservices. All parsing, embedding, indexing, and search operations run inside the client environment.
2. **Worker Isolation:** Hugging Face embedding pipelines and bulk text processing must run inside a dedicated Web Worker (`src/worker.ts`) to avoid freezing the React UI thread.
3. **Storage Persistence:** The vector index and document store must persist to browser `IndexedDB`.
4. **Vite Build Parity:** The project must build cleanly with standard Vite. The static output in `dist/` serves both the static web host (Vercel) and the Electron shell.
5. **No Private Secrets:** Do not create `.env` files with private API keys. The app runs in userland (browser/desktop); any API keys added in the future must be supplied by the user in settings and stored locally.

---

## 2. Pre-Migration Step 1: Capture Python Baseline Fixtures

Run this script inside the existing Python environment before tearing it down. It produces `tests/fixtures/golden_baseline.json`, which records baseline chunks and chroma query recall to verify against post-migration.

### `tests/export_golden_baseline.py`
```python
import json
import os
from typing import List, Dict

TEST_FILES = ["sample1.pdf", "sample2.md", "sample3.json"]
TEST_QUERIES = [
    "What is the system architecture?",
    "Error 10000 resolution steps",
    "Database schema definition",
    "Deployment instructions for desktop"
]

def generate_baseline():
    baseline_data = {
        "files": [],
        "queries": []
    }

    # 1. Capture chunks produced by current Python pipeline
    for filename in TEST_FILES:
        filepath = os.path.join("tests/fixtures/input_docs", filename)
        if not os.path.exists(filepath):
            continue
        with open(filepath, "rb") as f:
            content = f.read()
        
        # Replace with your actual Python parsing/chunking function:
        # chunks = chunk_document(filename, content)
        chunks = [{"text": "Example extracted chunk", "source": filename, "chunk_index": 0}]
        
        baseline_data["files"].append({
            "filename": filename,
            "chunks": chunks
        })

    # 2. Capture query results from active ChromaDB
    for q in TEST_QUERIES:
        # Replace with your actual Chroma query function:
        # results = query_chroma(query_text=q, top_k=5)
        results = [{"text": "Example matched chunk", "source": "sample1.pdf", "score": 0.89}]
        
        baseline_data["queries"].append({
            "query": q,
            "expected_top_hits": results
        })

    os.makedirs("tests/fixtures", exist_ok=True)
    with open("tests/fixtures/golden_baseline.json", "w", encoding="utf-8") as f:
        json.dump(baseline_data, f, indent=2)

    print("Baseline captured successfully in tests/fixtures/golden_baseline.json")

if __name__ == "__main__":
    generate_baseline()
```

---

## 3. Pre-Migration Step 2: Documentation Setup

Update or create the following documentation files before code migration.

### `AGENTS.md`
```markdown
# Instructions for Autonomous Coding Agents

## Core Directives
1. **No Backend Services:** Under no circumstances should you create Node.js servers, Express backends, Next.js `/api` endpoints, or Python services. The app is 100% client-side.
2. **Local AI / Vector Execution:** All embeddings must use `@huggingface/transformers` in a Web Worker. Search must use `@orama/orama` persisted via `@orama/plugin-data-persistence` to IndexedDB.
3. **No Private Secrets:** Do not create `.env` files with secret keys. The app runs in userland (browser/desktop); any API keys added in the future must be supplied by the user in settings and saved to local storage.
4. **Shared Codebase:** Every frontend component must run identically in standard web browsers and inside the Electron shell. Do not invoke Node-specific APIs (`fs`, `child_process`, `path`) directly in the React view layer.

## Verification Workflow
Before marking any task complete:
1. Run `npm run build` to verify clean TypeScript compilation and Vite bundling.
2. Run `npm test` to verify vector search recall against `tests/fixtures/golden_baseline.json`.
```

### `ARCHITECTURE.md`
```markdown
# Architecture: Client-Side Local Vector Search

## 1. Overview
The application is a zero-cost, local-first search system operating across Web (PWA on Vercel) and Desktop (Electron). It completely replaces the prior Python + FastAPI + ChromaDB architecture.

## 2. Component Pipeline
```
[User Documents: PDF, MD, JSON]
               │
               ▼
   [Client Document Parser] (pdfjs-dist / native text)
               │
               ▼
      [Document Chunker] (Sliding word window)
               │
               ▼
    [Web Worker: Transformers.js] ── (all-MiniLM-L6-v2 ONNX)
               │
               ▼
      [Orama Vector Index] ◄─── IndexedDB Persistence
               ▲
               │ (Semantic Search Vector)
   [Web Worker: Transformers.js]
               ▲
               │ (Search Query)
        [React UI Layer]
```

## 3. Technology Stack
- **Frontend / Shell:** React 18, Vite, TypeScript.
- **Desktop Wrapper:** Electron (loads local static bundle from `dist/`).
- **Embedding Model:** `Xenova/all-MiniLM-L6-v2` via `@huggingface/transformers` (Quantized ONNX running in WebAssembly/WebGPU).
- **Vector Database:** `@orama/orama` with `@orama/plugin-data-persistence`.
- **Parsing:** `pdfjs-dist` (browser-side PDF text extraction), native JSON, and markdown string splitters.
```

### `README.md`
```markdown
# Local Vector Search App

A local-first semantic document search application with zero recurring hosting costs. Runs as a Progressive Web App (PWA) via Vercel or as an offline desktop application via Electron.

## Features
- **100% Local Processing:** Embeddings and vector similarity search execute entirely on the client machine.
- **Privacy Preserving:** Documents never leave the user's browser or device.
- **Zero Server Costs:** Deployed as static HTML/JS/WASM files to Vercel's free edge network.
- **Multi-Format Ingestion:** Ingests and indexes PDF, Markdown, Plain Text, and JSON.

## Quickstart

### Development
```bash
npm install
npm run dev
```

### Run Electron Desktop Locally
```bash
npm run electron:dev
```

### Test Parity with Golden Baseline
```bash
npm test
```

### Build Releases
```bash
# Static Web Bundle (for Vercel)
npm run build

# Standalone Desktop App (Mac, Windows, Linux)
npm run electron:build
```
```

---

## 4. Directory Structure

```text
├── electron/
│   ├── main.ts
│   └── preload.ts
├── src/
│   ├── services/
│   │   └── orama.ts
│   ├── utils/
│   │   └── parser.ts
│   ├── App.tsx
│   ├── main.tsx
│   ├── worker.ts
│   └── vite-env.d.ts
├── tests/
│   ├── fixtures/
│   │   └── golden_baseline.json
│   ├── export_golden_baseline.py
│   └── parity.test.ts
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
└── electron-builder.json
```

---

## 5. Configuration & Dependencies

### `package.json`
```json
{
  "name": "local-vector-app",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "main": "dist-electron/main.js",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "electron:dev": "vite",
    "electron:build": "npm run build && electron-builder"
  },
  "dependencies": {
    "@huggingface/transformers": "^3.0.2",
    "@orama/orama": "^2.0.22",
    "@orama/plugin-data-persistence": "^2.0.22",
    "pdfjs-dist": "^4.6.82",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "electron": "^33.2.0",
    "electron-builder": "^25.1.8",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vite-plugin-electron": "^0.28.8",
    "vite-plugin-electron-renderer": "^0.14.5",
    "vitest": "^2.1.4"
  }
}
```

### `tsconfig.json`
```json
{
  "compilerOptions": {
    "target": "ESNext",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ESNext"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": false,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"]
}
```

### `vite.config.ts`
```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import electron from 'vite-plugin-electron';
import renderer from 'vite-plugin-electron-renderer';

export default defineConfig(({ mode }) => {
  const isElectron = process.env.ELECTRON === 'true';

  return {
    plugins: [
      react(),
      isElectron && electron([
        {
          entry: 'electron/main.ts',
          vite: {
            build: {
              outDir: 'dist-electron',
            },
          },
        },
      ]),
      isElectron && renderer(),
    ].filter(Boolean),
    build: {
      target: 'esnext',
      outDir: 'dist',
    },
    worker: {
      format: 'es',
    },
  };
});
```

---

## 6. Implementation Code

### Step 1: Web Worker for Embeddings (`src/worker.ts`)
```typescript
import { pipeline, env, FeatureExtractionPipeline } from '@huggingface/transformers';

env.allowLocalModels = false;
env.useBrowserCache = true;

let extractor: FeatureExtractionPipeline | null = null;

async function getExtractor(): Promise<FeatureExtractionPipeline> {
  if (!extractor) {
    extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
      quantized: true,
    });
  }
  return extractor;
}

self.onmessage = async (e: MessageEvent) => {
  const { id, type, payload } = e.data;

  try {
    const pipe = await getExtractor();

    if (type === 'EMBED_BATCH') {
      const texts: string[] = payload.texts;
      const embeddings: number[][] = [];

      for (let i = 0; i < texts.length; i++) {
        const output = await pipe(texts[i], { pooling: 'mean', normalize: true });
        embeddings.push(Array.from(output.data as Float32Array));

        if (i % 25 === 0 || i === texts.length - 1) {
          self.postMessage({ type: 'PROGRESS', current: i + 1, total: texts.length });
        }
      }

      self.postMessage({ id, type: 'EMBED_BATCH_SUCCESS', embeddings });
    }

    if (type === 'EMBED_QUERY') {
      const output = await pipe(payload.query, { pooling: 'mean', normalize: true });
      const embedding = Array.from(output.data as Float32Array);
      self.postMessage({ id, type: 'EMBED_QUERY_SUCCESS', embedding });
    }
  } catch (err: any) {
    self.postMessage({ id, type: 'ERROR', error: err.message });
  }
};
```

### Step 2: Document Ingestion & Chunking (`src/utils/parser.ts`)
```typescript
import * as pdfjsLib from 'pdfjs-dist';

pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`;

export interface DocumentChunk {
  text: string;
  source: string;
  chunkIndex: number;
}

export function chunkText(text: string, source: string, chunkSize = 400, overlap = 40): DocumentChunk[] {
  const clean = text.replace(/\s+/g, ' ').trim();
  const words = clean.split(' ');
  const chunks: DocumentChunk[] = [];
  let i = 0;
  let chunkIndex = 0;

  while (i < words.length) {
    const slice = words.slice(i, i + chunkSize).join(' ');
    if (slice.trim().length > 0) {
      chunks.push({ text: slice, source, chunkIndex });
      chunkIndex++;
    }
    i += chunkSize - overlap;
  }

  return chunks;
}

export async function parseFile(file: File): Promise<string> {
  const ext = file.name.split('.').pop()?.toLowerCase();

  if (ext === 'json') {
    const content = await file.text();
    const json = JSON.parse(content);
    return typeof json === 'string' ? json : JSON.stringify(json, null, 2);
  }

  if (ext === 'md' || ext === 'txt') {
    return await file.text();
  }

  if (ext === 'pdf') {
    const buffer = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buffer }).promise;
    let fullText = '';

    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const tokenized = await page.getTextContent();
      const pageStr = tokenized.items.map((item: any) => item.str).join(' ');
      text += `${pageStr}\n`;
    }
    return fullText;
  }

  throw new Error(`Unsupported file extension: .${ext}`);
}
```

### Step 3: Orama DB Management (`src/services/orama.ts`)
```typescript
import { create, insertMultiple, search, AnyOrama } from '@orama/orama';
import { persist, restore } from '@orama/plugin-data-persistence';

const DB_STORE_NAME = 'orama_local_store';

export interface ChunkRecord {
  id?: string;
  text: string;
  source: string;
  chunkIndex: number;
  embedding: number[];
}

let dbInstance: AnyOrama | null = null;

export async function getOrInitDB(): Promise<AnyOrama> {
  if (dbInstance) return dbInstance;

  try {
    dbInstance = await restore('idb', DB_STORE_NAME);
    return dbInstance!;
  } catch {
    dbInstance = await create({
      schema: {
        text: 'string',
        source: 'string',
        chunkIndex: 'number',
        embedding: 'vector[384]',
      },
    });
    return dbInstance;
  }
}

export async function addChunksToDB(chunks: ChunkRecord[]): Promise<void> {
  const db = await getOrInitDB();
  await insertMultiple(db, chunks);
  await persist(db, 'idb', DB_STORE_NAME);
}

export async function queryVectorDB(embedding: number[], limit = 5) {
  const db = await getOrInitDB();
  return await search(db, {
    mode: 'vector',
    vector: {
      value: embedding,
      property: 'embedding',
    },
    similarity: 0.65,
    limit,
  });
}
```

### Step 4: React UI (`src/App.tsx`)
```tsx
import React, { useState, useEffect, useRef } from 'react';
import { parseFile, chunkText, DocumentChunk } from './utils/parser';
import { getOrInitDB, addChunksToDB, queryVectorDB, ChunkRecord } from './services/orama';

export default function App() {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('Initializing DB...');
  const [isProcessing, setIsProcessing] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const workerRef = useRef<Worker | null>(null);

  useEffect(() => {
    getOrInitDB().then(() => setStatus('Ready'));

    workerRef.current = new Worker(new URL('./worker.ts', import.meta.url), {
      type: 'module',
    });

    return () => workerRef.current?.terminate();
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setIsProcessing(true);
    const chunksToIndex: DocumentChunk[] = [];

    try {
      for (const file of Array.from(files)) {
        setStatus(`Parsing ${file.name}...`);
        const text = await parseFile(file);
        const fileChunks = chunkText(text, file.name);
        chunksToIndex.push(...fileChunks);
      }

      setStatus(`Generating embeddings for ${chunksToIndex.length} chunks...`);

      const worker = workerRef.current;
      if (!worker) throw new Error('Worker not initialized');

      const handleBatchResponse = async (ev: MessageEvent) => {
        if (ev.data.type === 'PROGRESS') {
          setStatus(`Embedding: ${ev.data.current} / ${ev.data.total}`);
        }

        if (ev.data.type === 'EMBED_BATCH_SUCCESS') {
          worker.removeEventListener('message', handleBatchResponse);
          setStatus('Saving to local index...');

          const records: ChunkRecord[] = chunksToIndex.map((chunk, i) => ({
            text: chunk.text,
            source: chunk.source,
            chunkIndex: chunk.chunkIndex,
            embedding: ev.data.embeddings[i],
          }));

          await addChunksToDB(records);
          setStatus(`Indexed ${records.length} chunks successfully.`);
          setIsProcessing(false);
        }

        if (ev.data.type === 'ERROR') {
          worker.removeEventListener('message', handleBatchResponse);
          setStatus(`Error: ${ev.data.error}`);
          setIsProcessing(false);
        }
      };

      worker.addEventListener('message', handleBatchResponse);
      worker.postMessage({
        type: 'EMBED_BATCH',
        payload: { texts: chunksToIndex.map((c) => c.text) },
      });
    } catch (err: any) {
      setStatus(`Failed: ${err.message}`);
      setIsProcessing(false);
    }
  };

  const executeSearch = () => {
    if (!query.trim() || !workerRef.current) return;
    setIsProcessing(true);
    setStatus('Generating query embedding...');

    const worker = workerRef.current;
    const handleQueryResponse = async (ev: MessageEvent) => {
      if (ev.data.type === 'EMBED_QUERY_SUCCESS') {
        worker.removeEventListener('message', handleQueryResponse);
        setStatus('Searching...');
        const searchOutput = await queryVectorDB(ev.data.embedding, 5);
        setResults(searchOutput.hits.map((h) => h.document));
        setStatus('Ready');
        setIsProcessing(false);
      }
    };

    worker.addEventListener('message', handleQueryResponse);
    worker.postMessage({
      type: 'EMBED_QUERY',
      payload: { query },
    });
  };

  return (
    <div style={{ maxWidth: 700, margin: '40px auto', padding: '0 16px', fontFamily: 'system-ui' }}>
      <h1>Local Vector Search</h1>
      <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8, marginBottom: 20 }}>
        <input type="file" multiple accept=".pdf,.md,.txt,.json" onChange={handleFileUpload} disabled={isProcessing} />
        <p style={{ margin: '8px 0 0', fontSize: 14 }}>Status: <strong>{status}</strong></p>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        <input
          style={{ flex: 1, padding: 8 }}
          placeholder="Ask a question or search documents..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && executeSearch()}
          disabled={isProcessing}
        />
        <button onClick={executeSearch} disabled={isProcessing} style={{ padding: '8px 16px' }}>Search</button>
      </div>
      <div>
        {results.map((item, idx) => (
          <div key={idx} style={{ padding: 12, border: '1px solid #e0e0e0', borderRadius: 6, marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: '#666' }}>{item.source} (Chunk #{item.chunkIndex})</div>
            <div style={{ marginTop: 4 }}>{item.text}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

### Step 5: Electron Entrypoint (`electron/main.ts`)
```typescript
import { app, BrowserWindow } from 'electron';
import path from 'path';

function createWindow() {
  const win = new BrowserWindow({
    width: 1024,
    height: 768,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(__dirname, '../dist/index.html'));
  }
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
```

---

## 7. Step 7: Post-Migration Parity Verification

Run this test suite with `npm test` to verify search recall parity against the baseline.

### `tests/parity.test.ts`
```typescript
import { describe, it, expect, beforeAll } from 'vitest';
import fs from 'fs';
import path from 'path';
import { pipeline } from '@huggingface/transformers';
import { create, insertMultiple, search } from '@orama/orama';

describe('Search Quality Parity with Python Baseline', () => {
  let baseline: any;
  let oramaDB: any;

  beforeAll(async () => {
    const baselinePath = path.resolve(__dirname, 'fixtures/golden_baseline.json');
    if (!fs.existsSync(baselinePath)) {
      throw new Error("Missing golden_baseline.json! Run export_golden_baseline.py first.");
    }
    baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf-8'));

    oramaDB = await create({
      schema: {
        text: 'string',
        source: 'string',
        chunkIndex: 'number',
        embedding: 'vector[384]',
      },
    });

    const extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
      quantized: true,
    });

    const records = [];
    for (const file of baseline.files) {
      for (const chunk of file.chunks) {
        const out = await extractor(chunk.text, { pooling: 'mean', normalize: true });
        records.push({
          text: chunk.text,
          source: chunk.source,
          chunkIndex: chunk.chunk_index,
          embedding: Array.from(out.data as Float32Array),
        });
      }
    }

    await insertMultiple(oramaDB, records);
  }, 120000);

  it('retrieves relevant documents matching Python baseline recall', async () => {
    const extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
      quantized: true,
    });

    for (const queryCase of baseline.queries) {
      const qOutput = await extractor(queryCase.query, { pooling: 'mean', normalize: true });
      const qVec = Array.from(qOutput.data as Float32Array);

      const searchResults = await search(oramaDB, {
        mode: 'vector',
        vector: {
          value: qVec,
          property: 'embedding',
        },
        limit: 5,
      });

      const retrievedTexts = searchResults.hits.map((h: any) => h.document.text);
      const expectedTexts = queryCase.expected_top_hits.map((h: any) => h.text);

      const intersection = retrievedTexts.filter((t: string) => expectedTexts.includes(t));
      expect(intersection.length).toBeGreaterThan(0);
    }
  }, 60000);
});
```

---

## 8. Agent Execution Checklist

1. [ ] Run `python tests/export_golden_baseline.py` and ensure `tests/fixtures/golden_baseline.json` exists.
2. [ ] Write `AGENTS.md`, `ARCHITECTURE.md`, and `README.md`.
3. [ ] Delete all Python backend files, requirements files, and Chroma configs.
4. [ ] Install dependencies with `npm install`.
5. [ ] Run `npm test` to ensure parity validation passes.
6. [ ] Run `npm run build` to confirm static export builds into `dist/`.
7. [ ] Run `npm run electron:build` to confirm desktop packaging builds cleanly.