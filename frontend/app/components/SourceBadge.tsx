import { BookOpen, ScrollText, Sparkles, Wand2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

/**
 * Says where an answer came from.
 *
 * This is the most important piece of chrome in the app. A sheet answer is read
 * verbatim from the character file and cannot be wrong; a model answer is generated and
 * can. A rules answer is quoted from the 2024 SRD, and a rules-inferred answer is
 * *interpreted* from related SRD text when no heading names the question. Showing one as
 * another would let a plausible guess look like a recorded fact, so the distinction is
 * always visible — and an interpretation is deliberately not given the quotation's badge.
 */
export function SourceBadge({
  source,
  field,
}: {
  source: 'sheet' | 'model' | 'rules' | 'rules-inferred'
  field?: string | null
}) {
  if (source === 'sheet') {
    return (
      <Badge tone="verdant">
        <ScrollText className="h-3 w-3" />
        From your sheet{field ? `: ${field}` : ''}
      </Badge>
    )
  }
  if (source === 'rules') {
    return (
      <Badge tone="radiant">
        <BookOpen className="h-3 w-3" />
        2024 SRD
      </Badge>
    )
  }
  if (source === 'rules-inferred') {
    // Deliberately not the radiant tone the quoted badge uses. The text says
    // "interpreted"; the colour says it too, so the two cannot be confused at a glance.
    return (
      <Badge tone="muted">
        <Wand2 className="h-3 w-3" />
        2024 SRD — interpreted
      </Badge>
    )
  }
  return (
    <Badge tone="arcane">
      <Sparkles className="h-3 w-3" />
      From the model
    </Badge>
  )
}
