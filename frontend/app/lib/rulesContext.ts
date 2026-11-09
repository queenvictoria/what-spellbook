/**
 * The contextual menu's shared state, kept apart from the provider component.
 *
 * Kept in `lib/` and exporting only the context and its hook for the same reason
 * `spellNames.ts` is: a module that exports a hook alongside a component stops React Fast
 * Refresh from reloading the component without discarding the page.
 */
import { createContext, useContext } from 'react'

import type { Answer, SearchResult } from '@/api/types'

export interface RulesContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  selectedText: string
  setSelectedText: (text: string) => void
  /**
   * Ask about `text`. `documents` are the rules the question carries; pass them when the
   * selection's mentions have already been resolved, so the drawer does not resolve them a
   * second, slightly different way.
   */
  ask: (text: string, context?: string, documents?: string[]) => void
  /**
   * Ask about the current selection, carrying the prose it came from.
   *
   * A separate entry point from `ask` because the sentence is not something the drawer has:
   * it was read from the DOM when the highlight settled, and it is what lets the backend read
   * "2 beams" as the *Eldritch Blast* beams. It reaches the prompt only - the selection is
   * what was asked about, so the sentence never steers retrieval.
   */
  askSelection: () => void
  /**
   * Open the drawer on `text` and search the vector index for it.
   *
   * This is what a selection does, and it is a *different* act from `ask`: the index search
   * costs no model call, so it can run the moment the highlight settles, while the answer has
   * to wait for a click. The two readings land in one panel - the search underneath, the
   * answer pushed in above it - so the reader can see what the words retrieved before
   * deciding to spend a question on them.
   */
  explore: (text: string, context?: string, documents?: string[]) => void
  loading: boolean
  answer: Answer | null
  error: unknown
  /** The vector search the selection produced. Independent of the answer's own state. */
  search: SearchResult | null
  searching: boolean
  searchError: unknown
  /** The documents the next question will carry, by name. */
  attachments: string[]
  removeAttachment: (name: string) => void
}

export const RulesContext = createContext<RulesContextValue | null>(null)

export function useRulesContext(): RulesContextValue {
  const context = useContext(RulesContext)
  if (!context) {
    throw new Error('useRulesContext must be used within RulesContextDrawerProvider')
  }
  return context
}
