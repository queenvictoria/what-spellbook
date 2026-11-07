import type { ClassContext } from "@/api/types"
import { Markdown } from "@/components/Markdown"
import { RulePathLink } from "@/components/RulePathLink"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * The file's own text without its opening `#` heading.
 *
 * The card title already shows that heading, so rendering it again would state the name
 * twice - and the second copy would be a link to the page the reader is already on. The
 * heading is dropped rather than the whole first line, because a file whose title is
 * followed immediately by prose has no blank line to split on.
 */
function withoutTitle(text: string): string {
  return text.replace(/^#\s+.*(?:\n|$)/, "").replace(/^\s+/, "")
}

/**
 * One of our own class context files, quoted.
 *
 * The same shape as `SrdCard` on purpose - both are read verbatim from a file, and the two
 * should look like the same kind of answer. The badge is deliberately **not** the SRD's
 * quotation badge: these files are our own summary of a class, written to be read by a
 * model, and they are not the rulebook. Showing one as the other would let a summary look
 * like a rule, which is the one confusion `SourceBadge` exists to prevent.
 *
 * There is no breadcrumb and no heading tree, because there is nothing to browse: these
 * files are a handful of `##` sections each, and the file *is* the unit a reader wants -
 * "show me the Warlock rules" rather than "show me the third heading of the Warlock rules".
 *
 * Linking stays on, unlike `SpellCard`. The spells these files name - Sacred Flame, Guiding
 * Bolt - are real spells a reader wants to look up, and the sibling files they cross-
 * reference by path are the commonest next move. Only the file's own title is suppressed,
 * and that is done by dropping the heading rather than by turning the linker off.
 */
export function ClassContextCard({
  document,
  className,
}: {
  document: ClassContext
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="gap-2">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">{document.title}</CardTitle>
          <Badge tone="muted">Class context</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Markdown text={withoutTitle(document.text)} className="prose-spell" />
        <p className="border-t border-void-800 pt-2">
          <RulePathLink path={document.path} />
        </p>
      </CardContent>
    </Card>
  )
}
