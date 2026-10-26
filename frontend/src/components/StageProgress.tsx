import { Loader2 } from 'lucide-react'

import { PHASES, PHASE_LABELS } from '@/api/types'
import { formatSeconds } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Mirrors the CLI's progress line: which phase is running, how long it has been going,
 * and what to expect.
 *
 * The estimate comes from the backend's own recorded runs rather than a guess made
 * here, so the number shown is the median of what this machine actually did - and it
 * improves as more runs are recorded.
 */
export function StageProgress({
  stage,
  elapsed,
  estimate,
}: {
  /** Index into PHASES, or PHASES.length once every phase has finished. */
  stage: number
  elapsed: number
  estimate: number | null
}) {
  const percent = estimate ? Math.min(99, (elapsed / estimate) * 100) : null

  return (
    <div className="space-y-2">
      <ol className="space-y-1.5">
        {PHASES.map((phase, i) => {
          const done = i < stage
          const active = i === stage
          return (
            <li
              key={phase}
              className={cn(
                'flex items-center gap-2 text-sm',
                done && 'text-verdant-400',
                active && 'text-arcane-300',
                !done && !active && 'text-parchment/35',
              )}
            >
              {active ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <span className="w-3.5 text-center text-xs">{done ? '✓' : '·'}</span>
              )}
              {PHASE_LABELS[phase]}
            </li>
          )
        })}
      </ol>

      <div className="h-1.5 overflow-hidden rounded-full bg-void-800">
        <div
          className="h-full rounded-full bg-arcane-500 transition-[width] duration-500"
          style={{ width: `${percent ?? 5}%` }}
        />
      </div>

      <p className="font-mono text-xs text-parchment/50">{summary(elapsed, estimate)}</p>
    </div>
  )
}

function summary(elapsed: number, estimate: number | null) {
  const parts = [`${formatSeconds(elapsed)} elapsed`]
  if (estimate !== null) {
    const percent = Math.min(99, (elapsed / estimate) * 100)
    parts.push(`${percent.toFixed(0)}%`)
    parts.push(`${formatSeconds(Math.max(0, estimate - elapsed))} left`)
    parts.push(`expected ~${formatSeconds(estimate)}`)
  }
  return parts.join(' · ')
}
