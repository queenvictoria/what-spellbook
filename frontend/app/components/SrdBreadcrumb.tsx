import { ChevronRight } from "lucide-react"

import type { SrdSection } from "@/api/types"
import { srdHref } from "@/lib/srd"
import { useOpenRule } from "@/lib/ruleDrawer"
import { cn } from "@/lib/utils"

/**
 * Where a rule sits in the rulebook, as a chain of links.
 *
 * A rule is reached by descending through its parents, and the heading alone does not say
 * where it lives: "Prone [Condition]" is under *Rules Definitions* in the *Rules Glossary*,
 * and a reader who arrived from a citation has no way to know that. The trail is the answer
 * to "where am I", and each crumb is a link to the parent rule, which is the other thing a
 * reader wants from it - the section that defines the terms this one uses.
 *
 * The trail comes from the server rather than being derived here. The client holds the table
 * of contents, so it *could* walk it, but the server already knows the path and a second
 * lookup for something already computed is a way for the two to disagree.
 *
 * The last crumb is the section itself, marked as the current page rather than linked to
 * itself. The document's root heading is the first crumb, so a top-level rule reads as
 * "Rules Glossary / Rules Glossary" - which is why the root is dropped when it is the only
 * ancestor and its text matches the document title.
 *
 * Each crumb carries the anchor of the heading it opens, so following one lands on the rule
 * the reader was reading rather than at the top of its parent. A parent's text runs to the
 * next heading at its own level, so it *contains* the child - "Warlock Class Features" holds
 * all ten of the Warlock's feature headings - and without the anchor the reader arrives at
 * the top of a long section and has to find their place again. The anchor is the child's
 * slug, which is the heading the parent's text will render with that id.
 */
export function SrdBreadcrumb({
  section,
  className,
}: {
  section: SrdSection
  className?: string
}) {
  const open = useOpenRule()

  // The root heading of every vendored file repeats the document's title, so a section
  // directly under it would otherwise show the same name twice in a row.
  const ancestors = section.ancestors.filter(
    (crumb, index) =>
      !(index === 0 && crumb.text === section.title && section.ancestors.length === 1),
  )

  return (
    <nav aria-label="Breadcrumb" className={cn("min-w-0", className)}>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs">
        {ancestors.map((crumb, index) => {
          // The heading this crumb opens: the next one down the trail, or the section itself
          // for the last ancestor. `ancestors` is the trail minus the section, so the child
          // of crumb *i* is crumb *i + 1*.
          const child = ancestors[index + 1] ?? section
          return (
            <li key={crumb.slug} className="flex min-w-0 items-center gap-1">
              <Crumb
                href={srdHref(section.document, crumb.slug, child.slug)}
                onClick={() =>
                  open({
                    kind: "srd",
                    document: section.document,
                    slug: crumb.slug,
                    anchor: child.slug,
                  })
                }
              >
                {crumb.text}
              </Crumb>
              <ChevronRight className="h-3 w-3 shrink-0 text-parchment/25" />
            </li>
          )
        })}
        <li className="min-w-0">
          {/* The current page: not a link, because a link to where you already are is a
              control that does nothing. `aria-current` is what says so to a screen reader. */}
          <span
            aria-current="page"
            className="block truncate font-medium text-parchment/80"
          >
            {section.heading}
          </span>
        </li>
      </ol>
    </nav>
  )
}

/**
 * One ancestor, as a link that opens it in the drawer.
 *
 * A real `<a href>` carrying the section in the query string, so a parent rule can be
 * bookmarked and opened in a new tab. Only a plain left click is intercepted - a modified
 * click is the reader asking the browser for something else, and swallowing it would break
 * "open in new tab" on the one control where it is most useful.
 */
function Crumb({
  href,
  onClick,
  children,
}: {
  href: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <a
      href={href}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
        if (event.button !== 0) return
        event.preventDefault()
        onClick()
      }}
      className="block truncate rounded px-1 py-0.5 text-parchment/55 transition-colors hover:bg-void-800 hover:text-parchment"
    >
      {children}
    </a>
  )
}