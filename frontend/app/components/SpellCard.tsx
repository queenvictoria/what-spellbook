import type { Spell } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { SourceBadge } from '@/components/SourceBadge'
import { SpellStatsStrip } from '@/components/SpellStats'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { withoutStatLines } from '@/lib/spellText'

/**
 * Saying where a spell's text came from.
 *
 * Three sources answer a spell lookup and they are not equally authoritative: the SRD is
 * the 2024 rules, the corpus is a transcription of the published spell, and a class
 * context file describes something that is not a spell at all. Showing one as another
 * would let a transcription look like a rule.
 */
function SpellSource({ source }: { source: string }) {
  if (source === 'vendored-srd-5.2.1') return <SourceBadge source="rules" />
  if (source === 'class-context') return <Badge tone="muted">Eldritch Invocation</Badge>
  return <Badge tone="muted">From the spell corpus</Badge>
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
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-sm">{spell.name}</CardTitle>
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
        <p className="border-t border-void-800 pt-2 font-mono text-xs text-parchment/40">
          {spell.url}
        </p>
      </CardContent>
    </Card>
  )
}
