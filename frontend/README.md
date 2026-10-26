# What Spellbook - front end

The browser UI for the spell recommender. React + Vite + TypeScript + Tailwind v4 with
shadcn-style components.

## Running

The API must be running first:

```bash
# repo root
uvicorn api.main:get_app --factory --app-dir src --port 8000

# here
npm install
npm run dev        # http://localhost:5173
```

`VITE_API_BASE` overrides the API address (default `http://localhost:8000`).

## Scripts

| Command | Does |
| --- | --- |
| `npm run dev` | Dev server with HMR |
| `npm run build` | Typecheck (`tsc -b`) then build |
| `npm run lint` | ESLint |

## Layout

```
src/
  api/client.ts     typed client over the API, with ApiError carrying the status
  api/types.ts      mirrors src/api/schemas.py by hand
  components/       Markdown renderer, source badge, stage progress, book panel
  components/ui/    shadcn-style primitives (button, card, input, badge, textarea)
  screens/          scenario, history, character, rules
  lib/              cn() and formatting helpers
```

## Two things to know before editing

**`api/types.ts` mirrors the Python schemas by hand.** Nothing checks that the two
agree, so if you change `src/api/schemas.py`, change this file with it and keep both
open. `npm run build` will not notice the drift.

**An answer's `source` is always rendered.** `sheet` answers are read verbatim from the
character YAML and cannot be wrong; `model` answers are generated and can be; `rules`
answers are quoted from the 2024 SRD. `SourceBadge` exists so a plausible guess can
never look like a recorded fact. Do not render an answer without it.

Tailwind v4 keeps its configuration in `src/index.css` under `@theme` - there is no
`tailwind.config.js`. The `@` alias is declared in both `vite.config.ts` and
`tsconfig.app.json`, because Vite does not read the latter for resolution.
