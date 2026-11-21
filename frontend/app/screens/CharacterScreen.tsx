import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/api/client"
import { streamed } from "@/api/stream"
import type { Answer, Character, CharacterEntry, Health } from "@/api/types"
import { CharacterImporter } from "@/components/CharacterImporter"
import { CharacterPicker } from "@/components/CharacterPicker"
import { ErrorNotice } from "@/components/ErrorNotice"
import { Markdown } from "@/components/Markdown"
import { RulesContextDrawerProvider } from "@/components/RulesContextDrawer"
import { SelectionWatcher } from "@/components/SelectionWatcher"
import { SourceBadge } from "@/components/SourceBadge"
import { SpellLink } from "@/components/SpellLink"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StageProgress } from "@/components/StageProgress"
import { StreamingPreview } from "@/components/StreamingPreview"
import { STREAM_STAGE_LABELS } from "@/api/types"
import { useStreamStages } from "@/lib/useStreamStages"
import { Badge } from "@/components/ui/badge"
import { splitSpells, useSpellNames } from "@/lib/spellNames"
import { useCharacterChoice } from "@/lib/useCharacterChoice"
import {
  Loader2,
  WandSparkles,
  UsersRoundCollaboration,
  UserRound,
} from "lucide-react"

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
  // Which sheet to show. `selected` is null when this browser has never chosen, in which case
  // the server applies its own `CHARACTER` default and the picker offers that as "server default".
  const {
    entries: characters,
    selected,
    choose,
    refresh,
  } = useCharacterChoice()

  const [character, setCharacter] = useState<Character | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [keys, setKeys] = useState<string[]>([])
  // The failure itself, not its message: the notice decides how to present it, and a
  // retry needs the original error to know whether retrying is even sensible.
  const [error, setError] = useState<unknown>(null)

  const [question, setQuestion] = useState("")
  const [asking, setAsking] = useState(false)
  // A sheet lookup is instant and never shows this; the stages appear only when the question
  // reached the model, which is the half that takes seconds.
  const askStages = useStreamStages()
  // The exchange is stamped with the character it belongs to, and only the one matching the
  // sheet on screen is displayed. That is what makes switching characters start a new line of
  // questioning without a reset effect: an answer is a statement about *one* sheet, so an
  // answer for the previous character is not context for the next one - and the thread id would
  // have the backend append a follow-up about a different person to the old conversation.
  //
  // Deriving it rather than clearing it in an effect also means the two can never get out of
  // order: a clear that runs before the new sheet has loaded would blank an answer that then
  // reappears, and React's own guidance is that resetting state on a prop change is a render
  // concern, not a subscription.
  const [exchange, setExchange] = useState<Exchange | null>(null)
  const current = exchange?.for === selected ? exchange : null
  const answer = current?.answer ?? null
  const askError = current?.error ?? null

  // The sheet's values, and the only place a selection may come from. Scoped to the values
  // rather than the whole card so a selection in the header - the character's name - cannot
  // raise the drawer, and so the ask box below is outside it.
  const sheet = useRef<HTMLDListElement>(null)

  // Which ask is the newest, so a reply that lost a race cannot land on a newer question.
  const askedRun = useRef(0)

  // Depends on the chosen character, so switching re-fetches the sheet rather than leaving the
  // previous one on screen under a header that now names a different character.
  const load = useCallback(() => {
    Promise.all([
      api.character(selected ?? undefined),
      api.health(),
      api.sheetKeys(),
    ])
      .then(([sheet, status, sheetKeys]) => {
        setCharacter(sheet)
        setHealth(status)
        setKeys(sheetKeys)
      })
      .catch(setError)
  }, [selected])

  useEffect(load, [load])

  // Clearing the failure is the retry's own job rather than the loader's: a `setError(null)`
  // inside the effect body is a synchronous setState during render's commit, which React
  // warns about and which would blank the notice for a frame before the request even starts.
  function retry() {
    setError(null)
    load()
  }

  function switchTo(name: string) {
    // Choosing the sheet already on screen is a no-op. It has to be, because `selected` is the
    // browser's *preference* while the picker shows the loaded sheet - so with nothing stored the
    // two differ from the start, and changing the preference to the character already displayed
    // would re-fetch the same sheet and drop the answer along with it.
    if (name === character?.id) return
    // Clear the failure first: an error from a sheet that failed to load must not outlive the
    // switch to one that loads, and the loader only re-runs on a change of `selected`.
    setError(null)
    choose(name)
  }

  const imported = useCallback(
    async (entry: CharacterEntry) => {
      await refresh()
      setError(null)
      choose(entry.id)
      if (entry.id === selected && entry.id === character?.id) load()
    },
    [character?.id, choose, load, refresh, selected],
  )

  async function ask(text = question) {
    if (!text.trim()) return
    // Captured before the await, so an answer that arrives after the reader has switched sheets
    // is filed under the character it was asked about rather than the one now on screen.
    const asked = selected
    const run = ++askedRun.current
    setAsking(true)
    // The previous answer stays visible while a follow-up is in flight - it is still a true
    // statement about this character, and blanking it makes the panel flicker. For a *different*
    // character `current` is already null, so the panel starts empty by construction.
    setExchange({
      for: asked,
      answer: current?.answer ?? null,
      error: null,
      threadId: current?.threadId ?? null,
    })
    try {
      askStages.start("character")
      const result = await streamed.character(
        text,
        // Follow the sheet on screen. Passing `undefined` here is what made this screen answer
        // about the server's default character however it was displaying.
        asked ?? undefined,
        current?.threadId ?? undefined,
        askStages.handlers,
      )
      // A slower earlier request must not overwrite a newer answer: two asks in flight is
      // possible by switching character and asking again, and last-write-wins here would show
      // the wrong reply under the right header.
      if (run === askedRun.current) {
        setExchange({
          for: asked,
          answer: result,
          error: null,
          threadId: result.thread_id,
        })
      }
    } catch (e) {
      if (run === askedRun.current) {
        setExchange({
          for: asked,
          answer: null,
          error: e,
          threadId: current?.threadId ?? null,
        })
      }
    } finally {
      if (run === askedRun.current) {
        setAsking(false)
        askStages.finish()
      }
    }
  }

  if (error != null) {
    // The picker is kept, because the commonest reason a sheet fails to load is that *this* sheet
    // is broken - and replacing the whole screen with the failure would remove the only control
    // that can switch to one that works.
    return (
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <CardTitle>Character</CardTitle>
          <CharacterPicker
            entries={characters}
            value={selected}
            onChange={switchTo}
          />
          <CharacterImporter onImported={imported} />
        </CardHeader>
        <CardContent>
          <ErrorNotice error={error} onRetry={retry} />
        </CardContent>
      </Card>
    )
  }
  if (!character || (selected !== null && character.id !== selected)) {
    return (
      <Card>
        <CardHeader className="flex-row items-center gap-2">
          <CardTitle>Character</CardTitle>
          <CharacterPicker
            entries={characters}
            value={selected}
            onChange={switchTo}
          />
          <CharacterImporter onImported={imported} />
        </CardHeader>
        <CardContent>
          <p className="text-sm text-parchment/60">Loading…</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <Card>
        <CardHeader className="flex flex-col w-full gap-2">
          <div className="w-full items-start flex flex-row gap-2 justify-between">
            <CardTitle>
              <div className="border border-void-700 bg-void-800/70 rounded-full w-10 h-10 items-center flex justify-center text-parchment/60">
                <UserRound />
              </div>
              {character.name}
            </CardTitle>
            {health && (
              <Badge tone="muted">index v{health.index_version}</Badge>
            )}
          </div>
          <details className="flex flex-row-reverse items-start gap-2">
            <summary className="text-sm flex gap-2 text-parchment/60 hover:text-parchment">
              <UsersRoundCollaboration width={20} height={20} />
              <span className="sr-only">Character picker</span>
            </summary>
            <div className="flex flex-col gap-2 justify-between">
              <CharacterPicker
                entries={characters}
                value={character.id}
                onChange={switchTo}
              />
              <CharacterImporter onImported={imported} />
            </div>{" "}
          </details>
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
                {asking ? "Asking" : "Ask"}
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

            {asking && (
              <div className="space-y-3">
                <StageProgress
                  stage={askStages.stage}
                  elapsed={askStages.elapsed}
                  // Only shown once work actually started: a sheet lookup answers in
                  // milliseconds and would flash a progress list nobody can read.
                  estimate={null}
                  stages={askStages.stages}
                  labels={STREAM_STAGE_LABELS}
                />
                <StreamingPreview text={askStages.output} />
              </div>
            )}

            {askError != null && (
              <ErrorNotice error={askError} compact onRetry={() => ask()} />
            )}

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

/**
 * One question and its answer, stamped with the character it was asked about.
 *
 * `for` is compared against the sheet on screen, so the pair is self-describing rather than
 * relying on something else having remembered to clear it.
 */
interface Exchange {
  for: string | null
  answer: Answer | null
  error: unknown
  /** The conversation this exchange belongs to, so a follow-up is read in context. */
  threadId: string | null
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
