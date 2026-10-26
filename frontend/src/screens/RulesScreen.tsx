import { useState } from 'react'

import { api, ApiError } from '@/api/client'
import type { Answer } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { SourceBadge } from '@/components/SourceBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const EXAMPLES = [
  'how does cover work',
  'what happens when you drop prone',
  'how does difficult terrain work',
]

/**
 * Rules lookup: the `/?` command.
 *
 * The answer is quoted from the 2024 SRD at 5e24srd.com and cached, so repeating a
 * question costs nothing. The 2024 SRD is not the whole 2024 rulebook, and several
 * common rules are genuinely absent from it - a Short Rest, for one. When that happens
 * the honest outcome is to say which part is missing rather than to answer from memory,
 * and a 404 is a normal result here, not an error to hide.
 */
export function RulesScreen() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function look(text = question) {
    if (!text.trim()) return
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
            <Button onClick={() => look()} disabled={loading}>
              {loading ? '…' : 'Look up'}
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
                {answer.citations.map((url) => (
                  <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-arcane-300 hover:text-arcane-400"
                  >
                    {url}
                  </a>
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
