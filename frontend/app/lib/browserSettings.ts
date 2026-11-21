/**
 * The settings the browser owns, which is now all of them.
 *
 * `localStorage` is the store of record for the models and the OpenRouter key, because that is
 * where the user set them and they have to survive without a server-side file. The API has no
 * settings endpoint of its own that keeps anything: `PUT /api/settings` holds what it is sent
 * *in memory for the life of the process* so the model client can be built from it, and
 * nothing is written to disk. So a browser is the only durable copy, and the Next.js-style
 * "server is the source of truth" model does not apply here.
 *
 * The one thing that cannot be a browser value is which settings the *server* pinned in its
 * environment before it started. That outranks anything sent from here, so the page asks for
 * it (`Settings.pinned`) and says so rather than letting a save look ignored.
 *
 * The API address is the same idea taken further: it has to be known before a request can be
 * made, so it cannot even be sent anywhere.
 */

/** `VITE_API_BASE` from the build, or the dev server every `npm run dev` wants. */
export const BUILD_API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const API_BASE_KEY = 'what-loadout.apiBase'
const MODELS_KEY = 'what-loadout.models'
const CHARACTER_KEY = 'what-loadout.character'

/** The model settings a user has stored in this browser. */
export interface StoredModelSettings {
  reasoning_provider?: string
  reasoning_model?: string
  fast_provider?: string
  fast_model?: string
  api_key?: string
  anthropic_api_key?: string
  ollama_model?: string
}

/**
 * Both stores degrade to "nothing saved" rather than throwing.
 *
 * Storage can be unavailable - a hard-blocked cookie setting, a sandboxed frame - and a
 * settings screen must not be the thing that breaks the app. Reading nothing gives exactly the
 * behaviour of having saved nothing, which is the fallback every caller already handles.
 */
function read(key: string): string | null {
  try {
    const value = window.localStorage.getItem(key)
    return value && value.trim() ? value : null
  } catch {
    return null
  }
}

function write(key: string, value: string | null): boolean {
  try {
    if (value === null || !value.trim()) {
      window.localStorage.removeItem(key)
    } else {
      window.localStorage.setItem(key, value)
    }
    return true
  } catch {
    return false
  }
}

/** The saved API override, or null when the build's default should be used. */
export function readApiBase(): string | null {
  const saved = read(API_BASE_KEY)
  return saved ? saved.trim() : null
}

/**
 * The address requests actually go to: the saved override, else the build's default.
 *
 * Normalised without a trailing slash so `${base}${path}` never produces a double slash,
 * which some servers treat as a different route and 404.
 */
export function apiBase(): string {
  return (readApiBase() ?? BUILD_API_BASE).replace(/\/+$/, '')
}

/** Whether a saved override differs from the build's default. */
export function hasApiBaseOverride(): boolean {
  return readApiBase() !== null
}

/** Save an override, or clear it by passing null/blank. Returns whether it was stored. */
export function writeApiBase(value: string | null): boolean {
  return write(API_BASE_KEY, value)
}

/**
 * The character last chosen on the Character tab, or null when none has been.
 *
 * Stored here rather than on the server for the same reason as everything else in this file:
 * which sheet a reader is looking at is a property of *them*, not of the process. A second
 * browser should be free to look at a different character without changing the first one's
 * screen, and a server-side value would make the choice global.
 *
 * `null` is a real answer and is deliberately distinct from "the server's default": it means
 * this browser has no opinion, so the server's `CHARACTER` / `--character` decides. That is
 * what keeps a fresh checkout working with no interaction.
 */
export function readCharacter(): string | null {
  const saved = read(CHARACTER_KEY)
  return saved ? saved.trim() : null
}

/** Remember the chosen character, or forget it by passing null/blank. */
export function writeCharacter(value: string | null): boolean {
  return write(CHARACTER_KEY, value)
}

/** The model settings stored in this browser, or an empty object when none are. */
export function readModelSettings(): StoredModelSettings {
  const raw = read(MODELS_KEY)
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    // Only strings survive a round trip, so a hand-edited value cannot smuggle a non-string
    // into a field the API expects as text.
    return Object.fromEntries(
      Object.entries(parsed).filter(([, value]) => typeof value === 'string'),
    ) as StoredModelSettings
  } catch {
    // A corrupt entry is treated as nothing saved rather than as a hard failure: the user's
    // next save overwrites it, and the page still opens with the server's defaults.
    return {}
  }
}

/** Store the model settings, replacing whatever was there. Returns whether it was stored. */
export function writeModelSettings(values: StoredModelSettings): boolean {
  return write(MODELS_KEY, JSON.stringify(values))
}

/** Forget the stored model settings, so the server's defaults apply again. */
export function clearModelSettings(): boolean {
  return write(MODELS_KEY, null)
}

/**
 * Reject an address a request could not use, before it is saved and every call breaks.
 *
 * A bare `localhost:8000` is the mistake worth catching: it parses, it *looks* right, and
 * `fetch` treats it as a relative path against the page's own origin — so the app quietly
 * talks to itself and every endpoint 404s, with nothing on screen pointing at this field.
 */
export function apiBaseError(value: string): string | null {
  const text = value.trim()
  if (!text) return null
  let parsed: URL
  try {
    parsed = new URL(text)
  } catch {
    return 'That is not a URL. Include the scheme, for example http://localhost:8000'
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    // A bare `localhost:8000` does not fail to parse - `new URL` reads `localhost:` as the
    // protocol - so it lands here rather than in the catch above. Naming the missing scheme
    // is the useful thing to say, because "not localhost" describes the parser's reading
    // rather than the mistake. The app would otherwise quietly treat the address as a
    // relative path and every screen would 404 with nothing pointing at this box.
    if (!text.includes('//')) {
      return 'That is missing its scheme. Try http://' + text.replace(/^\/+/, '')
    }
    return `Only http and https can be reached, not ${parsed.protocol.replace(':', '')}.`
  }
  return null
}
