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
  // `dd` is in the list because the character sheet is a selection surface too, and its
  // values are definition-list entries. Without it a selection inside a bolded run would
  // fall back to the `<strong>` and the context would be the two words that were bolded
  // rather than the value they sit in.
  const block = element?.closest('p, li, h1, h2, h3, h4, td, dd') ?? element
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
 * A selection is published when the gesture that made it *ends*, not while it is being made.
 * A drag fires `selectionchange` for every character it crosses, so a pause in the middle of
 * one is indistinguishable from having finished - which is how the drawer came to open on
 * half a phrase while the reader was still choosing the other half.
 *
 * `settled` says which of the two happened. A selection published by a mouseup is finished
 * by definition and can be acted on at once; one published by `selectionchange` outside a
 * drag has no gesture to wait for and still needs a settle timer. Without the distinction
 * the mouseup would merely move the wait rather than end it, and the reader would release
 * the button and then sit through another second of nothing.
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
  // Whether the selection last published was finished by a gesture, and so needs no settle.
  const [settled, setSettled] = useState(false)

  useEffect(() => {
    const element = ref.current
    if (!element) return

    // The selection as it stands right now, or null when there is nothing to ask about - an
    // empty range, or one outside the prose this hook watches (a selection in the drawer's
    // own input, say).
    const read = () => {
      const selection = window.getSelection()
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null
      const range = selection.getRangeAt(0)
      const text = range.toString().trim()
      if (!text || !element.contains(range.commonAncestorContainer)) return null
      return { text, context: surroundingText(range), documents: mentionsOf(text) }
    }

    // The text last published by this effect. A browser can re-report the *same* selection
    // after the mouse has come up, and treating that as new work would demote a finished
    // selection back to "wait for the timer" - reinstating, at the last moment, exactly the
    // delay the gesture exists to remove. Measured live: two `selectionchange` events landed
    // 35ms after the `pointerup` for the selection the pointerup had already published.
    let lastText = ''

    const publish = (found: ReturnType<typeof read>, fromGesture: boolean) => {
      const text = found?.text ?? ''
      setSelectedText(text)
      setContext(found?.context ?? '')
      setDocuments(found?.documents ?? [])
      if (fromGesture) setSettled(found !== null)
      else if (text !== lastText) setSettled(false)
      lastText = text
    }

    // A drag is in progress: `selectionchange` is firing for every character it crosses, and
    // none of those is a selection the reader has finished making.
    let dragging = false

    const handleSelectionChange = () => {
      if (dragging) return
      publish(read(), false)
    }

    // The gesture ended, so whatever is selected now is what was chosen - and it is chosen
    // already, which is why this publishes as settled. This is the only place a drag's
    // selection is published, which is what makes the wait unnecessary: the mouse coming up
    // *is* the signal that the reader has stopped choosing.
    const handlePointerUp = () => {
      dragging = false
      publish(read(), true)
    }

    // A drag that starts outside the prose and ends inside it - or the reverse - still ends
    // with a mouseup, and the selection it left is the reader's. Tracked from the document
    // rather than the element because a drag routinely leaves the element it began in.
    const handlePointerDown = () => {
      dragging = true
    }

    document.addEventListener('selectionchange', handleSelectionChange)
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('pointerup', handlePointerUp)
    return () => {
      document.removeEventListener('selectionchange', handleSelectionChange)
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('pointerup', handlePointerUp)
    }
    // `mentionsOf` must be stable or the listener is torn down and re-added on every
    // render. It is the caller's, because only the caller knows what a mention is.
  }, [ref, mentionsOf])

  /** Drop the selection, so the button goes away once it has been acted on. */
  const clearSelection = useCallback(() => {
    window.getSelection()?.removeAllRanges()
    setSelectedText('')
    setContext('')
    setDocuments([])
    setSettled(false)
  }, [])

  return { selectedText, context, documents, settled, clearSelection }
}
