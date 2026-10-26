import {
  Coins,
  Crosshair,
  FlaskConical,
  Hourglass,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Timer,
} from 'lucide-react'

import type { SpellDamage, SpellStats } from '@/api/types'
import { cn } from '@/lib/utils'

/**
 * A spell's stat block, as a strip of icon-led tiles.
 *
 * Every value shown is one the backend read out of the vendored file, so this component
 * decides nothing — it only decides what a value *looks* like. Which is the whole reason
 * it exists: `V, S, M` is a rule reference, `8d6 Fire` sits in the description's second
 * paragraph, and a reader at the table should not have to hunt for either to cast the
 * spell.
 *
 * The order answers the questions as they get asked: how long to cast it, what it does,
 * where it reaches, what it needs, how long it lasts.
 */

/** An action economy word reads as a category, so it gets a colour rather than plain text. */
const ACTION_TONE: Record<string, string> = {
  action: 'text-arcane-300',
  'bonus action': 'text-verdant-400',
  reaction: 'text-radiant-400',
}

function actionTone(castingTime: string) {
  const head = castingTime.split(',')[0].trim().toLowerCase()
  return ACTION_TONE[head] ?? 'text-parchment'
}

function Tile({
  icon,
  label,
  value,
  detail,
  valueClassName,
  className,
}: {
  icon: React.ReactNode
  label: string
  value?: string
  detail?: React.ReactNode
  valueClassName?: string
  className?: string
}) {
  return (
    <div className={cn('flex items-start gap-2', className)}>
      <span className="mt-0.5 text-parchment/35">{icon}</span>
      <div className="min-w-0">
        <div className="text-[0.65rem] tracking-wide text-parchment/40 uppercase">
          {label}
        </div>
        {value && (
          <div className={cn('text-sm leading-tight', valueClassName)}>{value}</div>
        )}
        {detail && (
          <div className={cn('text-[0.7rem] text-parchment/45', value && 'mt-0.5')}>
            {detail}
          </div>
        )}
      </div>
    </div>
  )
}

/** One damage amount. A roll, a count of instances and a chosen type all read differently. */
function Damage({ entry }: { entry: SpellDamage }) {
  if (entry.chosen_type) {
    // No type to show, and inventing one would be worse than saying it is a choice.
    return (
      <span className="text-sm">
        <span className="font-mono text-parchment">{entry.dice}</span>{' '}
        <span className="text-parchment/50">of a type you choose</span>
      </span>
    )
  }

  if (!entry.types.length) {
    // The text stated a roll and no type at all. Rare, and shown plainly rather than
    // dressed up as a choice that was not offered.
    return <span className="text-sm font-mono text-parchment">{entry.dice}</span>
  }

  return (
    <span className="text-sm">
      {/* `5x` is five separate instances, not five dice, and the `x` says so - so it is not
          followed by a space the way a roll is. */}
      <span className="font-mono text-parchment">
        {entry.dice.endsWith('x') ? entry.dice : `${entry.dice} `}
      </span>
      <span className="text-parchment/55">{entry.types.join(' / ')}</span>
    </span>
  )
}

export function SpellStatsStrip({ stats }: { stats: SpellStats }) {
  const { components, damage } = stats

  return (
    <div className="grid gap-x-4 gap-y-3 border-y border-void-800 py-3 sm:grid-cols-2 lg:grid-cols-3">
      <Tile
        icon={<Timer className="h-4 w-4" />}
        label="Casting Time"
        value={stats.casting_time}
        valueClassName={actionTone(stats.casting_time)}
        detail={
          stats.ritual && (
            <span className="inline-flex items-center gap-1 text-verdant-400">
              <RefreshCw className="h-3 w-3" />
              Ritual: +10 minutes
            </span>
          )
        }
      />

      {/* Next to Casting Time on purpose: the damage is the number a reader is looking for,
          and the description buries it in the second paragraph. */}
      {damage.length > 0 && (
        <Tile
          icon={<Sparkles className="h-4 w-4" />}
          label={damage.length === 1 ? 'Damage' : 'Damage (each)'}
          detail={
            // A multi-type roll is one entry naming every type, and any one of them may
            // apply - so the types are joined rather than shown as separate amounts.
            <div className="space-y-0.5">
              {damage.map((entry, i) => (
                <Damage key={i} entry={entry} />
              ))}
            </div>
          }
        />
      )}

      <Tile
        icon={<Crosshair className="h-4 w-4" />}
        label="Range"
        value={stats.range ?? '—'}
      />

      <Tile
        icon={<Hourglass className="h-4 w-4" />}
        label="Duration"
        value={stats.duration ?? '—'}
        valueClassName={stats.concentration ? 'text-radiant-400' : undefined}
        detail={
          stats.concentration && (
            <span className="inline-flex items-center gap-1 text-radiant-400">
              <ShieldAlert className="h-3 w-3" />
              Concentration
            </span>
          )
        }
      />

      <Tile
        icon={<FlaskConical className="h-4 w-4" />}
        label={components?.letters.length === 1 ? 'Component' : 'Components'}
        // The letters are expanded because the shorthand assumes a rule the reader may not
        // have to hand. The material is left exactly as the file wrote it, because *which*
        // material is what decides whether a component pouch covers the spell.
        value={components ? components.expanded : '—'}
        detail={
          components?.material && (
            <span className="inline-flex flex-wrap items-center gap-1">
              {components.consumed && <Coins className="h-3 w-3 text-radiant-400" />}
              {components.material}
              {components.consumed && <span className="text-radiant-400">(consumed)</span>}
            </span>
          )
        }
      />
    </div>
  )
}
