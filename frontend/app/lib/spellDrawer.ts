/**
 * Opening a spell in the pull-out drawer instead of navigating to the Rules tab.
 *
 * Kept apart from the provider component for the same reason `spellNames.ts` is: a module
 * exporting both a component and a hook cannot be hot-reloaded without discarding the page.
 */
import { createContext, useContext } from 'react'

/**
 * Opens the drawer on a spell. A no-op until the provider mounts, so a renderer can call
 * it without checking - which is what lets `SpellLink` stay a plain component.
 */
export const OpenSpellContext = createContext<(name: string) => void>(() => {})

export function useOpenSpell() {
  return useContext(OpenSpellContext)
}

/**
 * The spell a link points at, or null when it is not one this app can answer locally.
 *
 * The links the markdown renderer produces are all `/rules?spell=<name>`, so a link is
 * intercepted only when it resolves to content we already hold. Anything else - an
 * external address, a fragment, a link added later - returns null and is left to the
 * browser, which is what keeps "local links" from quietly becoming "all links".
 */
export function spellInHref(href: string | undefined | null): string | null {
  if (!href) return null
  try {
    // Resolved against the current origin so a relative href and an absolute one for this
    // site are treated alike, while another host is not.
    const url = new URL(href, window.location.origin)
    if (url.origin !== window.location.origin) return null
    if (url.pathname !== '/rules') return null
    const name = url.searchParams.get('spell')
    return name && name.trim() ? name : null
  } catch {
    return null
  }
}

/**
 * Whether a click should be left to the browser rather than opening the drawer.
 *
 * The link keeps its real `href` and is only intercepted when a plain left click was made.
 * A modified click is how a reader opens the Rules tab in a new tab, and swallowing it
 * would take away the one thing the href is there for - the task asks for the drawer on
 * a click *and* the link for Ctrl+click, so both have to keep working.
 */
export function shouldDeferToBrowser(event: {
  button: number
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  altKey: boolean
  defaultPrevented: boolean
}) {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey ||
    event.defaultPrevented
  )
}
