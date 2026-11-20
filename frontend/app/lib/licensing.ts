/**
 * The third-party attributions this app owes, loaded once.
 *
 * Kept apart from the components so this module exports only a hook, which is what lets
 * React Fast Refresh reload the tree without discarding the page.
 */
import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import type { LicenceSource } from '@/api/types'

/**
 * Every third-party source and its attribution.
 *
 * A failure is reported rather than retried: the list is static text served by the backend,
 * so a failure here means the API is not running, which no amount of retrying fixes. The
 * caller renders nothing for an error — a licensing notice that cannot be fetched is not a
 * reason to block the app, and the long-form records are still in `context/*.PROVENANCE.md`.
 */
export function useLicensing() {
  const [sources, setSources] = useState<LicenceSource[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let cancelled = false
    api
      .licensing()
      .then((found) => {
        if (!cancelled) setSources(found)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { sources, error, loading: sources === null && error === null }
}

/**
 * The sources whose content is actually installed.
 *
 * The list an obligation applies to. The full list is what a licensing screen shows, because
 * it can also say "not installed" — which is a different statement from omitting the row.
 */
export function presentSources(sources: LicenceSource[] | null): LicenceSource[] {
  return (sources ?? []).filter((source) => source.present)
}
