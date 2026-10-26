import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

type Tone = 'arcane' | 'radiant' | 'verdant' | 'muted'

const TONES: Record<Tone, string> = {
  arcane: 'border-arcane-500/40 bg-arcane-500/15 text-arcane-300',
  radiant: 'border-radiant-500/40 bg-radiant-500/15 text-radiant-400',
  verdant: 'border-verdant-400/40 bg-verdant-400/15 text-verdant-400',
  muted: 'border-void-700 bg-void-800/70 text-parchment/60',
}

export function Badge({
  className,
  tone = 'muted',
  ...props
}: ComponentProps<'span'> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] ' +
          'font-medium whitespace-nowrap',
        TONES[tone],
        className,
      )}
      {...props}
    />
  )
}
