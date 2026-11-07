import { TrendingUp } from "lucide-react"

import type { Spell } from "@/api/types"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { RulePathLink } from "@/components/RulePathLink"
import { SpellStatsStrip } from "@/components/SpellStats"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { withoutStatLines } from "@/lib/spellText"

/**
 * Saying where a spell's text came from.
 *
 * Three sources answer a spell lookup and they are not equally authoritative: the SRD is
 * the 2024 rules, the corpus is a transcription of the published spell, and a class
 * context file describes something that is not a spell at all. Showing one as another
 * would let a transcription look like a rule.
 */
function SpellSource({ source }: { source: string }) {
  if (source === "vendored-srd-5.2.1") return <SourceBadge source="rules" />
  if (source === "class-context")
    return <Badge tone="muted">Eldritch Invocation</Badge>
  return <Badge tone="muted">From the spell corpus</Badge>
}

/**
 * What the spell does at *this* character's level.
 *
 * The spell's text states its scaling as a table - "two beams at level 5, three beams at
 * level 11" - and a reader at the table wants the row that applies to them. The backend
 * reads that row out of the spell's own words, so this is a rule rather than a summary;
 * the badge is what says it is about the loaded character rather than about the spell.
 *
 * Rendered beside the name rather than in the stat strip, because it is the one value on
 * the card that changes when the character levels up.
 */
function SpellScaling({ scaling }: { scaling: string }) {
  return (
    <Badge
      tone="arcane"
      title="At your character's level"
      // A two-part upgrade ("extra 1d8 thunder damage on hit; movement damage 2d8") is
      // longer than the badge's default single line, and `whitespace-nowrap` would push it
      // out of the card rather than onto a second line.
      className="whitespace-normal text-left"
    >
      <TrendingUp className="h-3 w-3 shrink-0" />
      {scaling}
    </Badge>
  )
}

/**
 * One spell, quoted from a vendored file.
 *
 * Shared by the Rules screen and the drawer so the two cannot drift - the drawer is the
 * same reading of the same text, and a second renderer would eventually disagree about
 * something like the stat lines. `linkSpells` is off because the text *is* the spell, so
 * its own name must not link back to itself.
 */
export function SpellCard({
  spell,
  className,
}: {
  spell: Spell
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader className="flex-row items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <CardTitle className="text-sm">{spell.name}</CardTitle>
          {spell.scaling && <SpellScaling scaling={spell.scaling} />}
        </div>
        <SpellSource source={spell.source} />
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Null for an invocation, which is quoted through this same card. It has no
            Casting Time, Range or Duration, and a strip of empty tiles would imply it
            does. */}
        {spell.stats && <SpellStatsStrip stats={spell.stats} />}
        <Markdown
          // The stat lines the strip just rendered are dropped here, so a value is not
          // shown twice - and the copy that is left would be the unexpanded one.
          text={withoutStatLines(spell.text, spell.stats)}
          className="prose-spell"
          linkSpells={false}
        />
        {/* A link when the text came from the vendored SRD, plain text when it came from
            the retrieval corpus - which is not a rulebook page and has no headings to
            browse. `RulePathLink` makes that distinction, so a corpus spell does not offer
            a link that cannot open. */}
        <p className="border-t border-void-800 pt-2">
          <RulePathLink path={spell.url} />
        </p>
      </CardContent>
    </Card>
  )
}
