import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search } from 'lucide-react'

import { api, ApiError } from '@/api/client'
import type { Answer, Spell } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { SourceBadge } from '@/components/SourceBadge'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const EXAMPLES = [
  'how does cover work',
  'what happens when you drop prone',
  'how does difficult terrain work',
]

/**
 * Rules lookup: the `/?` command, and the target of every spell mention in the app.
 *
 * Answers are quoted from the vendored 2024 SRD in `context/srd/` and cached, so
 * repeating a question costs nothing. The 2024 SRD is not the whole 2024 rulebook, and
 * several common rules are genuinely absent from it - a Short Rest, for one. When that
 * happens the honest outcome is to say which part is missing rather than to answer from
 * memory, and a 404 is a normal result here, not an error to hide.
 *
 * `?spell=Name` opens a spell instead of a question. The spell text comes from the same
 * vendored SRD, so a spell the corpus knows but the SRD dropped (Tenser's Floating Disk,
 * Bigby's Hand) reports that plainly rather than showing nothing.
 */
export function RulesScreen() {
  const [params, setParams] = useSearchParams()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const spellName = params.get('spell')

  // The spell is fetched into state keyed by name, and the render reads it only when the
  // key still matches the URL. That keeps the effect free of synchronous setState - which
  // would cascade a second render on every navigation - while still clearing the card the
  // moment the query changes.
  const [loaded, setLoaded] = useState<{ name: string; spell: Spell } | null>(null)
  const spell = loaded && loaded.name === spellName ? loaded.spell : null

  useEffect(() => {
    if (!spellName) return
    let cancelled = false
    api
      .spell(spellName)
      .then((found) => {
        if (!cancelled) setLoaded({ name: spellName, spell: found })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (e instanceof ApiError && e.status === 404) setMissing(e.message)
        else setError(e instanceof ApiError ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [spellName])

  async function look(text = question) {
    if (!text.trim()) return
    if (spellName) setParams({}, { replace: true })
    setLoading(true)
    setError(null)
    setAnswer(null)
    setMissing(null)
    try {
      setAnswer(await api.rules(text))
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setMissing(e.message)
      } else {
        setError(e instanceof ApiError ? e.message : String(e))
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Ask the 2024 SRD</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={question}
              placeholder="how does cover work"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && look()}
            />
            <Button
              onClick={() => look()}
              disabled={loading}
              aria-label="Look up"
              title="Look up in the 2024 SRD"
              className="shrink-0 whitespace-nowrap"
            >
              <Search className="h-4 w-4" />
              <span className="sr-only">Look up</span>
            </Button>
          </div>
          <div className="flex flex-wrap gap-1">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => {
                  setQuestion(example)
                  look(example)
                }}
                className="rounded-full border border-void-700 px-2 py-0.5 text-[0.7rem] text-parchment/50 hover:text-parchment"
              >
                {example}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-red-500/40">
          <CardContent className="pt-4 text-sm text-red-300">{error}</CardContent>
        </Card>
      )}

      {missing && (
        <Card className="border-radiant-500/40">
          <CardHeader>
            <CardTitle className="text-radiant-400">Not in the SRD</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-parchment/70">
            <p>{missing}</p>
            <p className="text-xs text-parchment/45">
              The 2024 SRD is a subset of the 2024 rulebook. Rules that are absent here
              are reported as absent rather than answered from memory, because a
              confidently wrong rule is worse than a gap.
            </p>
          </CardContent>
        </Card>
      )}

      {spell && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-sm">{spell.name}</CardTitle>
            {/* The SRD is the 2024 authority; the corpus is not. A spell the SRD does not
                carry is still shown, but it must not look like an SRD quote. */}
            {spell.source === 'vendored-srd-5.2.1' ? (
              <SourceBadge source="rules" />
            ) : (
              <Badge tone="muted">From the spell corpus</Badge>
            )}
          </CardHeader>
          <CardContent className="space-y-3">
            <Markdown text={spell.text} className="prose-spell" linkSpells={false} />
            <p className="border-t border-void-800 pt-2 font-mono text-xs text-parchment/40">
              {spell.url}
            </p>
          </CardContent>
        </Card>
      )}

      {answer && (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-sm">{answer.question}</CardTitle>
            <SourceBadge source={answer.source} />
          </CardHeader>
          <CardContent className="space-y-3">
            <Markdown text={answer.answer} className="prose-spell" />
            {answer.citations.length > 0 && (
              <div className="border-t border-void-800 pt-2 text-xs">
                {answer.citations.map((path) => (
                  <p key={path} className="truncate font-mono text-parchment/40">
                    {path}
                  </p>
                ))}
              </div>
            )}
            {answer.from_cache && (
              <p className="text-xs text-parchment/40">Answered from cache.</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
