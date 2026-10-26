# What Spellbook - front end

The browser UI for the spell recommender. React + Vite + TypeScript + Tailwind v4 with
shadcn-style components.

## Running

The API must be running first:

```bash
# repo root
uvicorn backend.api.main:get_app --factory --port 8000

# here
npm install
npm run dev        # http://localhost:5173
```

`VITE_API_BASE` overrides the API address (default `http://localhost:8000`).

`VITE_PORT` moves the dev server off 5173, for when another copy is already running. The
API's CORS list follows `FRONTEND_PORT`, so a second instance needs both set to the same
value or the browser blocks the request:

```bash
VITE_PORT=5273 VITE_API_BASE=http://localhost:8100 npm run dev
API_PORT=8100 FRONTEND_PORT=5273 uvicorn backend.api.main:get_app --factory --port 8100
```

## Scripts

| Command | Does |
| --- | --- |
| `npm run dev` | Dev server with HMR |
| `npm run build` | Typecheck (`tsc -b`) then build |
| `npm run lint` | ESLint |

## Layout

```
app/
  api/client.ts     typed client over the API, with ApiError carrying the status
  api/types.ts      mirrors backend/api/schemas.py by hand
  components/       Markdown renderer, source badge, stage progress, book panel
  components/ui/    shadcn-style primitives (button, card, input, badge, textarea)
  screens/          scenario, history, character, rules
  lib/              cn() and formatting helpers
```

## Two things to know before editing

**`api/types.ts` mirrors the Python schemas by hand.** Nothing checks that the two
agree, so if you change `backend/api/schemas.py`, change this file with it and keep both
open. `npm run build` will not notice the drift.

**An answer's `source` is always rendered.** `sheet` answers are read verbatim from the
character YAML and cannot be wrong; `model` answers are generated and can be; `rules`
answers are quoted from the 2024 SRD. `SourceBadge` exists so a plausible guess can
never look like a recorded fact. Do not render an answer without it.

Tailwind v4 keeps its configuration in `app/index.css` under `@theme` - there is no
`tailwind.config.js`. The `@` alias is declared in both `vite.config.ts` and
`tsconfig.app.json`, because Vite does not read the latter for resolution.
