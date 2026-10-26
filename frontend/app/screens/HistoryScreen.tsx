import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, Star } from 'lucide-react'

import { api, ApiError } from '@/api/client'
import type { RunSummary } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { formatSeconds } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

/**
 * Every stored run, newest first.
 *
 * Listed as runs rather than books: a book on its own is ambiguous, and the scenario is
 * what makes it meaningful. Re-opening returns the same shape the scenario screen
 * renders, so the reading experience is identical either way.
 */
export function HistoryScreen() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Which run is open lives here rather than inside each card, because the card's own
  // width depends on it: an open run takes the full row, and a child cannot widen its
  // parent. Only one is open at a time, which also keeps the listing scannable.
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    api
      .history()
      .then(setRuns)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)))
  }, [])

  if (error) {
    return <p className="text-sm text-red-300">{error}</p>
  }
  if (runs === null) {
    return <p className="text-sm text-parchment/50">Loading…</p>
  }
  if (runs.length === 0) {
    return (
      <p className="text-sm text-parchment/50">
        Nothing has been run yet. Generate a scenario and it will appear here.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-parchment">Past runs</h2>
      {/* Flex rather than a grid: an opened run needs to take the full width, and a
          grid cell cannot span its own row without knowing the column count. */}
      <div className="flex flex-wrap gap-3">
        {runs.map((run) => (
          <Card
            key={run.id}
            className={cn(
              'w-full',
              openId !== run.id && 'sm:w-[calc(50%-0.375rem)]',
            )}
          >
            <CardHeader className="flex-row items-start justify-between gap-3">
              <CardTitle className="text-sm leading-6">{run.scenario}</CardTitle>
              <Badge tone="muted">{run.book_count} books</Badge>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-parchment/55">
              <div className="flex flex-wrap gap-1">
                {run.book_names.map((name, i) => (
                  <span key={i} className="text-parchment/70">
                    {i > 0 && <span className="text-parchment/25"> · </span>}
                    {name}
                  </span>
                ))}
              </div>
              <div className="flex items-center justify-between font-mono">
                <span>{formatDate(run.created_at)}</span>
                <span>
                  {run.timings.total_seconds
                    ? formatSeconds(run.timings.total_seconds)
                    : '—'}
                </span>
              </div>
              <ViewRun
                run={run}
                open={openId === run.id}
                onToggle={() => setOpenId(openId === run.id ? null : run.id)}
              />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

/**
 * Re-opens the stored run in place, so reading does not lose the listing.
 *
 * `open` is owned by the list because it drives the card's width; this component only
 * fetches the books and reports the toggle.
 */
function ViewRun({
  run,
  open,
  onToggle,
}: {
  run: RunSummary
  open: boolean
  onToggle: () => void
}) {
  const [books, setBooks] = useState<{ name: string; text: string; rating: number | null }[]>(
    [],
  )
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    if (open) {
      onToggle()
      return
    }
    setLoading(true)
    setError(null)
    try {
      const result = await api.run(run.id)
      setBooks(
        result.books.map((book) => ({
          name: book.name,
          text: book.text,
          rating: book.rating?.score ?? null,
        })),
      )
      onToggle()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="pt-1">
      <Button variant="outline" size="sm" onClick={toggle} disabled={loading}>
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {loading ? 'Opening…' : 'Read books'}
      </Button>
      {error && <p className="pt-1 text-red-300">{error}</p>}
      {open && (
        <div className="mt-3 space-y-3 border-t border-void-800 pt-3">
          {books.map((book, i) => (
            <div key={i}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-parchment">{book.name}</span>
                {book.rating !== null && (
                  <span className="flex items-center gap-0.5 text-radiant-400">
                    <Star className="h-3 w-3 fill-radiant-400" />
                    {book.rating}
                  </span>
                )}
              </div>
              {/* Rendered rather than printed raw: the model emits markdown, and a
                  preview full of ** and # markers reads as corruption. Shown in full -
                  the card is already open, so clipping it only hides what was asked for. */}
              <Markdown text={book.text} className="prose-spell mt-1 text-xs" />
            </div>
          ))}
          <Link
            to={`/scenario?scenario=${encodeURIComponent(run.scenario)}&run=${encodeURIComponent(run.id)}`}
            className="inline-block text-arcane-300 hover:text-arcane-400"
          >
            Open in the scenario screen →
          </Link>
        </div>
      )}
    </div>
  )
}

function formatDate(value: string | null) {
  if (!value) return 'unknown'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
