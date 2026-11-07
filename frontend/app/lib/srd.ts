/**
 * Reading the vendored SRD as documents, and addressing a section of one.
 *
 * Kept apart from the components so this module exports only functions and hooks, which is
 * what lets React Fast Refresh reload the tree without discarding the page.
 */
import { useEffect, useState } from 'react'

import { api, ApiError } from '@/api/client'
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
export function srdHref(document: string, slug: string | null): string {
  const params = new URLSearchParams({ doc: document })
  if (slug) params.set('section', slug)
  return `/rules?${params.toString()}`
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
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .srd()
      .then((found) => {
        if (!cancelled) setDocuments(found)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e))
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
          message: e instanceof ApiError ? e.message : String(e),
        })
      })
    return () => {
      cancelled = true
    }
  }, [document, slug])

  const current = result?.key === key ? result : null
  return {
    section: current?.kind === 'ok' ? current.section : null,
    error: current?.kind === 'error' ? current.message : null,
    loading: key !== null && current === null,
  }
}

type Result =
  | { key: string; kind: 'ok'; section: SrdSection }
  | { key: string; kind: 'error'; message: string }
