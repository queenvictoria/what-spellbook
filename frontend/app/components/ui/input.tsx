import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

export function Input({ className, ...props }: ComponentProps<'input'>) {
  return (
    <input
      className={cn(
        'h-9 w-full rounded-md border border-void-700 bg-void-950/70 px-3 text-sm text-parchment',
        'placeholder:text-parchment/35 focus-visible:border-arcane-400 ' +
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-arcane-400',
        className,
      )}
      {...props}
    />
  )
}
