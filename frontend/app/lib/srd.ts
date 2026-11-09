/**
 * Reading the vendored SRD as documents, and addressing a section of one.
 *
 * Kept apart from the components so this module exports only functions and hooks, which is
 * what lets React Fast Refresh reload the tree without discarding the page.
 */
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { SrdDocument, SrdHeading, SrdSection } from '@/api/types'

/**
 * The address of a section, so a rule can be bookmarked, shared and reached with the back
 * button.
 *
 * The document and the section are separate parameters rather than a path segment because
 * the Rules screen already owns `?spell=`, and a route of `/rules/:doc/:slug` would need a
 * second route entry for the same screen - two ways to reach one page, which is how the two
 * drift.
 */
export function srdHref(
  document: string,
  slug: string | null,
  fragment?: string | null,
): string {
  const params = new URLSearchParams({ doc: document })
  if (slug) params.set('section', slug)
  // The fragment goes last, and it has to: everything after a `#` is the fragment, so
  // `/rules#anchor?doc=…` would swallow the query string and the section would never be
  // read. `URLSearchParams` cannot carry it either - it would percent-encode the `#`.
  return `/rules?${params.toString()}${fragment ? `#${fragment}` : ''}`
}

/**
 * The anchor each heading in a section's own text should carry, in document order.
 *
 * A section's text runs from its heading line to the next heading at the same or a higher
 * level, so the headings inside it are exactly the subtree rooted at it. That is what makes
 * this a lookup rather than a guess - checked against all 1280 sections, where the two lists
 * agree line for line.
 *
 * The slugs come from the table of contents because that is the only place they exist: they
 * are de-duplicated per document, so `classes.md`'s eleven `Level 19: Epic Boon` headings are
 * `level-19-epic-boon` through `level-19-epic-boon-11`. Slugifying the heading text here
 * would produce the first of those every time and land on the wrong section.
 *
 * A heading the table of contents does not know about gets no anchor rather than an invented
 * one. Nothing in the corpus is in that position today, and a made-up slug is a link that
 * silently lands nowhere.
 */
export function srdAnchors(
  documents: SrdDocument[] | null,
  section: SrdSection,
): string[] {
  const found = documents?.find((document) => document.name === section.document)
  if (!found) return []
  // A whole-file view carries no slug of its own, and its text is the entire document, so
  // every heading in the file is in it.
  if (!section.slug) return [...walk(found.headings)].map((heading) => heading.slug)
  const root = findHeading(found.headings, section.slug)
  return root ? [...walk([root])].map((heading) => heading.slug) : []
}

function findHeading(headings: SrdHeading[], slug: string): SrdHeading | null {
  for (const heading of headings) {
    if (heading.slug === slug) return heading
    const found = findHeading(heading.children, slug)
    if (found) return found
  }
  return null
}

function* walk(headings: SrdHeading[]): Generator<SrdHeading> {
  for (const heading of headings) {
    yield heading
    yield* walk(heading.children)
  }
}

/**
 * A file's top-level sections, with a title-only wrapper flattened away.
 *
 * Every vendored file opens with an `#` heading that repeats the file's own name and holds
 * no text of its own - `# Classes` is immediately followed by `## Barbarian`. Rendering it
 * would put a single child called "Classes" under the "Classes" link, which expands to
 * nothing but the word again. The wrapper is dropped so the first level of the tree is the
 * first level of the rulebook.
 *
 * Exported because the keyword filter walks the same shape the tree draws. Two functions
 * that decided the structure independently could disagree about what the first level of a
 * file is, and only one of them would be the one on screen.
 */
export function documentSections(document: SrdDocument): SrdHeading[] {
  const [only, ...rest] = document.headings
  if (rest.length === 0 && only && only.text === document.title) return only.children
  return document.headings
}

/**
 * The table of contents, loaded once.
 *
 * One request for all seven files: the tree carries no text, so it is small, and asking per
 * file would show the list filling in. A failure is reported rather than retried - the
 * corpus is on disk, so a failure here means the backend is not running, which no amount of
 * retrying fixes.
 */
export function useSrdDocuments() {
  const [documents, setDocuments] = useState<SrdDocument[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let cancelled = false
    api
      .srd()
      .then((found) => {
        if (!cancelled) setDocuments(found)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { documents, error, loading: documents === null && error === null }
}

/**
 * One section's text, fetched on demand.
 *
 * The result carries the key it was fetched for and the caller's value is taken from it only
 * while that still matches. That is what clears the card the moment the selection changes,
 * without a setState in the effect body - which would cascade a second render on every
 * navigation.
 */
export function useSrdSection(document: string | null, slug: string | null) {
  const key = document ? `${document}:${slug ?? ''}` : null
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    if (!document) return
    let cancelled = false
    api
      .srdSection(document, slug ?? undefined)
      .then((section) => {
        if (!cancelled) setResult({ key: `${document}:${slug ?? ''}`, kind: 'ok', section })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setResult({
          key: `${document}:${slug ?? ''}`,
          kind: 'error',
          error: e,
        })
      })
    return () => {
      cancelled = true
    }
  }, [document, slug])

  const current = result?.key === key ? result : null
  return {
    section: current?.kind === 'ok' ? current.section : null,
    error: current?.kind === 'error' ? current.error : null,
    loading: key !== null && current === null,
  }
}

type Result =
  | { key: string; kind: 'ok'; section: SrdSection }
  | { key: string; kind: 'error'; error: unknown }
