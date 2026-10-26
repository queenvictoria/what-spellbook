import { useEffect, useState } from 'react'

import { api, ApiError } from '@/api/client'
import type { Answer, Character, Health } from '@/api/types'
import { Markdown } from '@/components/Markdown'
import { SourceBadge } from '@/components/SourceBadge'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

/**
 * The character sheet, plus a box to ask about it.
 *
 * Asking here is the `/c` command: a question whose answer is a field on the sheet
 * ("passive perception", "dex save") is resolved by lookup and comes back in
 * milliseconds with `source: "sheet"`. Anything else is answered by the model with the
 * sheet in context, and `source: "model"` says so. The two are shown differently
 * because one is a recorded fact and the other is an interpretation of one.
 */
export function CharacterScreen() {
  const [character, setCharacter] = useState<Character | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [keys, setKeys] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.character(), api.health(), api.sheetKeys()])
      .then(([sheet, status, sheetKeys]) => {
        setCharacter(sheet)
        setHealth(status)
        setKeys(sheetKeys)
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : String(e)))
  }, [])

  async function ask(text = question) {
    if (!text.trim()) return
    setAsking(true)
    setAskError(null)
    try {
      setAnswer(await api.askCharacter(text))
    } catch (e) {
      setAskError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAsking(false)
    }
  }

  if (error) return <p className="text-sm text-red-300">{error}</p>
  if (!character) return <p className="text-sm text-parchment/50">Loading…</p>

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>{character.name}</CardTitle>
          {health && (
            <Badge tone="muted">index v{health.index_version}</Badge>
          )}
        </CardHeader>
        <CardContent>
          <dl className="divide-y divide-void-800">
            {Object.entries(character.sheet).map(([key, value]) => (
              <div key={key} className="grid grid-cols-[10rem_1fr] gap-4 py-2 text-sm">
                <dt className="text-parchment/50">{key}</dt>
                <dd className="text-parchment/90">{renderValue(value)}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Ask about this character</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <Input
                value={question}
                placeholder="perception, dex save, why two Light spells…"
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && ask()}
              />
              <Button onClick={() => ask()} disabled={asking}>
                {asking ? '…' : 'Ask'}
              </Button>
            </div>

            {keys.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {keys.slice(0, 12).map((key) => (
                  <button
                    key={key}
                    onClick={() => {
                      setQuestion(key)
                      ask(key)
                    }}
                    className="rounded-full border border-void-700 px-2 py-0.5 text-[0.7rem] text-parchment/50 hover:text-parchment"
                  >
                    {key}
                  </button>
                ))}
              </div>
            )}

            {askError && <p className="text-xs text-red-300">{askError}</p>}

            {answer && (
              <div className="space-y-2 border-t border-void-800 pt-3">
                <SourceBadge source={answer.source} field={answer.field_name} />
                <Markdown text={answer.answer} className="prose-spell" />
              </div>
            )}
          </CardContent>
        </Card>

        {health && (
          <Card>
            <CardContent className="space-y-1 pt-4 font-mono text-xs text-parchment/45">
              <p>model: {health.model ?? 'unknown'}</p>
              <p>status: {health.status}</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

/** A sheet value is a string, number or list; a list reads better as a bullet run. */
function renderValue(value: unknown) {
  if (Array.isArray(value)) {
    return (
      <ul className="list-disc space-y-0.5 pl-4">
        {value.map((item, i) => (
          <li key={i}>{String(item)}</li>
        ))}
      </ul>
    )
  }
  return String(value)
}
