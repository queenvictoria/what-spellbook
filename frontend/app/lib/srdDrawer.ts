/**
 * Opening a rule in the pull-out drawer instead of navigating to the Rules tab.
 *
 * Kept apart from the provider component for the same reason `spellDrawer.ts` is: a module
 * exporting both a component and a hook cannot be hot-reloaded without discarding the page.
 */
import { createContext, useContext } from 'react'

/** A document, and optionally one heading inside it. */
export interface SrdTarget {
  document: string
  slug: string | null
}

/**
 * Opens the drawer on a rule. A no-op until the provider mounts, so a renderer can call it
 * without checking - which is what lets a citation stay a plain component.
 */
export const OpenSrdContext = createContext<(target: SrdTarget | null) => void>(
  () => {},
)

export function useOpenSrd() {
  return useContext(OpenSrdContext)
}

/**
 * The rule a repo-relative path points at, or null when it is not vendored SRD text.
 *
 * Every place this app prints provenance prints a path, and only some of them are rules:
 * a spell's footer may be `context/srd/spells.md` (the 2024 SRD) or
 * `data/reddit-spence_post/...` (the retrieval corpus). The corpus is not a rulebook page
 * and has no headings to browse, so it stays plain text - which is what keeps "a path is
 * clickable" from quietly becoming "every path is clickable" and then failing on the ones
 * that are not.
 *
 * A `#slug` suffix is honoured, because `SrdCard` already prints one and a link that
 * dropped it would open the document at the top instead of at the rule the reader was
 * looking at.
 */
export function srdInPath(path: string | null | undefined): SrdTarget | null {
  if (!path) return null
  const match = /^context\/srd\/([A-Za-z0-9_-]+)\.md(?:#([A-Za-z0-9_-]+))?$/.exec(
    path.trim(),
  )
  if (!match) return null
  // `PROVENANCE.md` is the CC-BY-4.0 attribution, not SRD text, and `rules.source_files`
  // excludes it from the corpus - so it is not a document the drawer can open either.
  if (match[1] === 'PROVENANCE') return null
  return { document: match[1], slug: match[2] ?? null }
}
