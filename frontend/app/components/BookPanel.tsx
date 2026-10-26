import { useState } from 'react'
import { ChevronDown, ChevronRight, Star } from 'lucide-react'

import { api, ApiError } from '@/api/client'
import type { Answer, Book } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { SourceBadge } from '@/components/SourceBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

const OUTCOMES = ['won', 'lost', 'unused', 'partial'] as const

/**
 * One book, with its picks, its text, a rating, and a place to ask about it.
 *
 * A rating belongs to the book *slot*, not to the file, so re-generating a scenario
 * keeps the history of how that approach actually went. That is why the star row is
 * per book and why the notes field exists.
 *
 * `scenario` and `runId` are both needed and are not interchangeable: `/api/ask` keys on
 * the scenario text, while `/api/runs/{id}/rate` needs the run's id. Rating by scenario
 * text is ambiguous, because a run is keyed on the scenario *and* the character, level
 * and book count - so two runs can share a scenario and the wrong one gets rated.
 */
export function BookPanel({
  book,
  scenario,
  runId,
}: {
  book: Book
  scenario: string
  runId: string | null
}) {
  const [expanded, setExpanded] = useState(true)
  const [rating, setRating] = useState(book.rating?.score ?? null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [asking, setAsking] = useState(false)

  const picks = Object.entries(book.picks ?? {})

  // A run that was never persisted has no id to rate against. That happens when no
  // character is loaded, and the honest thing is to disable the control rather than
  // let a click fail.
  const rateable = runId !== null

  async function saveScore(score: number) {
    if (!runId) return
    setRating(score)
    setSaving(true)
    setError(null)
    try {
      await api.rate(runId, {
        score,
        book: String(book.index),
      })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setRating(book.rating?.score ?? null)
    } finally {
      setSaving(false)
    }
  }

  async function ask() {
    if (!question.trim()) return
    setAsking(true)
    setError(null)
    try {
      setAnswer(await api.ask(scenario, question))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAsking(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <button
          className="flex items-start gap-2 text-left"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="mt-0.5 h-4 w-4 text-parchment/40" />
          ) : (
            <ChevronRight className="mt-0.5 h-4 w-4 text-parchment/40" />
          )}
          <div>
            <CardTitle>
              <span className="text-parchment/35">Book {book.index}: </span>
              {book.name}
            </CardTitle>
            <p className="mt-0.5 text-xs text-parchment/45">
              {picks.length} categor{picks.length === 1 ? 'y' : 'ies'} of picks
            </p>
          </div>
        </button>

        <div className="flex items-center gap-1">
          {[1, 2, 3, 4, 5].map((score) => (
            <button
              key={score}
              onClick={() => saveScore(score)}
              disabled={saving || !rateable}
              aria-label={`Rate ${score} out of 5`}
              title={rateable ? undefined : 'This run was not stored, so it cannot be rated'}
              className={cn('p-0.5', !rateable && 'cursor-not-allowed opacity-40')}
            >
              <Star
                className={cn(
                  'h-4 w-4 transition-colors',
                  rating !== null && score <= rating
                    ? 'fill-radiant-400 text-radiant-400'
                    : 'text-parchment/25 hover:text-radiant-400',
                )}
              />
            </button>
          ))}
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4">
          {picks.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {picks.map(([group, names]) => (
                <Badge key={group} tone="arcane">
                  {group}:{' '}
                  {names.map((name, i) => (
                    <span key={name}>
                      {i > 0 && ', '}
                      <a
                        href={`/rules?spell=${encodeURIComponent(name)}`}
                        className="underline decoration-dotted underline-offset-2 hover:text-arcane-200"
                        title={`Look up ${name} in the rules`}
                      >
                        {name}
                      </a>
                    </span>
                  ))}
                </Badge>
              ))}
            </div>
          )}

          <Markdown text={book.text} className="prose-spell" />

          <div className="border-t border-void-800 pt-3">
            <div className="flex gap-2">
              <Input
                value={question}
                placeholder="Ask about this scenario, e.g. what if it has fire resistance?"
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && ask()}
              />
              <Button variant="secondary" onClick={ask} disabled={asking}>
                {asking ? '…' : 'Ask'}
              </Button>
            </div>
            {answer && (
              <div className="mt-3 space-y-2">
                <SourceBadge source={answer.source} field={answer.field_name} />
                <Markdown text={answer.answer} className="prose-spell" />
              </div>
            )}
          </div>

          {error && <p className="text-xs text-red-300">{error}</p>}

          <OutcomeRow book={book} runId={runId} />
        </CardContent>
      )}
    </Card>
  )
}

/**
 * How the book actually played out. Separate from the star rating because they answer
 * different questions: a book can be well built and still lose, and that is exactly the
 * distinction that makes the record worth keeping.
 */
function OutcomeRow({ book, runId }: { book: Book; runId: string | null }) {
  const [outcome, setOutcome] = useState(book.rating?.outcome ?? null)
  const [notes, setNotes] = useState(book.rating?.notes ?? '')
  const [saved, setSaved] = useState(false)
  const [failed, setFailed] = useState(false)

  // A rating is keyed on a score, so an outcome cannot be stored before one exists.
  // Substituting a default would record a judgement the user never made.
  const score = book.rating?.score ?? null
  const disabled = score === null || runId === null

  async function save(next: string) {
    if (score === null || !runId) return
    setOutcome(next)
    setSaved(false)
    setFailed(false)
    try {
      await api.rate(runId, {
        score,
        book: String(book.index),
        outcome: next,
        notes: notes || undefined,
      })
      setSaved(true)
    } catch {
      setFailed(true)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-parchment/45">Outcome</span>
      {OUTCOMES.map((option) => (
        <button
          key={option}
          onClick={() => save(option)}
          disabled={disabled}
          title={disabled ? 'Rate the book first' : undefined}
          className={cn(
            'rounded-full border px-2 py-0.5 transition-colors',
            disabled && 'cursor-not-allowed opacity-40',
            outcome === option
              ? 'border-arcane-500/50 bg-arcane-500/15 text-arcane-300'
              : 'border-void-700 text-parchment/50 hover:text-parchment',
          )}
        >
          {option}
        </button>
      ))}
      <Input
        value={notes}
        placeholder={disabled ? 'rate the book first' : 'notes'}
        disabled={disabled}
        onChange={(e) => setNotes(e.target.value)}
        onBlur={() => !disabled && notes && outcome && save(outcome)}
        className="h-7 max-w-48 text-xs"
      />
      {saved && <span className="text-verdant-400">saved</span>}
      {failed && <span className="text-red-300">could not save</span>}
    </div>
  )
}


