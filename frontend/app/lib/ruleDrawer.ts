/**
 * Opening a rule in the pull-out drawer instead of navigating to the Rules tab.
 *
 * Kept apart from the provider component for the same reason `spellDrawer.ts` is: a module
 * exporting both a component and a hook cannot be hot-reloaded without discarding the page.
 */
import { createContext, useContext, useEffect } from 'react'
import type { RefObject } from 'react'

/** A document, and optionally one heading inside it. */
export interface RuleTarget {
  /**
   * Which kind of document this is, because the kinds are fetched differently and are not
   * equally authoritative.
   *
   * `srd` is the vendored 2024 rulebook, quoted. `class` is our own summary of a class,
   * written to be read by a model - it is not the rulebook, and the card says so. `rulebook`
   * is the optional third-party source, which is a transcription rather than the SRD.
   * One target type with a discriminator rather than three contexts, because a reader
   * following a link does not care which kind it is: the panel is the same panel.
   */
  kind: 'srd' | 'class' | 'rulebook'
  /**
   * The SRD file stem (`classes`), the repo-relative class context path
   * (`context/classes/warlock/base.md`), or the rule's name for `rulebook`.
   */
  document: string
  slug: string | null
  /**
   * A heading *inside* the section to scroll to, when the section is opened as a parent.
   *
   * A breadcrumb opens the parent rule but the reader was reading the child, and a parent's
   * text contains its children - so without this the panel opens at the top of a long section
   * and the reader has to find their place again. It is a separate field from `slug` because
   * the two are different things: `slug` is what is fetched, `anchor` is where to land.
   */
  anchor?: string | null
}

/**
 * Opens the drawer on a rule. A no-op until the provider mounts, so a renderer can call it
 * without checking - which is what lets a citation stay a plain component.
 */
export const OpenRuleContext = createContext<(target: RuleTarget | null) => void>(
  () => {},
)

export function useOpenRule() {
  return useContext(OpenRuleContext)
}

/**
 * Scroll the heading a fragment names into view, once it is on the page.
 *
 * The browser does this itself for a fragment on load, but not for one that arrives after
 * the content does - and here the content always arrives after: the section is fetched, so
 * at the moment the URL changes there is no element with that id yet.
 *
 * `contentKey` identifies what is rendered, and is null until it is ready. It is a parameter
 * rather than a boolean because the anchor alone is not enough to know when to scroll again:
 * following a breadcrumb from a child to its parent keeps the *same* anchor while replacing
 * the whole card, so an effect keyed on the anchor would never re-run and the reader would
 * land at the top of the parent - the exact thing the anchor is there to prevent.
 *
 * `container` scopes the lookup, and is not optional in practice: the Rules screen and the
 * drawer can show the same section at once, so the same heading id exists twice in the page.
 * A global lookup finds whichever comes first in the DOM - the screen behind the panel - and
 * scrolls that instead, leaving the panel where it was.
 *
 * `scrollIntoView` rather than `location.hash = …`, because the latter would push a history
 * entry for a scroll and make the back button undo a jump rather than a navigation.
 */
export function useAnchorScroll(
  anchor: string | null | undefined,
  contentKey: string | null,
  container?: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (!anchor || !contentKey) return
    const root = container?.current ?? document
    // An attribute selector rather than `getElementById`, so the lookup can be scoped - and
    // quoted, so a slug needs no escaping. `querySelector('#…')` would break on an id that
    // begins with a digit, which a slug derived from heading text can.
    const element = root.querySelector(`[id="${anchor}"]`)
    if (!element) return
    // `scroll-mt-*` on the heading keeps the sticky header from covering it, which
    // `scrollIntoView` honours and a hand-computed offset would have to duplicate.
    element.scrollIntoView({ block: 'start' })
  }, [anchor, contentKey, container])
}

/**
 * The document a repo-relative path points at, or null when it is not one this app can open.
 *
 * Every place this app prints provenance prints a path, and only some of them are documents:
 * a spell's footer may be `context/srd/spells.md` (the 2024 SRD), `context/classes/warlock/
 * base.md` (our own class summary) or `data/reddit-spence_post/...` (the retrieval corpus).
 * The corpus is not a rulebook page and has no headings to browse, so it stays plain text -
 * which is what keeps "a path is clickable" from quietly becoming "every path is clickable"
 * and then failing on the ones that are not.
 *
 * The two kinds are told apart here rather than by the caller, because the caller has a path
 * and nothing else. They are not interchangeable: the SRD is quoted and the class context is
 * our own summary, and the card shows a different badge for each.
 *
 * A `#slug` suffix is honoured, because `SrdCard` already prints one and a link that dropped
 * it would open the document at the top instead of at the rule the reader was looking at.
 */
export function ruleInPath(path: string | null | undefined): RuleTarget | null {
  if (!path) return null
  const trimmed = path.trim()

  const srd = /^context\/srd\/([A-Za-z0-9_-]+)\.md(?:#([A-Za-z0-9_-]+))?$/.exec(trimmed)
  if (srd) {
    // `PROVENANCE.md` is the CC-BY-4.0 attribution, not SRD text, and `rules.source_files`
    // excludes it from the corpus - so it is not a document the drawer can open either.
    if (srd[1] === 'PROVENANCE') return null
    return { kind: 'srd', document: srd[1], slug: srd[2] ?? null }
  }

  // Anchored to `context/classes/` and to a `.md` suffix, so a traversal does not match.
  // The backend refuses one anyway; this is the front end declining to offer it.
  if (/^context\/classes\/[A-Za-z0-9_/-]+\.md$/.test(trimmed)) {
    return { kind: 'class', document: trimmed, slug: null }
  }

  // The optional rulebook is deliberately *not* handled here, unlike the class context.
  // A class context file *is* the unit a reader opens, so a path is enough. A rulebook
  // file is not: `warlock-subclasses.json` holds six subclass features, so a path names
  // no single rule and the drawer would have nothing to open. Those hits carry a rule
  // *name* instead and open by name, which is why this stays plain text rather than
  // becoming a link that cannot resolve.
  return null
}
