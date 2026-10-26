import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Star } from 'lucide-react'

import { api, ApiError } from '@/api/client'
import type { RunSummary } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { formatSeconds } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
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
      <div className="grid gap-3 sm:grid-cols-2">
        {runs.map((run) => (
          <Card key={run.id}>
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
              <ViewRun run={run} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

/** Re-opens the stored run in place, so reading does not lose the listing. */
function ViewRun({ run }: { run: RunSummary }) {
  const [open, setOpen] = useState(false)
  const [books, setBooks] = useState<{ name: string; text: string; rating: number | null }[]>(
    [],
  )
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    if (open) {
      setOpen(false)
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
      setOpen(true)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="pt-1">
      <button
        onClick={toggle}
        className="text-arcane-300 hover:text-arcane-400 disabled:opacity-50"
        disabled={loading}
      >
        {loading ? 'Opening…' : open ? 'Hide books' : 'Read books'}
      </button>
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
                  preview full of ** and # markers reads as corruption. Clipped at the
                  first section so the card stays a preview. */}
              <Markdown
                text={book.text.slice(0, 400)}
                className="prose-spell mt-1 max-h-32 overflow-hidden text-xs after:from-void-900 after:absolute after:inset-x-0 after:bottom-0 after:h-8 after:bg-gradient-to-t after:content-[''] relative"
              />
            </div>
          ))}
          <Link
            to={`/scenario?scenario=${encodeURIComponent(run.scenario)}`}
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
