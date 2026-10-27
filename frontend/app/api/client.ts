import type {
  Answer,
  Book,
  Character,
  Generation,
  Health,
  RunBooks,
  RunSummary,
  Spell,
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

  askCharacter: (question: string, character?: string) =>
    request<Answer>(`/api/character/ask${query({ question, character })}`),

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

  ask: (scenario: string, question: string, character?: string) =>
    request<Answer>(`/api/ask${query({ scenario, character })}`, {
      method: 'POST',
      body: JSON.stringify({ question, character }),
    }),

  rules: (question: string) => request<Answer>(`/api/rules${query({ question })}`),

  /** Contextual rules answer based on selected text. A 404 means the SRD has no rule. */
  rulesContextual: (selectedText: string) =>
    request<Answer>(`/api/rules/contextual${query({ selectedText })}`),

  /** One spell's own text. A 404 means neither the SRD nor the corpus has that name. */
  spell: (name: string) => request<Spell>(`/api/spell${query({ name })}`),

  /**
   * One Eldritch Invocation's rules.
   *
   * Separate from `spell` because an invocation is a class feature, not a spell, and the
   * 2024 SRD does not publish them - the text comes from our own class context.
   */
  invocation: (name: string) => request<Spell>(`/api/invocation${query({ name })}`),

  /**
   * Every name the prose may mention, used to decide which mentions to link.
   *
   * Spells and invocations together: the books name both in the same sentence, and the
   * caller resolves each name against `spell` and falls back to `invocation`.
   */
  spells: () => request<string[]>('/api/spells'),

  history: (character?: string) =>
    request<RunSummary[]>(`/api/history${query({ character })}`),

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
