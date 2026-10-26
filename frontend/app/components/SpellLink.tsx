import { spellInHref, shouldDeferToBrowser, useOpenSpell } from '@/lib/spellDrawer'
import { cn } from '@/lib/utils'

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
 * Shared by the markdown renderer and the picks list, because both name spells and both
 * should behave the same. A second implementation would eventually answer to a plain click
 * differently, which is the kind of inconsistency that reads as a bug.
 */
export function SpellLink({ name, className }: { name: string; className?: string }) {
  const openSpell = useOpenSpell()
  const href = `/rules?spell=${encodeURIComponent(name)}`

  return (
    <a
      href={href}
      onClick={(e) => {
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
        'text-arcane-300 underline decoration-dotted underline-offset-2 hover:text-arcane-200',
        className,
      )}
      title={`Look up ${name} in the rules`}
    >
      {name}
    </a>
  )
}
