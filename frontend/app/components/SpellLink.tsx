import { useRef } from "react"

import {
  spellInHref,
  shouldDeferToBrowser,
  useOpenSpell,
} from "@/lib/spellDrawer"
import { cn } from "@/lib/utils"

/**
 * A spell mention, rendered as a link that opens the drawer.
 *
 * The `href` is kept and still points at the rules tab, so the browser's own affordances
 * keep working: Ctrl+click opens it in a new tab, middle-click too, and the status bar
 * shows where it goes. A plain left click is intercepted and opens the panel instead,
 * which is the point — a reader comparing spells should not lose the book they are reading
 * to follow one mention.
 *
 * A real `<a href>` rather than a router link, because the rules tab is a separate document
 * in this app's routing and the browser's own navigation is what keeps the back button
 * working.
 *
 * A click that ended a **drag** is left to the browser's default, which is to do nothing.
 * This is the case that makes selecting prose across a mention usable: the reader drags
 * from before "Thorn Whip" to after it, the mouse comes up on the link, and a browser
 * fires a click on it — which would navigate away, discarding the selection they just made
 * and were about to ask about. There is no way to tell that click apart from a real one
 * except by knowing the mouse moved, so the movement is tracked.
 *
 * Shared by the markdown renderer and the picks list, because both name spells and both
 * should behave the same. A second implementation would eventually answer to a plain click
 * differently, which is the kind of inconsistency that reads as a bug.
 */
export function SpellLink({
  name,
  className,
}: {
  name: string
  className?: string
}) {
  const openSpell = useOpenSpell()
  const href = `/rules?spell=${encodeURIComponent(name)}`
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
        if (
          pressed &&
          Math.hypot(e.clientX - pressed.x, e.clientY - pressed.y) > 4
        ) {
          e.preventDefault()
          return
        }
        // A modified click, a middle click, or a click another handler already claimed is
        // left to the browser — that is what keeps the href meaningful rather than
        // decorative.
        if (shouldDeferToBrowser(e)) return
        // Only a link this app can answer locally becomes a panel. Anything else is left
        // to navigate, so "local links" cannot silently come to mean "all links".
        if (!spellInHref(href)) return
        e.preventDefault()
        openSpell(name)
      }}
      className={cn(
        "text-arcane-300 underline underline-offset-4 decoration-arcane-300/0 hover:decoration-arcane-500/60 hover:text-arcane-500 transition-colors",
        className,
      )}
      title={`Look up ${name} in the rules`}
    >
      {name}
    </a>
  )
}
