import { useEffect, useRef, useState } from "react"

import { api, ApiError } from "@/api/client"
import type { Answer, Character, Health } from "@/api/types"
import { Markdown } from "@/components/Markdown"
import { RulesContextDrawerProvider } from "@/components/RulesContextDrawer"
import { SelectionWatcher } from "@/components/SelectionWatcher"
import { SourceBadge } from "@/components/SourceBadge"
import { SpellLink } from "@/components/SpellLink"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { splitSpells, useSpellNames } from "@/lib/spellNames"
import { Loader2, WandSparkles } from "lucide-react"

/**
 * The character sheet, plus a box to ask about it.
 *
 * Asking here is the `/c` command: a question whose answer is a field on the sheet
 * ("passive perception", "dex save") is resolved by lookup and comes back in
 * milliseconds with `source: "sheet"`. Anything else is answered by the model with the
 * sheet in context, and `source: "model"` says so. The two are shown differently
 * because one is a recorded fact and the other is an interpretation of one.
 *
 * The sheet is also a selection surface, the same as a book: selecting a value opens the
 * contextual drawer on it and searches the index. It is the surface where that is most
 * useful, because a sheet is dense with the things a reader wants explained - "Pact Slots:
 * Two 3rd-level slots", "Healing Light: 6d6 pool per Long Rest" - and the alternative is
 * retyping the phrase into the box below.
 */
export function CharacterScreen() {
  const [character, setCharacter] = useState<Character | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [keys, setKeys] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState<string | null>(null)
  // The conversation this screen is in. Held so a follow-up is read in context, and so
  // the exchange can be found again on the Chats screen.
  const [threadId, setThreadId] = useState<string | null>(null)

  // The sheet's values, and the only place a selection may come from. Scoped to the values
  // rather than the whole card so a selection in the header - the character's name - cannot
  // raise the drawer, and so the ask box below is outside it.
  const sheet = useRef<HTMLDListElement>(null)

  useEffect(() => {
    Promise.all([api.character(), api.health(), api.sheetKeys()])
      .then(([sheet, status, sheetKeys]) => {
        setCharacter(sheet)
        setHealth(status)
        setKeys(sheetKeys)
      })
      .catch((e: unknown) =>
        setError(e instanceof ApiError ? e.message : String(e)),
      )
  }, [])

  async function ask(text = question) {
    if (!text.trim()) return
    setAsking(true)
    setAskError(null)
    try {
      const result = await api.askCharacter(
        text,
        undefined,
        threadId ?? undefined,
      )
      setAnswer(result)
      setThreadId(result.thread_id)
    } catch (e) {
      setAskError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setAsking(false)
    }
  }

  if (error) return <p className="text-sm text-red-300">{error}</p>
  if (!character) return <p className="text-sm text-parchment/60">Loading…</p>

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>{character.name}</CardTitle>
          {health && <Badge tone="muted">index v{health.index_version}</Badge>}
        </CardHeader>
        <CardContent>
          {/* The provider wraps the sheet and the watcher together, because the watcher needs
              the drawer's `explore` and the drawer's panel belongs to this screen. */}
          <RulesContextDrawerProvider>
            <dl ref={sheet} className="divide-y divide-void-800">
              {Object.entries(character.sheet).map(([key, value]) => (
                <div
                  key={key}
                  className="grid grid-cols-[10rem_1fr] gap-4 py-2 text-sm"
                >
                  <dt className="text-parchment/60">{key}</dt>
                  <dd className="text-parchment/90">{renderValue(value)}</dd>
                </div>
              ))}
            </dl>

            <SelectionWatcher target={sheet} />
          </RulesContextDrawerProvider>
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
                onKeyDown={(e) => e.key === "Enter" && ask()}
              />
              <Button
                className="bg-verdant-400 hover:bg-verdant-300 hover:text-verdant-600 whitespace-nowrap text-void-900 rounded-full"
                onClick={() => ask()}
                disabled={asking}
              >
                {asking ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <WandSparkles className="h-4 w-4" />
                )}
                {asking ? "…" : "Ask"}
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
                    className="rounded-full border border-void-700 px-2 py-0.5 text-[0.7rem] text-parchment/60 hover:text-parchment"
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
              <p>model: {health.model ?? "unknown"}</p>
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
  return <SheetValue text={String(value)} />
}

/**
 * One sheet value, with the spell names in it linked.
 *
 * A sheet is a list of spell names as often as it is a number - `Known/Prepared Base Spells`,
 * `Always Prepared Spells`, `Eldritch Invocations` - and those names were dead text on the one
 * screen whose whole subject is this character's spells. The renderer's own mention rule is
 * reused rather than a second one written here, so a name that is linked in a book is linked
 * on the sheet and the two cannot disagree about what a spell is called.
 *
 * `linkSpells` is left on, which is the opposite of the spell card's choice: there the text
 * *is* the spell, so a link would point at itself. Here the text is a sheet that happens to
 * name spells, and every one of them is worth following.
 */
function SheetValue({ text }: { text: string }) {
  const names = useSpellNames()
  const parts = splitSpells(text, names)
  if (parts.length === 1 && !parts[0][1]) return text
  return (
    <>
      {parts.map(([chunk, isSpell], i) =>
        isSpell ? <SpellLink key={i} name={chunk} /> : chunk,
      )}
    </>
  )
}
