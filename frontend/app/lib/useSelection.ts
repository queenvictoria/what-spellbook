import { useCallback, useEffect, useState } from 'react'

/** Enough surrounding prose to disambiguate a fragment, without pasting the paragraph. */
const CONTEXT_LIMIT = 400

/**
 * The block of prose a selection sits in, so the backend can read a fragment in context.
 *
 * "2 beams" means nothing on its own and everything beside "Eldritch Blast". The nearest
 * block element is where the Markdown renderer puts a paragraph or a list item, so its
 * text is the surrounding prose - and it is taken whole rather than split into sentences,
 * because sentence splitting on model-authored prose finds the wrong full stop often
 * enough to be worse than the extra words.
 */
function surroundingText(range: Range): string {
  const node = range.startContainer
  const element = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement
  const block = element?.closest('p, li, h1, h2, h3, h4, td') ?? element
  const text = block?.textContent?.replace(/\s+/g, ' ').trim() ?? ''
  return text.length > CONTEXT_LIMIT ? text.slice(0, CONTEXT_LIMIT).trim() : text
}

/**
 * Tracks the text selected inside `ref`, the prose around it, and the spells it names.
 *
 * The element is read from the ref *inside* the listener, never captured when the effect
 * runs. A ref is populated during the commit that renders the element, so a hook that
 * snapshots `ref.current` in its effect body sees `null` on the first pass and, because
 * the ref object itself never changes, never gets a second chance - which is how this hook
 * silently reported "nothing selected" for every selection ever made.
 *
 * The caller clears the selection with `clearSelection` once it has taken the words, so the
 * empty update this produces is the normal end of a selection rather than an error path.
 *
 * `mentionsOf` is supplied as a function so the caller can decide what a mention is (the
 * prose renderer already knows, from the corpus's spell list) without this hook taking a
 * dependency on a context it does not otherwise need.
 */
export function useSelection(
  ref: React.RefObject<HTMLElement | null>,
  mentionsOf: (text: string) => string[],
) {
  const [selectedText, setSelectedText] = useState('')
  const [context, setContext] = useState('')
  const [documents, setDocuments] = useState<string[]>([])

  useEffect(() => {
    const handleSelectionChange = () => {
      const element = ref.current
      const selection = window.getSelection()

      // An empty range, or one outside the prose this hook watches - a selection in the
      // drawer's own input, say - means there is nothing to ask about.
      if (!element || !selection || selection.rangeCount === 0 || selection.isCollapsed) {
        setSelectedText('')
        setContext('')
        setDocuments([])
        return
      }

      const range = selection.getRangeAt(0)
      const text = range.toString().trim()
      if (!text || !element.contains(range.commonAncestorContainer)) {
        setSelectedText('')
        setContext('')
        setDocuments([])
        return
      }

      setSelectedText(text)
      setContext(surroundingText(range))
      setDocuments(mentionsOf(text))
    }

    document.addEventListener('selectionchange', handleSelectionChange)
    return () => document.removeEventListener('selectionchange', handleSelectionChange)
    // `mentionsOf` must be stable or the listener is torn down and re-added on every
    // render. It is the caller's, because only the caller knows what a mention is.
  }, [ref, mentionsOf])

  /** Drop the selection, so the button goes away once it has been acted on. */
  const clearSelection = useCallback(() => {
    window.getSelection()?.removeAllRanges()
    setSelectedText('')
    setContext('')
    setDocuments([])
  }, [])

  return { selectedText, context, documents, clearSelection }
}
