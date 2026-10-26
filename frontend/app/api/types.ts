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
  /** The stored run's id, for rating a book. Null when the run was not persisted. */
  run_id: string | null
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
  /** The run's id, so a book opened from history is rateable. */
  run_id: string | null
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

export interface SpellComponents {
  letters: string[]
  /** `V (Verbal), S (Somatic)` — the shorthand with what it stands for. */
  expanded: string
  material: string | null
  consumed: boolean
}

export interface SpellDamage {
  /** A roll (`8d6`, `10d6+40`) or a count of instances (`5x` for five separate hits). */
  dice: string
  types: string[]
  /** The caster picks the type at cast time, as distinct from the type being unknown. */
  chosen_type: boolean
}

/**
 * A spell's stat block, read back out of its own text rather than generated.
 *
 * Every value is one the file already wrote — the point is that the file does not explain
 * itself. `V` is Verbal only if you have memorised the Components rule, and the damage sits
 * in the description's second paragraph where it is the most important number on the card.
 */
export interface SpellStats {
  casting_time: string
  ritual: boolean
  range: string | null
  components: SpellComponents | null
  duration: string | null
  concentration: boolean
  damage: SpellDamage[]
}

/**
 * One spell, quoted from the vendored SRD. Mirrors `SpellSchema`.
 *
 * Unlike an `Answer` there is no `source` ambiguity: this is read straight from the SRD
 * file, so it cannot be a model's guess about what the spell says.
 */
export interface Spell {
  name: string
  text: string
  url: string
  source: string
  /**
   * Null for anything that is not a spell. An Eldritch Invocation is quoted through this
   * same card and is a class feature, so it gets no stat block rather than an empty one.
   */
  stats: SpellStats | null
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
