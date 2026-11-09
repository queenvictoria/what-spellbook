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
  /**
   * The book's prose only. A run stored before the delimited format was introduced still
   * has its title and pick list inside this text, because the old format had nowhere else
   * to put them; `name` and `picks` are authoritative either way.
   */
  text: string
  picks: Record<string, string[]>
  cache_path: string | null
  rating: Rating | null
}

export interface Generation {
  scenario: string
  answer: string
  books: Book[]
  /** Reasoning that applies to every book. Empty when the model wrote none. */
  preamble: string
  /** Which prepared spells and features pair with each book. Empty when none was written. */
  pairings: string
  prompt: string
  warnings: string[]
  from_cache: boolean
  model: string | null
  timings: Timings
  /** The stored run's id, for rating a book. Null when the run was not persisted. */
  run_id: string | null
  /**
   * The conversation a refinement belongs to, so a follow-up can be asked in context.
   * Null for a fresh generation, which is not a conversation.
   */
  thread_id: string | null
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
  /** Reasoning that applies to every book. Empty when the model wrote none. */
  preamble: string
  /** Which prepared spells and features pair with each book. */
  pairings: string
  /** The run's id, so a book opened from history is rateable. */
  run_id: string | null
}

/**
 * `source` is the field that matters most on this type. A `sheet` answer is read
 * verbatim from the character file and cannot be wrong; a `model` answer is generated
 * and can be. `rules` is a rule quoted from the 2024 SRD, and `rules-inferred` is an
 * answer interpreted from related SRD text when no heading names the question — an
 * interpretation must not look like a quotation. The UI must show which one it got.
 */
export interface Answer {
  question: string
  answer: string
  source: 'sheet' | 'model' | 'rules' | 'rules-inferred'
  field_name: string | null
  citations: string[]
  from_cache: boolean
  /**
   * The documents the answer was given, by name.
   *
   * Worth showing: an answer that says the SRD does not cover a spell reads very
   * differently once the reader can see the spell was never attached.
   */
  attachments: string[]
  /**
   * The conversation this answer belongs to. Pass it back to ask a follow-up in context,
   * and use it to read the exchange again later.
   */
  thread_id: string | null
}

/** One question and its answer, with the provenance a reader needs to trust it. */
export interface ConversationTurn {
  question: string
  answer: string
  source: Answer['source']
  asked_at: string | null
  field_name: string | null
  citations: string[]
  attachments: string[]
  from_cache: boolean
  model: string | null
}

/**
 * One row of the conversation listing: a thread, not a single answer.
 *
 * A follow-up is only meaningful beside the question it followed, so the listing is keyed
 * on the thread and the opening question is what names it.
 */
export interface ConversationSummary {
  id: string
  kind: ConversationKind
  opening: string
  character: string | null
  run_id: string | null
  created_at: string | null
  updated_at: string | null
  turn_count: number
  /** The most recent answer, so a listing can be scanned without opening every thread. */
  last_answer: string
}

/** A whole thread, every turn in order. */
export interface Conversation {
  id: string
  kind: ConversationKind
  opening: string
  character: string | null
  run_id: string | null
  created_at: string | null
  updated_at: string | null
  turns: ConversationTurn[]
}

/**
 * Which surface a conversation came from.
 *
 * The kind is part of a thread's identity because the same words asked of the sheet and
 * of the rulebook are different questions with different answers.
 */
export type ConversationKind = 'rules' | 'character' | 'selection' | 'refine'

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
  /**
   * What the spell does at the loaded character's level, e.g. `2 beams (L5)`.
   *
   * Null when the spell does not scale with level, when no character is loaded, or when
   * the character is below the first level the spell states. Read out of the spell's own
   * text, so it is a rule rather than a guess — but it is that rule *applied to a sheet*,
   * which is why it is a field of its own and not folded into `text`.
   */
  scaling: string | null
}

/**
 * One heading in a vendored SRD file, nested under its parent. Mirrors `SrdHeadingSchema`.
 *
 * `slug` is the anchor to ask for, and it is de-duplicated within its document: the SRD
 * repeats headings — `classes.md` has six `Level 1: Spellcasting` sections, one per class —
 * so a slug derived from the text alone would collide and every link after the first would
 * open the wrong section.
 */
export interface SrdHeading {
  text: string
  level: number
  slug: string
  children: SrdHeading[]
}

/**
 * One vendored SRD file, as a table of contents. Mirrors `SrdDocumentSchema`.
 *
 * The tree carries no text. The seven files are ~880KB of Markdown between them, and a
 * screen that only wants to draw a list of links should not pay for the rulebook — the
 * text is fetched per section, on the click that needs it.
 */
export interface SrdDocument {
  name: string
  title: string
  path: string
  headings: SrdHeading[]
}

/**
 * One step in a section's ancestry, for a breadcrumb. Mirrors `SrdCrumbSchema`.
 *
 * `slug` is what a click asks for, so a crumb is a link to the parent rule rather than just
 * a label. The document's own root heading is included as the first crumb, which is why a
 * section's trail starts at the file rather than at its first real subdivision.
 */
export interface SrdCrumb {
  text: string
  slug: string
  level: number
}

/**
 * One section of one SRD file, as renderable Markdown. Mirrors `SrdSectionSchema`.
 *
 * `text` includes the heading line, so the fragment reads as a document rather than a body
 * with no title. `source` is always the vendored SRD: this is quoted, never generated.
 *
 * `ancestors` is the chain of headings above this one, outermost first, excluding the
 * heading itself. It is sent rather than left for the client to derive because the client
 * only holds the table of contents, and walking it to find a parent would mean a second
 * lookup for something the server already knows.
 */
export interface SrdSection {
  document: string
  title: string
  heading: string
  slug: string
  path: string
  text: string
  source: string
  ancestors: SrdCrumb[]
}

/**
 * One class context file in the list, without its text. Mirrors `ClassContextFileSchema`.
 *
 * `name` is the phrase a reader recognises — "Warlock", "Celestial Patron" — derived from
 * the file's own title rather than from its filename, which is a path segment (`celestial`).
 * It is what the prose is searched for, so it has to be the phrase the prose uses.
 */
export interface ClassContextFile {
  name: string
  title: string
  path: string
}

/**
 * One class context file, as renderable Markdown. Mirrors `ClassContextSchema`.
 *
 * Deliberately not an `SrdSection`: these files are our own summary of a class, written to
 * be read by a model, and they are not the rulebook. `source` is always `class-context`, and
 * the card shows a different badge for it — a summary must not be able to look like a
 * quotation.
 */
export interface ClassContext {
  name: string
  title: string
  path: string
  text: string
  source: string
}

/**
 * One file of the optional rulebook source, without its text.
 *
 * Mirrors `IonasFileSchema`. `/api/ionas` returns an empty list when the source is not
 * installed, which is the normal state of a checkout that does not have it — so a caller
 * shows nothing rather than an error, and the feature simply is not there.
 */
export interface IonasFile {
  name: string
  title: string
  path: string
  kind: string
  sections: number
}

/**
 * One rule from the optional rulebook source, quoted.
 *
 * Mirrors `IonasSectionSchema`. `source` is always `ionas-politis`: a third-party scan of
 * the 2024 books, not the SRD, so the card shows a different badge. It fills a real gap —
 * non-SRD subclasses like the Celestial Patron and the Diviner — and is lower quality than
 * the SRD where the two overlap.
 */
export interface IonasSection {
  name: string
  title: string
  slug: string
  path: string
  text: string
  kind: string
  source: string
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

/**
 * One distinct spell a search returned, with the chunk that matched it.
 *
 * Distinct spells, not chunks: the index holds ~1280 chunks for 544 spells, so a raw
 * result list would show the same spell two or three times and read as a duplicate bug.
 */
export interface SearchHit {
  name: string
  level: number | null
  /** "Cantrip" / "Level 3" / "Not a spell", computed server-side so it is written once. */
  level_label: string
  school: string | null
  classes: string[]
  ritual: boolean
  is_spell: boolean
  filename: string
  text: string
  /**
   * Which kind of indexed text this is: `spell`, `item`, `srd` or `ionas-politis`.
   *
   * Needed to tell a rule from a spell, because a rule row has no school and a level of 0 —
   * inferring the type from those would call every rule a cantrip. The two rule types are
   * distinguished because they are not equally authoritative: the SRD is the 2024 authority,
   * while `ionas-politis` is a third-party scan of the books.
   */
  doc_type: 'spell' | 'item' | 'srd' | 'ionas-politis'
  /** For an SRD row, the document and heading it came from, so the hit can be opened. */
  document: string | null
  slug: string | null
  /** How many of this spell's chunks matched, not how many it has. */
  chunks: number
  /**
   * Chroma's distance for the best chunk, or null when the store cannot score.
   *
   * Lower is closer. It is **not** a percentage and must not be shown as one — the scale
   * depends on the embedding model, so a number is only meaningful next to another number
   * from the same query.
   */
  distance: number | null
  /** How many of the query's words the matching chunks contain. */
  terms_matched: number
}

export interface SearchFacet {
  value: string
  count: number
}

export interface SearchLevelFacet {
  level: number
  label: string
  count: number
}

/** What the index holds, so the filter controls offer values that actually exist. */
export interface SearchFacets {
  classes: SearchFacet[]
  schools: SearchFacet[]
  levels: SearchLevelFacet[]
  rituals: number
  spells: number
  chunks: number
  /** How many rows of each kind the collection holds, including the vendored SRD. */
  doc_types: SearchFacet[]
}

export interface SearchFacetsResponse {
  index_version: number
  facets: SearchFacets
}

/**
 * One search over the vector index.
 *
 * `where` is the Chroma clause actually sent, echoed back because a filter that silently
 * matches nothing is the commonest failure here and the clause is the fastest way to see
 * why. `total_matching` counts the distinct spells the *criteria* admit — filters always,
 * plus the words in text mode — so it says whether a filter is too narrow. A vector search
 * has no relevance threshold, so it cannot say how many spells are relevant.
 */
export interface SearchResult {
  query: string
  mode: 'vector' | 'text' | 'hybrid'
  limit: number
  offset: number
  hits: SearchHit[]
  total_matching: number
  elapsed_ms: number
  where: Record<string, unknown> | null
  filters: {
    classes: string[]
    school: string | null
    level_min: number | null
    level_max: number | null
    ritual: boolean | null
    spells_only: boolean
    /** `null` when the caller named no type, in which case `spells_only` decided. */
    doc_type: 'all' | 'spell' | 'item' | 'srd' | 'ionas-politis' | null
  }
  /** Set when the result needs explaining: an unsatisfiable filter, an AND that found
   * nothing, or a candidate cap that truncated the ranking. */
  note: string | null
}

/** The filters a search request may carry. */
export interface SearchParams {
  query?: string
  mode?: 'vector' | 'text' | 'hybrid'
  limit?: number
  offset?: number
  classes?: string[]
  school?: string
  level_min?: number
  level_max?: number
  ritual?: boolean
  spells_only?: boolean
  all_terms?: boolean
  /**
   * Which kind of indexed text to search: `all`, `spell`, `item`, `srd` or
   * `ionas-politis`.
   *
   * **An explicit value wins outright.** `all` means the whole collection — the rulebook
   * included — even though `spells_only` defaults true; omitting the field leaves the choice
   * to `spells_only`. The two are never combined, because `all` with the default
   * `spells_only` used to resolve to spells only: the value that reads as "search
   * everything" returned the narrowest set, so a rules search could never find a rule.
   */
  doc_type?: 'all' | 'spell' | 'item' | 'srd' | 'ionas-politis'
}

/** A stage of a run, in the order the CLI reports them. */
export const PHASES = ['retrieval', 'prompt', 'books'] as const

export const PHASE_LABELS: Record<string, string> = {
  retrieval: 'Fetching spells from Grimoire',
  prompt: 'Crafting prompt',
  books: 'Scribing Books of Shadow',
}

/**
 * The contextual menu's own stages.
 *
 * A separate list from `PHASES` rather than a reuse of it, because the work is different
 * work: nothing is ranked, nothing is filtered by class, and the spell texts that answer
 * the question are *attached* rather than retrieved - which is the stage a reader most
 * wants to see, since a missing attachment is invisible in the answer text.
 */
export const CONTEXT_STAGES = ['analyse', 'gather', 'prompt', 'answer'] as const

export const CONTEXT_STAGE_LABELS: Record<string, string> = {
  analyse: 'Analysing the selection',
  gather: 'Retrieving context',
  prompt: 'Crafting prompt',
  answer: 'Cogitating',
}
