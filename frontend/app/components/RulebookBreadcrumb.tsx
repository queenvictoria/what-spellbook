import { ChevronRight } from "lucide-react"

import type { IonasCrumb, IonasSection } from "@/api/types"
import { cn } from "@/lib/utils"

/**
 * Where a rule sits in the optional rulebook, as a chain of labels.
 *
 * The same question `SrdBreadcrumb` answers, and the answer matters more here: a rule arrived
 * at from a search hit is a bare name. "Agonizing Blast" does not say it is a Warlock
 * invocation, and nothing in its own file does either - the link is in a third file that
 * names the router. "Darkvision" is worse, being a trait of ten species at once.
 *
 * **Every crumb is text, never a link.** The source's hierarchy is made of files and folders,
 * and one section is emitted per rule, so a crumb names a place that has no page of its own.
 * Offering a link to "Warlock" would promise a Warlock page and deliver something else that
 * happens to be called Warlock. The component therefore takes no callback at all - there is
 * nothing to open.
 *
 * It stays a separate component from `SrdBreadcrumb` rather than an option on it. The SRD's
 * trail is headings with slugs, and its crumbs *are* links; sharing one component would mean
 * a prop whose only job is to turn half the behaviour off.
 */
export function RulebookBreadcrumb({
  section,
  className,
}: {
  section: IonasSection
  className?: string
}) {
  const ancestors: IonasCrumb[] = section.ancestors ?? []
  if (ancestors.length === 0) return null

  return (
    <nav aria-label="Breadcrumb" className={cn("min-w-0", className)}>
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs">
        {ancestors.map((crumb) => (
          <li key={crumb.level} className="flex min-w-0 items-center gap-1">
            <span className="block truncate text-parchment/55">{crumb.text}</span>
            <ChevronRight className="h-3 w-3 shrink-0 text-parchment/25" />
          </li>
        ))}
        <li className="min-w-0">
          {/* The current page: not a link, because a link to where you already are is a
              control that does nothing. `aria-current` is what says so to a screen reader. */}
          <span aria-current="page" className="block truncate font-medium text-parchment/80">
            {section.name}
          </span>
        </li>
      </ol>
    </nav>
  )
}