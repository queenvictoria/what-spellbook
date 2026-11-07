/**
 * Our own class context files, as documents a reader can open.
 *
 * These are the files spliced into a prompt as `=== CHARACTER CONTEXT ===` - the class-wide
 * rules, the pact, the patron. They are **not** the SRD: they are our summary of a class,
 * written to be read by a model, and the badge on the card says so. Keeping them a separate
 * kind of document from `SrdSection` is what stops a summary from wearing the quotation
 * badge, which is the one confusion `SourceBadge` exists to prevent.
 *
 * Kept apart from the components so this module exports only functions and hooks, which is
 * what lets React Fast Refresh reload the tree without discarding the page.
 */
import { useEffect, useState } from 'react'

import { api, ApiError } from '@/api/client'
import type { ClassContext, ClassContextFile } from '@/api/types'

/**
 * The address of a class context file, so a link to one can be bookmarked and shared.
 *
 * A query parameter on the Rules tab rather than a route of its own, for the same reason
 * `srdHref` is: the screen already owns `?spell=`, `?doc=` and `?section=`, and a second
 * route entry for one screen is two ways to reach one page - which is how the two drift.
 */
export function classContextHref(path: string): string {
  return `/rules?context=${encodeURIComponent(path)}`
}

/**
 * The class context file a repo-relative path names, or null when it is not one.
 *
 * The mirror of `ruleInPath`, and it exists for the same reason: every place this app
 * prints provenance prints a path, and only some of them are documents. A path that is not
 * a class context file stays plain text rather than becoming a link that cannot open,
 * because a link that fails is worse than no link - it looks like the file is missing
 * rather than like the path is not a document.
 *
 * The pattern is anchored to `context/classes/` and to a `.md` suffix, so a traversal
 * (`context/classes/../../AGENTS.md`) does not match. The backend refuses one anyway; this
 * is the front end declining to offer it.
 */
export function classContextInPath(path: string | null | undefined): string | null {
  if (!path) return null
  const trimmed = path.trim()
  return /^context\/classes\/[A-Za-z0-9_/-]+\.md$/.test(trimmed) ? trimmed : null
}

/**
 * Every class context file, loaded once.
 *
 * One request for the whole list: it carries no text, so it is small, and asking per file
 * would show the list filling in. A failure is reported rather than retried - the files are
 * on disk, so a failure here means the backend is not running, which no amount of retrying
 * fixes.
 */
export function useClassContextFiles() {
  const [files, setFiles] = useState<ClassContextFile[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .classContextFiles()
      .then((found) => {
        if (!cancelled) setFiles(found)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { files, error, loading: files === null && error === null }
}

/**
 * One class context file's text, fetched on demand.
 *
 * The result carries the key it was fetched for and the caller's value is taken from it
 * only while that still matches - the same shape as `useSrdSection`, and for the same
 * reason: it clears the card the moment the selection changes without a setState in the
 * effect body, which would cascade a second render on every navigation.
 */
export function useClassContext(path: string | null) {
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    if (!path) return
    let cancelled = false
    api
      .classContext(path)
      .then((document) => {
        if (!cancelled) setResult({ key: path, kind: 'ok', document })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setResult({
          key: path,
          kind: 'error',
          message: e instanceof ApiError ? e.message : String(e),
        })
      })
    return () => {
      cancelled = true
    }
  }, [path])

  const current = result?.key === path ? result : null
  return {
    document: current?.kind === 'ok' ? current.document : null,
    error: current?.kind === 'error' ? current.message : null,
    loading: path !== null && current === null,
  }
}

type Result =
  | { key: string; kind: 'ok'; document: ClassContext }
  | { key: string; kind: 'error'; message: string }
