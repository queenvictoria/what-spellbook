import { useCallback, useEffect, useRef } from "react"
import type { RefObject } from "react"

import { useRulesContext } from "@/lib/rulesContext"
import { extractSpellNames, useSpellNames } from "@/lib/spellNames"
import { SELECTION_SETTLE_MS } from "@/lib/timing"
import { useSelection } from "@/lib/useSelection"

/**
 * Opens the contextual drawer on whatever prose is selected inside `target`.
 *
 * `target` is the element holding the prose, so the selection can be scoped to it: without a
 * real element the hook has nothing to watch and no selection is ever reported.
 *
 * This replaced a button that appeared on selection and had to be clicked. The button was
 * the only way in, so a reader who had selected the wrong words found out only after paying
 * for an answer; and because the selection is what the action acts on, the click itself was
 * the gesture that cancelled it - the text had to be read at click time and handed over
 * before the highlight was dropped. Opening on the selection removes that whole class of
 * problem: what is searched is what is highlighted, and the answer waits for an explicit
 * Ask.
 *
 * The wait exists because a drag fires `selectionchange` on every intermediate character.
 * Searching each one would issue a request per letter of the drag and leave several
 * responses racing to fill one panel, so the highlight must hold still first.
 */
export function SelectionWatcher({ target }: { target: RefObject<HTMLElement | null> }) {
  const names = useSpellNames()
  // The renderer's own mention rule, so what is attached is exactly what is linked. Stable
  // across renders because `useSelection` takes it as an effect dependency.
  const mentionsOf = useCallback(
    (text: string) => extractSpellNames(text, names),
    [names],
  )
  const { selectedText, context, documents, clearSelection } = useSelection(
    target,
    mentionsOf,
  )
  const { explore } = useRulesContext()

  // The selection the drawer was last opened for, so the same words are not searched twice.
  // A ref rather than state: it records what happened, and the render does not depend on it.
  const openedFor = useRef("")
  // Everything the timer reads is reached through a ref, so the effect can depend on the
  // selection *text* alone.
  //
  // This matters more than it looks. `documents` is a fresh array on every
  // `selectionchange`, and `explore` is rebuilt whenever the provider re-renders - which is
  // continuously while an answer streams in. Either one in the dependency array would tear
  // the timer down and start it again on events that did not change the selection, and the
  // search would be postponed for as long as the churn continued.
  const latest = useRef({ context, documents, explore })
  useEffect(() => {
    latest.current = { context, documents, explore }
  })

  useEffect(() => {
    if (!selectedText) {
      // The selection was dropped - by `clearSelection` below, or by the reader clicking
      // away. Clearing the guard here is what lets the *same* phrase be selected a second
      // time: the drawer would otherwise refuse to re-open on words it had already searched,
      // and the panel would stay shut with no way to bring it back.
      openedFor.current = ""
      return
    }
    if (selectedText === openedFor.current) return

    const timer = setTimeout(() => {
      // Re-checked inside the timer: the selection may have moved on during the wait, and
      // the point of the wait is that only the settled value is searched.
      if (selectedText === openedFor.current) return
      openedFor.current = selectedText
      const { context, documents, explore } = latest.current
      explore(selectedText, context, documents)
      // The highlight is dropped once the drawer holds the words. Leaving it would keep the
      // prose behind the panel selected, so a click that closed the drawer would land on a
      // stale highlight - and clearing it here, in the same tick the words are handed over,
      // is what lets the same phrase be selected again later and open the drawer afresh.
      clearSelection()
    }, SELECTION_SETTLE_MS)
    return () => clearTimeout(timer)
  }, [selectedText, clearSelection])

  return null
}
