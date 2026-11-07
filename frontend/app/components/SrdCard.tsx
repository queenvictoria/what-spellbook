import type { SrdSection } from "@/api/types"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { SrdBreadcrumb } from "@/components/SrdBreadcrumb"
import { SrdPathLink } from "@/components/SrdPathLink"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * One section of the vendored SRD, quoted.
 *
 * The same shape as `SpellCard` on purpose: a rule and a spell are both read verbatim from a
 * file, and the two cards should look like the same kind of answer. The badge is the
 * quotation badge, never the interpreted one - nothing here is generated, so nothing here
 * can be a paraphrase of a bonus.
 *
 * The heading is *not* repeated as a card title when the text already opens with it. The
 * backend includes the heading line so the fragment reads as a document, so the title is the
 * document's name and the section heading is the first line of the text.
 *
 * The breadcrumb sits above the title because it answers a question the title cannot: a rule
 * read from a citation arrives without its context, and "Prone [Condition]" does not say it
 * lives under *Rules Definitions* in the *Rules Glossary*.
 */
export function SrdCard({
  section,
  className,
}: {
  section: SrdSection
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="gap-2">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">{section.title}</CardTitle>
          <SourceBadge source="rules" />
        </div>
        <SrdBreadcrumb section={section} />
      </CardHeader>
      <CardContent className="space-y-3">
        <Markdown text={section.text} className="prose-spell" />
        <p className="border-t border-void-800 pt-2">
          <SrdPathLink
            path={`${section.path}${section.slug ? `#${section.slug}` : ""}`}
          />
        </p>
      </CardContent>
    </Card>
  )
}
