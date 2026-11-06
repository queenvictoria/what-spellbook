import { useCallback } from 'react'
import type { RefObject } from 'react'
import { MessageSquare } from 'lucide-react'

import { useRulesContext } from '@/lib/rulesContext'
import { extractSpellNames, useSpellNames } from '@/lib/spellNames'
import { useSelection } from '@/lib/useSelection'

/**
 * The "ask about this" button, shown once prose in `target` has been selected.
 *
 * `target` is the element holding the prose, so the selection can be scoped to it: without
 * a real element the hook has nothing to watch and the button can never appear at all.
 *
 * The selected text is read at click time rather than from the hook's own state, because
 * the selection is what the button acts on and the hook's copy is updated by an event that
 * the click itself will cancel. The surrounding prose goes along with it, so the backend
 * can read "2 beams" as the *Eldritch Blast* beams.
 */
export function RulesContextButton({ target }: { target: RefObject<HTMLElement | null> }) {
  const names = useSpellNames()
  // The renderer's own mention rule, so what is attached is exactly what is linked. Stable
  // across renders because `useSelection` takes it as an effect dependency.
  const mentionsOf = useCallback(
    (text: string) => extractSpellNames(text, names),
    [names],
  )
  const { selectedText, context, documents, clearSelection } = useSelection(target, mentionsOf)
  const { ask } = useRulesContext()

  if (!selectedText) return null

  const preview = selectedText.length > 50 ? `${selectedText.slice(0, 50)}…` : selectedText

  const handleClick = () => {
    // Ask first, then drop the selection: the drawer holds the text from here, and the
    // highlight would otherwise sit over the prose behind the panel.
    //
    // `documents` is passed explicitly because *this* component is what sits on the prose
    // and can see which words are links. Handing the names over rather than letting the
    // drawer re-derive them from the text keeps "what the reader was shown as a link" and
    // "what the model was given" the same list.
    ask(selectedText, context, documents)
    clearSelection()
  }

  return (
    <button
      onClick={handleClick}
      className="flex w-full items-center justify-center gap-2 rounded-md border border-arcane-500/30 bg-arcane-500/10 px-4 py-2 text-sm text-arcane-300 transition-colors hover:bg-arcane-500/20"
      aria-label={`Ask about "${preview}"`}
    >
      <MessageSquare className="h-4 w-4" />
      <span>Ask about “{preview}”</span>
    </button>
  )
}
