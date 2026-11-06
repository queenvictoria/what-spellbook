import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerTitle } from '@/components/ui/drawer'
import { Input } from '@/components/ui/input'
import { Markdown } from '@/components/Markdown'
import { SourceBadge } from '@/components/SourceBadge'
import { api } from '@/api/client'
import type { Answer } from '@/api/types'
import { RulesContext, useRulesContext } from '@/lib/rulesContext'

/**
 * The contextual menu: select prose from a book, click the button, read the explanation.
 *
 * The selection lives here rather than beside the button, because the button is per-book
 * and the panel is per-book too, but the *text* has to survive the selection being cleared
 * before the request is made - clicking the button collapses the selection, so reading the
 * selection at click time would send an empty string every time.
 */
export function RulesContextDrawerProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [selectedText, setSelectedText] = useState('')
  const [loading, setLoading] = useState(false)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)

  const ask = useCallback(async (text?: string, context?: string) => {
    const question = (text ?? '').trim()
    if (!question) return

    setSelectedText(question)
    setOpen(true)
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      setAnswer(await api.rulesContextual(question, context || undefined))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach the rules lookup.')
    } finally {
      setLoading(false)
    }
  }, [])

  return (
    <RulesContext.Provider
      value={{ open, setOpen, selectedText, setSelectedText, ask, loading, answer, error }}
    >
      {children}
      <RulesContextDrawer />
    </RulesContext.Provider>
  )
}


function RulesContextDrawer() {
  const { open, setOpen, selectedText, setSelectedText, ask, loading, answer, error } =
    useRulesContext()

  return (
    <Drawer open={open} onOpenChange={setOpen} swipeDirection="right">
      <DrawerContent>
        <DrawerTitle className="sr-only">Rules Context</DrawerTitle>
        <DrawerDescription className="sr-only">
          An explanation of the selected text in the context of D&D 5.5e rules.
        </DrawerDescription>

        <div className="border-b border-void-800 p-4">
          <div className="flex gap-2">
            <Input
              placeholder="Text to explain, e.g. 2 beams"
              value={selectedText}
              onChange={(e) => setSelectedText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') ask(selectedText)
              }}
              className="flex-1"
            />
            <button
              onClick={() => ask(selectedText)}
              disabled={loading || !selectedText.trim()}
              className="rounded-md bg-parchment px-4 py-2 text-void-900 transition-colors hover:bg-parchment/90 disabled:opacity-50"
            >
              {loading ? '…' : 'Ask'}
            </button>
          </div>
          {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {loading && <p className="text-center text-parchment/60">Consulting the 2024 SRD…</p>}
          {!loading && answer && (
            <div className="space-y-2">
              {/* The provenance badge is the point of this panel: a `rules` answer is
                  quoted from the SRD and a `rules-inferred` one is the model's reading of
                  related text. Showing the second as the first is the failure the badge
                  exists to prevent. */}
              <SourceBadge source={answer.source} field={answer.field_name} />
              <Markdown text={answer.answer} className="prose-spell" />
              {answer.citations.length > 0 && (
                <p className="text-xs text-parchment/40">
                  {answer.from_cache ? 'Cached · ' : ''}
                  {answer.citations.join(', ')}
                </p>
              )}
            </div>
          )}
          {/* Only when nothing has been asked yet. Once an answer is on screen the entry
              hint is gone, because this panel renders the search box but not the spelling
              of every request the backend accepts (`/api/rules/contextual` is a GET, not a
              POST) - and a hint that overstates what a control does is worse than none. */}
          {!loading && !answer && (
            <p className="text-center text-parchment/60">
              Select text in a book and click the button to get an explanation.
            </p>
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
