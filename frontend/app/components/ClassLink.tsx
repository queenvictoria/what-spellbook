import { useRef } from "react"

import { classContextHref } from "@/lib/classContext"
import { useOpenRule } from "@/lib/ruleDrawer"
import { shouldDeferToBrowser } from "@/lib/spellDrawer"
import { cn } from "@/lib/utils"

/**
 * A class context mention, rendered as a link that opens the drawer.
 *
 * The same affordance `SpellLink` gives a spell, for the same reason: an answer that says
 * "the attached documents show Celestial Patron" is naming a document the reader can read,
 * and leaving it as dead text makes them go and find it by hand. The `href` is kept and
 * still points at the Rules tab, so Ctrl+click, middle-click and the status bar all keep
 * working; only a plain left click is intercepted.
 *
 * A click that ended a **drag** is left to the browser, exactly as `SpellLink` does it. The
 * case is the same one: a reader dragging a selection across a mention must not have the
 * page navigate out from under the highlight they just made.
 */
export function ClassLink({
  name,
  path,
  className,
}: {
  name: string
  path: string
  className?: string
}) {
  const open = useOpenRule()
  const href = classContextHref(path)
  // Where the pointer went down on this link, or null when it did not. A drag that ends on
  // the link has a different origin from the click, which is the whole of the test.
  const pressedAt = useRef<{ x: number; y: number } | null>(null)

  return (
    <a
      href={href}
      onMouseDown={(e) => {
        pressedAt.current = { x: e.clientX, y: e.clientY }
      }}
      onClick={(e) => {
        const pressed = pressedAt.current
        pressedAt.current = null
        // A few pixels of slop: a hand on a mouse is not perfectly still, and treating a
        // 1px shift as a drag would make the link feel broken.
        if (pressed && Math.hypot(e.clientX - pressed.x, e.clientY - pressed.y) > 4) {
          e.preventDefault()
          return
        }
        if (shouldDeferToBrowser(e)) return
        e.preventDefault()
        open({ kind: "class", document: path, slug: null })
      }}
      className={cn(
        "text-verdant-400 underline underline-offset-4 decoration-verdant-400/0 hover:decoration-verdant-400/60 transition-colors",
        className,
      )}
      title={`Read our ${name} rules`}
    >
      {name}
    </a>
  )
}
