import type { IonasSection } from "@/api/types"
import { Markdown } from "@/components/Markdown"
import { RulebookBreadcrumb } from "@/components/RulebookBreadcrumb"
import { RulePathLink } from "@/components/RulePathLink"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * One rule from the optional rulebook, quoted.
 *
 * Shaped like `SrdCard`, because both are read verbatim from a file, and the two should look
 * like the same kind of answer. The badge is deliberately **not** the SRD's quotation badge:
 * this text is a scan of the 2024 books from a third-party source, not the SRD, so showing it
 * as the rulebook would let a transcription pass for the authority.
 *
 * Separate from `ClassContextCard` - which this used to reuse - because that card is for our
 * own one-page class summaries, where the file *is* the unit a reader wants. A rulebook rule
 * is one entry out of a thousand, and it arrives without its context: "Agonizing Blast" does
 * not say it is a Warlock invocation. That is what the breadcrumb is for, and it is also why
 * the card shows the rule's `name` as its title rather than the file it came from.
 *
 * The heading is *not* repeated in the body. The text opens with the rule's own `###`
 * heading so a fragment reads as a document, so rendering it again would state the name
 * twice - once in the title and once as a heading.
 */
function withoutHeading(text: string): string {
  return text.replace(/^#{1,6}\s+.*(?:\n|$)/, "").replace(/^\s+/, "")
}

export function RulebookCard({
  section,
  className,
}: {
  section: IonasSection
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="gap-2">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">{section.name}</CardTitle>
          <Badge tone="muted">Rulebook</Badge>
        </div>
        <RulebookBreadcrumb section={section} />
      </CardHeader>
      <CardContent className="space-y-3">
        <Markdown text={withoutHeading(section.text)} className="prose-spell" />
        <p className="border-t border-void-800 pt-2">
          {/* A rulebook JSON holds many rules, so the path names the file and not this
              entry. It stays plain text rather than becoming a link that cannot open. */}
          <RulePathLink path={section.path} />
        </p>
      </CardContent>
    </Card>
  )
}