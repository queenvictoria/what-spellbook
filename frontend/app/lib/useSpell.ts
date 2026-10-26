import { useEffect, useState } from 'react'

import { api, ApiError } from '@/api/client'
import type { Spell } from '@/api/types'

/**
 * Resolves a name to a spell, reporting which of the three outcomes happened.
 *
 * A hook rather than part of the card, so the card module exports only components - a
 * module exporting both cannot be hot-reloaded without discarding the page - and so a
 * caller can decide how to show "not found": a page has room for the explanation, a drawer
 * has a line.
 *
 * The invocation fallback is not a nicety. A book's link list holds spell names and
 * Eldritch Invocation names in the same sentence, and the list does not say which is which.
 * Trying the spell first and falling back only on a 404 keeps the front end from needing a
 * second list, and a real failure still surfaces rather than being read as "not an
 * invocation either".
 */
export function useSpell(name: string | null) {
  // The result carries the name it was fetched for, and the caller's value is taken from it
  // only while that still matches. That is what clears the card the moment the name
  // changes, without a setState in the effect body - which would cascade a second render on
  // every navigation.
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    if (!name) return
    let cancelled = false
    api
      .spell(name)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) return api.invocation(name)
        throw e
      })
      .then((spell) => {
        if (!cancelled) setResult({ name, kind: 'ok', spell })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (e instanceof ApiError && e.status === 404) {
          setResult({ name, kind: 'missing', message: e.message })
        } else {
          setResult({
            name,
            kind: 'error',
            message: e instanceof ApiError ? e.message : String(e),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [name])

  const current = result?.name === name ? result : null
  return {
    spell: current?.kind === 'ok' ? current.spell : null,
    missing: current?.kind === 'missing' ? current.message : null,
    error: current?.kind === 'error' ? current.message : null,
    loading: name !== null && current === null,
  }
}

type Result =
  | { name: string; kind: 'ok'; spell: Spell }
  | { name: string; kind: 'missing'; message: string }
  | { name: string; kind: 'error'; message: string }
