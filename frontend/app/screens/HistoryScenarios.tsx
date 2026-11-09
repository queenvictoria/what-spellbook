import { useCallback, useEffect, useState } from "react"
import { Link } from "react-router-dom"
import {
  BookIcon,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Waypoints,
} from "lucide-react"

import { api } from "@/api/client"
import type { Book, RunSummary } from "@/api/types"
import { BookPanel } from "@/components/BookPanel"
import { ErrorNotice } from "@/components/ErrorNotice"
import { formatSeconds } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/**
 * Every stored run, newest first.
 *
 * Listed as runs rather than books: a book on its own is ambiguous, and the scenario is
 * what makes it meaningful. Re-opening returns the same shape the scenario screen
 * renders, so the reading experience is identical either way.
 */
export function HistoryScenarios() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  // Which run is open lives here rather than inside each card, because the card's own
  // width depends on it: an open run takes the full row, and a child cannot widen its
  // parent. Only one is open at a time, which also keeps the listing scannable.
  const [openId, setOpenId] = useState<string | null>(null)
  // Which book of which run was clicked in a card's header. Held until the run's books
  // have loaded - the element does not exist yet when the name is clicked - and then
  // handed to `ViewRun`, which scrolls to it and clears it.
  const [focus, setFocus] = useState<{ runId: string; slot: number } | null>(
    null,
  )

  function toggleRun(id: string) {
    setFocus(null)
    setOpenId(openId === id ? null : id)
  }

  // Stable, because `ViewRun`'s scroll effect depends on it: a fresh identity each
  // render would re-run that effect on every render.
  const clearFocus = useCallback(() => setFocus(null), [])

  useEffect(() => {
    api
      .history()
      .then(setRuns)
      .catch(setError)
  }, [])

  if (error) {
    return <ErrorNotice error={error} />
  }
  if (runs === null) {
    return <p className="text-sm text-parchment/60">Loading…</p>
  }
  if (runs.length === 0) {
    return (
      <p className="text-sm text-parchment/60">
        Nothing has been run yet. Generate a scenario and it will appear here.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {/* Flex rather than a grid: an opened run needs to take the full width, and a
          grid cell cannot span its own row without knowing the column count. */}
      <div className="flex flex-wrap gap-3">
        {runs.map((run) => (
          <Card
            key={run.id}
            className={cn(
              "w-full",
              openId !== run.id && "sm:w-[calc(50%-0.375rem)]",
            )}
          >
            <CardHeader className="flex-row items-start justify-between gap-3">
              <CardTitle className="text-sm leading-6">
                <button
                  className="text-left font-medium text-parchment hover:underline"
                  onClick={() => toggleRun(run.id)}
                >
                  {run.scenario}
                </button>
              </CardTitle>
              <Badge tone="muted">{run.book_count} books</Badge>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-parchment/55">
              <div className="flex flex-wrap gap-1">
                {run.book_names.map((name, i) => (
                  <span key={i} className="text-parchment/70">
                    {i > 0 && <span className="text-parchment/25"> · </span>}
                    <button
                      className="text-arcane-300 text-left font-medium underline-offset-4  hover:underline"
                      onClick={() => {
                        // The book element only exists once the run is open *and* its
                        // books have been fetched, so the slot is remembered and
                        // scrolled to from `ViewRun` after they render.
                        setOpenId(run.id)
                        setFocus({ runId: run.id, slot: i })
                      }}
                    >
                      {name}
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex items-center justify-between font-mono">
                <span>{formatDate(run.created_at)}</span>
                <span>
                  {run.timings.total_seconds
                    ? formatSeconds(run.timings.total_seconds)
                    : "—"}
                </span>
              </div>
              <ViewRun
                run={run}
                open={openId === run.id}
                focusSlot={focus?.runId === run.id ? focus.slot : null}
                onFocused={clearFocus}
                onToggle={() => toggleRun(run.id)}
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
 *
 * The books are rendered with the same `BookPanel` the scenario screen uses, rather than
 * a read-only preview. A rating is the whole reason to come back to a past run - "how did
 * that approach actually go?" - and a history page that shows the stars but cannot set
 * them makes the user navigate away to record the answer. Reusing the panel also means
 * the two screens cannot drift apart in what they show.
 */
function ViewRun({
  run,
  open,
  focusSlot,
  onFocused,
  onToggle,
}: {
  run: RunSummary
  open: boolean
  focusSlot: number | null
  onFocused: () => void
  onToggle: () => void
}) {
  const [books, setBooks] = useState<Book[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  // Fetch when the run is opened from anywhere, not only from this component's own
  // button. A book name in the card header opens the run directly, and with the fetch
  // confined to the button's handler that path widened the card and rendered nothing.
  useEffect(() => {
    if (!open || books !== null) return
    let cancelled = false
    api
      .run(run.id)
      .then((result) => {
        if (cancelled) return
        setBooks(result.books)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e)
        }
      })
    return () => {
      cancelled = true
    }
  }, [open, books, run.id])

  // Derived rather than stored: the fetch is driven by `open`, so a `loading` flag set
  // from the effect would be a second source of truth for the same fact.
  const loading = open && books === null && error === null

  // Scroll to the clicked book once it exists. The element cannot be found earlier: a
  // book name is clicked while the books are still being fetched.
  useEffect(() => {
    if (focusSlot === null || !open || books === null) return
    const target = books[focusSlot]
    if (target) {
      document
        .getElementById(`${run.id}-book-${target.index}`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" })
    }
    onFocused()
  }, [focusSlot, open, books, run.id, onFocused])

  return (
    <div className="pt-1">
      <div className="pt-1 flex gap-2 justify-between @container">
        <Button
          variant="outline"
          size="sm"
          onClick={onToggle}
          disabled={loading}
        >
          <span className="@sm:hidden">
            {open ? (
              <BookIcon className="h-4 w-4" />
            ) : (
              <BookOpen className="h-4 w-4" />
            )}
          </span>
          <span className="hidden @sm:flex items-center gap-1">
            {open ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            {open ? "Hide books" : "Read books"}
          </span>
        </Button>
        <Link
          to={`/scenario?scenario=${encodeURIComponent(run.scenario)}&run=${encodeURIComponent(run.id)}`}
          className="inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-arcane-400 disabled:pointer-events-none disabled:opacity-50 border border-void-700 bg-transparent hover:bg-void-800 h-8 px-3 text-xs"
        >
          <Waypoints className="h-4 w-4" />
          <span className="hidden @sm:inline">Open in the scenario screen</span>
        </Link>
        {error != null && <ErrorNotice error={error} compact className="mt-1" />}
      </div>
      {open && books !== null && (
        <div className="mt-3 space-y-3 border-t border-void-800 pt-3">
          {books.map((book) => (
            <BookPanel
              key={book.index}
              book={book}
              scenario={run.scenario}
              runId={run.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function formatDate(value: string | null) {
  if (!value) return "unknown"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}
