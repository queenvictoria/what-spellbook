/**
 * The one setting the browser owns: which API to talk to.
 *
 * Everything else the Settings page edits — the models and the OpenRouter key — is read by
 * the *backend* when it builds a model client, so a browser copy would be decorative. This
 * one is different in kind: the address has to be known before a request can be made at all,
 * so it cannot be fetched from the server it points at. It lives in `localStorage` for that
 * reason and for no other.
 *
 * The build-time `VITE_API_BASE` remains the default, because a deployment should still be
 * able to bake the address in. A saved value is an override for the case that needs it: a
 * second API on another port, a copy on the LAN, a preview build pointed at a dev server.
 */

/** `VITE_API_BASE` from the build, or the dev server every `npm run dev` wants. */
export const BUILD_API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const STORAGE_KEY = 'what-loadout.apiBase'

/** The saved override, or null when the build's default should be used. */
export function readApiBase(): string | null {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    return saved && saved.trim() ? saved.trim() : null
  } catch {
    // Storage can be unavailable — a hard-blocked cookie setting, a sandboxed frame — and a
    // settings screen must not be the thing that breaks the app. Falling back to the build
    // default is the same behaviour as having saved nothing.
    return null
  }
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

/**
 * Save an override, or clear it by passing null/blank.
 *
 * Returns nothing rather than throwing: the caller is a form that also has server-side saves
 * to report, and a browser that refuses to store is a reason to *say* so, not to fail the
 * whole submission.
 */
export function writeApiBase(value: string | null): boolean {
  try {
    if (value === null || !value.trim()) {
      window.localStorage.removeItem(STORAGE_KEY)
      return true
    }
    window.localStorage.setItem(STORAGE_KEY, value.trim())
    return true
  } catch {
    return false
  }
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
