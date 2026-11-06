/**
 * The contextual menu's shared state, kept apart from the provider component.
 *
 * Kept in `lib/` and exporting only the context and its hook for the same reason
 * `spellNames.ts` is: a module that exports a hook alongside a component stops React Fast
 * Refresh from reloading the component without discarding the page.
 */
import { createContext, useContext } from 'react'

import type { Answer } from '@/api/types'

export interface RulesContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  selectedText: string
  setSelectedText: (text: string) => void
  /** Ask about `text`, or about the current selection when called with none. */
  ask: (text?: string, context?: string) => void
  loading: boolean
  answer: Answer | null
  error: string | null
}

export const RulesContext = createContext<RulesContextValue | null>(null)

export function useRulesContext(): RulesContextValue {
  const context = useContext(RulesContext)
  if (!context) {
    throw new Error('useRulesContext must be used within RulesContextDrawerProvider')
  }
  return context
}
