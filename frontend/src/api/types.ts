/**
 * Mirrors `src/api/schemas.py`.
 *
 * Hand-written rather than generated: the surface is small, and a generated client
 * would need the dev server running to regenerate. If the Python schemas change, this
 * is the file to change with them - `npm run typecheck` will not catch the drift, so
 * keep the two open side by side.
 */

export interface Timings {
  phases: Record<string, number>
  total_seconds: number | null
  unaccounted_seconds: number | null
}

export interface Rating {
  score: number | null
  rated_at: string | null
  notes: string | null
  outcome: string | null
}

export interface Book {
  index: number
  name: string
  text: string
  picks: Record<string, string[]>
  cache_path: string | null
  rating: Rating | null
}

export interface Generation {
  scenario: string
  answer: string
  books: Book[]
  prompt: string
  warnings: string[]
  from_cache: boolean
  model: string | null
  timings: Timings
}

export interface RunSummary {
  id: string
  scenario: string
  character: string | null
  level: number | null
  created_at: string | null
  model: string | null
  book_count: number
  book_names: string[]
  timings: Timings
}

export interface RunBooks {
  scenario: string
  created_at: string | null
  books: Book[]
}

/**
 * `source` is the field that matters most on this type. A `sheet` answer is read
 * verbatim from the character file and cannot be wrong; a `model` answer is generated
 * and can be. The UI must show which one it got.
 */
export interface Answer {
  question: string
  answer: string
  source: 'sheet' | 'model' | 'rules'
  field_name: string | null
  citations: string[]
  from_cache: boolean
}

export interface Character {
  name: string
  sheet: Record<string, unknown>
  text: string
}

export interface Health {
  status: string
  character: string | null
  model: string | null
  index_version: number
  cache_dir: string
}

/** A stage of a run, in the order the CLI reports them. */
export const PHASES = ['retrieval', 'prompt', 'books'] as const

export const PHASE_LABELS: Record<string, string> = {
  retrieval: 'Fetching spells from Grimoire',
  prompt: 'Crafting prompt',
  books: 'Scribing Books of Shadow',
}
