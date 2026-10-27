import { useState } from 'react'
import type { ReactNode } from 'react'
import React from 'react'
import { X } from 'lucide-react'

import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerTitle } from '@/components/ui/drawer'
import { Input } from '@/components/ui/input'
import { api } from '@/api/client'
import { SourceBadge } from '@/components/SourceBadge'

/**
 * A pull-out panel for contextual rules explanations based on selected text.
 *
 * When a user selects text from the book prose (e.g., "2 beams" from Eldritch Blast),
 * this drawer shows an explanation of what that means in the context of D&D 5.5e rules.
 *
 * The panel is Base UI's Drawer, which is what shadcn's current drawer wraps, so Escape,
 * the focus trap and the `aria-*` wiring come from the primitive rather than being redone
 * here.
 */
export function RulesContextDrawerProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [selectedText, setSelectedText] = useState('')
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleAsk = async () => {
    if (!selectedText.trim()) return
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      const result = await api.rulesContextual(selectedText)
      setAnswer(result.answer)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get answer')
    } finally {
      setLoading(false)
    }
  }

  return (
    <RulesContextContext.Provider value={{ open, setOpen, selectedText, setSelectedText, handleAsk, loading, answer, error }}>
      {children}
      <RulesContextDrawer />
    </RulesContextContext.Provider>
  )
}

const RulesContextContext = React.createContext<{
  open: boolean
  setOpen: (open: boolean) => void
  selectedText: string
  setSelectedText: (text: string) => void
  handleAsk: () => void
  loading: boolean
  answer: string | null
  error: string | null
} | null>(null)

function RulesContextDrawer() {
  const context = React.useContext(RulesContextContext)
  if (!context) throw new Error('RulesContextDrawer must be used within RulesContextDrawerProvider')

  const { open, setOpen, selectedText, setSelectedText, handleAsk, loading, answer, error } = context

  return (
    <Drawer open={open} onOpenChange={setOpen} swipeDirection="right">
      <DrawerContent>
        <DrawerTitle className="sr-only">Rules Context</DrawerTitle>
        <DrawerDescription className="sr-only">
          An explanation of selected text in the context of D&D 5.5e rules.
        </DrawerDescription>

        <div className="border-b border-void-800 p-4">
          <div className="flex gap-2">
            <Input
              placeholder="Selected text..."
              value={selectedText}
              onChange={(e) => setSelectedText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAsk()
              }}
              className="flex-1"
            />
            <button
              onClick={handleAsk}
              disabled={loading || !selectedText.trim()}
              className="rounded-md bg-parchment px-4 py-2 text-void-900 transition-colors hover:bg-parchment/90 disabled:opacity-50"
            >
              {loading ? '...' : 'Ask'}
            </button>
          </div>
          {error && (
            <p className="mt-2 text-sm text-red-400">{error}</p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {answer ? (
            <div className="prose prose-invert max-w-none">
              <SourceBadge source="rules" />
              <div className="whitespace-pre-wrap">{answer}</div>
            </div>
          ) : (
            <p className="text-center text-parchment/60">Select text and click Ask to get an explanation</p>
          )}
        </div>

        <div className="border-t border-void-800 p-3">
          <DrawerClose
            onClick={() => setOpen(false)}
            className="flex w-full items-center justify-center gap-2 rounded-md py-2 text-sm text-parchment/60 transition-colors hover:bg-void-800 hover:text-parchment"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
            Close
          </DrawerClose>
        </div>
      </DrawerContent>
    </Drawer>
  )
}