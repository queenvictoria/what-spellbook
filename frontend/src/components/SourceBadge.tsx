import { BookOpen, ScrollText, Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'

/**
 * Says where an answer came from.
 *
 * This is the most important piece of chrome in the app. A sheet answer is read
 * verbatim from the character file and cannot be wrong; a model answer is generated and
 * can. A rules answer is quoted from the 2024 SRD. Showing one as another would let a
 * plausible guess look like a recorded fact, so the distinction is always visible.
 */
export function SourceBadge({
  source,
  field,
}: {
  source: 'sheet' | 'model' | 'rules'
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
  return (
    <Badge tone="arcane">
      <Sparkles className="h-3 w-3" />
      From the model
    </Badge>
  )
}
