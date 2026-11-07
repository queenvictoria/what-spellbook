import type {
  Answer,
  Book,
  Character,
  Conversation,
  ConversationKind,
  ConversationSummary,
  Generation,
  Health,
  RunBooks,
  RunSummary,
  SearchFacetsResponse,
  SearchParams,
  SearchResult,
  Spell,
  SrdDocument,
  SrdSection,
} from './types'

/**
 * The backend base URL. `VITE_API_BASE` lets a build point somewhere else; the default
 * is the dev server, which is what anyone running `npm run dev` wants.
 */
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

/**
 * An error carrying the status code, because the code is what callers act on:
 * 404 "no such run" is a normal outcome to show as an empty state, 503 "model down" is
 * something to retry. The message alone cannot be distinguished.
 */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }

  /** A 4xx that retrying cannot fix, so the UI should say so rather than offer a retry. */
  get isPermanent() {
    return this.status >= 400 && this.status < 500
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    // fetch only rejects on a transport failure, and "the backend is not running" is
    // the overwhelmingly likely cause in development. Saying so saves a debugging loop.
    throw new ApiError(0, `Could not reach the API at ${BASE}. Is it running?`)
  }

  if (!response.ok) {
    throw new ApiError(response.status, await detail(response))
  }
  // 204 and friends carry no body.
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** FastAPI puts the message in `detail`; fall back to the raw text if it does not. */
async function detail(response: Response): Promise<string> {
  const body = await response.text()
  try {
    const parsed = JSON.parse(body)
    const value = parsed?.detail ?? parsed
    if (typeof value === 'string') return value
    // A validation error is a list of locations and messages; join the messages, since
    // that is the only part a user can act on.
    if (Array.isArray(value)) {
      return value.map((item) => item?.msg ?? JSON.stringify(item)).join('; ')
    }
    return JSON.stringify(value)
  } catch {
    return body || `Request failed with ${response.status}`
  }
}

const query = (params: Record<string, string | undefined>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  health: () => request<Health>('/api/health'),

  characters: () => request<string[]>('/api/characters'),

  character: (name?: string) =>
    request<Character>(`/api/character${query({ name })}`),

  askCharacter: (question: string, character?: string, threadId?: string) =>
    request<Answer>(
      `/api/character/ask${query({ question, character, thread_id: threadId })}`,
    ),

  sheetKeys: () => request<string[]>('/api/sheet-keys'),

  /** Generate, or replay the stored run for the same scenario, character and book count. */
  scenario: (scenario: string, character?: string) =>
    request<Generation>('/api/scenario', {
      method: 'POST',
      body: JSON.stringify({ scenario, character }),
    }),

  /** The cached run for a scenario, or null. A miss is normal, not an error. */
  cached: (scenario: string, character?: string) =>
    request<Generation | null>(`/api/cached${query({ scenario, character })}`),

  ask: (scenario: string, question: string, character?: string, threadId?: string) =>
    request<Answer>(`/api/ask${query({ scenario, character })}`, {
      method: 'POST',
      body: JSON.stringify({ question, character, thread_id: threadId }),
    }),

  rules: (question: string, threadId?: string) =>
    request<Answer>(`/api/rules${query({ question, thread_id: threadId })}`),

  /**
   * Explain a phrase selected from a book's prose.
   *
   * `selected_text`, not `selectedText`: FastAPI names the parameter and the query key
   * comes from it, so the camelCase spelling 422'd on every request.
   *
   * `context` is the sentence the selection came from, which the backend threads into the
   * prompt so the model can read "2 beams" as the *Eldritch Blast* beams. A 404 means the
   * SRD does not discuss the selection at all, which is a normal outcome to show.
   */
  rulesContextual: (
    selectedText: string,
    context?: string,
    documents: string[] = [],
    threadId?: string,
  ) => {
    const params = new URLSearchParams({ selected_text: selectedText })
    if (context) params.set('context', context)
    if (threadId) params.set('thread_id', threadId)
    // Repeated, not comma-joined: the backend declares it as a list query parameter, and a
    // joined value would resolve as one document named "Thorn Whip, Repelling Blast".
    for (const document of documents) params.append('document', document)
    return request<Answer>(`/api/rules/contextual?${params.toString()}`)
  },

  /**
   * One spell's own text. A 404 means neither the SRD nor the corpus has that name.
   *
   * `character` decides the `scaling` note — "2 beams (L5)" is only true of a level 5
   * Warlock — so it is passed through rather than left to the server's default. Omit it
   * and the server's configured character is used.
   */
  spell: (name: string, character?: string) =>
    request<Spell>(`/api/spell${query({ name, character })}`),

  /**
   * One Eldritch Invocation's rules.
   *
   * Separate from `spell` because an invocation is a class feature, not a spell, and the
   * 2024 SRD does not publish them - the text comes from our own class context.
   */
  invocation: (name: string, character?: string) =>
    request<Spell>(`/api/invocation${query({ name, character })}`),

  /**
   * Every name the prose may mention, used to decide which mentions to link.
   *
   * Spells and invocations together: the books name both in the same sentence, and the
   * caller resolves each name against `spell` and falls back to `invocation`.
   */
  spells: () => request<string[]>('/api/spells'),

  /**
   * Every vendored SRD file, with its headings nested — the Rules screen's table of
   * contents.
   *
   * Sent whole rather than per file because it is small (seven files, ~1280 headings, no
   * text) and a screen that had to ask seven times to draw one list would show it filling
   * in. The text is a separate request, so drawing the tree costs nothing.
   */
  srd: () => request<SrdDocument[]>('/api/srd'),

  /**
   * One section of one SRD file, as renderable Markdown.
   *
   * Omit `slug` for the whole document, which is what a click on the file name asks for.
   * Deterministic, like `spell`: the text is read from the file, so it cannot paraphrase a
   * rule.
   */
  srdSection: (name: string, slug?: string) =>
    request<SrdSection>(
      `/api/srd/${encodeURIComponent(name)}${query({ slug })}`,
    ),

  history: (character?: string) =>
    request<RunSummary[]>(`/api/history${query({ character })}`),

  /**
   * Every stored ask/chat conversation, newest first.
   *
   * A conversation is a thread: the questions asked and the answers given, in order.
   * Listed rather than the individual answers because a follow-up is only meaningful
   * beside the question it followed.
   */
  conversations: (kind?: ConversationKind, character?: string) =>
    request<ConversationSummary[]>(
      `/api/conversations${query({ kind, character })}`,
    ),

  /** One stored conversation, every turn in order. */
  conversation: (reference: string, character?: string) =>
    request<Conversation>(
      `/api/conversations/${encodeURIComponent(reference)}${query({ character })}`,
    ),

  /**
   * Search the vector index directly.
   *
   * The diagnostic surface, not the recommender: it can return a spell the character could
   * never pick, on purpose. `class` is repeated rather than comma-joined because the
   * backend declares it as a list query parameter, and a joined value would resolve as one
   * class named "Wizard, Bard".
   */
  search: (params: SearchParams) => {
    const search = new URLSearchParams()
    if (params.query) search.set('query', params.query)
    if (params.mode) search.set('mode', params.mode)
    if (params.limit !== undefined) search.set('limit', String(params.limit))
    if (params.offset !== undefined) search.set('offset', String(params.offset))
    for (const name of params.classes ?? []) search.append('class', name)
    if (params.school) search.set('school', params.school)
    if (params.level_min !== undefined)
      search.set('level_min', String(params.level_min))
    if (params.level_max !== undefined)
      search.set('level_max', String(params.level_max))
    if (params.ritual !== undefined) search.set('ritual', String(params.ritual))
    if (params.spells_only !== undefined)
      search.set('spells_only', String(params.spells_only))
    if (params.all_terms !== undefined)
      search.set('all_terms', String(params.all_terms))
    if (params.doc_type) search.set('doc_type', params.doc_type)
    return request<SearchResult>(`/api/search?${search.toString()}`)
  },

  /** Every class, school and level the index holds, with counts. */
  searchFacets: () => request<SearchFacetsResponse>('/api/search/facets'),
  run: (id: string) => request<RunBooks>(`/api/runs/${encodeURIComponent(id)}`),

  rate: (
    id: string,
    body: { score: number; book?: string; notes?: string; outcome?: string },
  ) =>
    request<Book[]>(`/api/runs/${encodeURIComponent(id)}/rate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
}
