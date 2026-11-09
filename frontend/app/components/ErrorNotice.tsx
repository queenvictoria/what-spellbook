import { RefreshCw, TriangleAlert } from 'lucide-react'

import { describeFailure } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

/**
 * One failure, rendered the same way everywhere.
 *
 * The screens used to print `e.message` as a red line, which is fine for "no such run" and
 * useless for the failure that actually happens: a stopped Ollama. The backend now writes
 * an actionable message, and this is what makes it readable - a headline naming the kind of
 * failure, the message itself, and a Retry button only when retrying could work.
 *
 * `onRetry` is optional because not every caller can retry: a screen that failed while
 * loading has nothing to re-run, and a button that does nothing is worse than no button.
 */
export function ErrorNotice({
  error,
  onRetry,
  className,
  compact = false,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
  /** Inline form for a panel inside a card, where a full card would nest badly. */
  compact?: boolean
}) {
  const failure = describeFailure(error)
  const showRetry = failure.retryable && onRetry !== undefined

  return (
    <div
      role="alert"
      className={cn(
        'rounded-lg border border-red-500/40 bg-red-500/5',
        compact ? 'p-3' : 'p-4',
        className,
      )}
    >
      <div className="flex gap-3">
        <TriangleAlert
          className={cn(
            'shrink-0 text-red-300',
            compact ? 'mt-0.5 h-4 w-4' : 'mt-0.5 h-5 w-5',
          )}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p
            className={cn(
              'font-semibold text-red-300',
              compact ? 'text-xs' : 'text-sm',
            )}
          >
            {failure.title}
          </p>
          <p
            className={cn(
              'break-words text-parchment/70',
              compact ? 'text-xs' : 'text-sm',
            )}
          >
            {failure.message}
          </p>
          {showRetry && (
            <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
