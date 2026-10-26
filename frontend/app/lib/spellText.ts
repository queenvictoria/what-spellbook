/**
 * Preparing a spell's quoted text for display.
 *
 * Kept in `lib/` rather than beside the component that uses it for the same reason
 * `spellNames.ts` is: a module exporting a component and a plain function cannot be
 * hot-reloaded without discarding the page, and this is pure text handling anyway.
 */

import type { SpellStats } from '@/api/types'

// The stat lines a spell body opens with. The stat strip renders them, so they are not
// printed a second time - and the second copy would be the unexpanded one.
const STAT_LINE = /^\*\*(Casting Time|Range|Component|Components|Duration):\*\*/

/**
 * The stat block removed from the top of ``text``, leaving the spell's prose.
 *
 * The vendored text opens with `**Casting Time:** Action` and three more like it, which is
 * how the SRD lays the information out and is exactly what the strip renders better.
 * Leaving both shows every value twice.
 *
 * Only the *leading* run is ever dropped. Verified against all 539 spells the app can
 * resolve: no spell repeats a stat field inside its own description, so anchoring to the
 * top means a `**Range:**` mentioned in the prose of some future spell cannot be deleted by
 * mistake. An invocation has no stat block and is returned untouched - which is why a null
 * ``stats`` short-circuits.
 */
export function withoutStatLines(text: string, stats: SpellStats | null) {
  if (!stats) return text

  // Only the lines the strip definitely rendered are removed, so a field the strip left out
  // cannot vanish from the page entirely.
  const rendered = new Set(
    [
      'Casting Time',
      stats.range ? 'Range' : null,
      stats.components ? 'Components' : null,
      stats.components ? 'Component' : null,
      stats.duration ? 'Duration' : null,
    ].filter((field): field is string => field !== null),
  )

  const lines = text.split('\n')
  const kept: string[] = []
  let dropped = false
  let i = 0

  for (; i < lines.length; i++) {
    const line = lines[i]
    if (!line.trim()) {
      kept.push(line)
      continue
    }
    const match = STAT_LINE.exec(line)
    if (match) {
      if (!rendered.has(match[1])) break
      dropped = true
      continue
    }
    // The level line - `_Level 3 Evocation (Sorcerer, Wizard)_` - sits above the stat block
    // and is the one piece of the header the strip does not show, so it stays. Only before
    // the block, though: an italic line further down is part of the description.
    if (!dropped && /^_.*_$/.test(line.trim())) {
      kept.push(line)
      continue
    }
    break
  }

  if (!dropped) return text
  // The removed lines leave their blank neighbours behind, so the gaps around them collapse
  // back to a single paragraph break.
  return [...kept, ...lines.slice(i)].join('\n').replace(/\n{3,}/g, '\n\n').trimStart()
}
