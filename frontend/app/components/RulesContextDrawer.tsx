import { useCallback, useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { X } from "lucide-react"

import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
} from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { AttachmentChips } from "@/components/AttachmentChips"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { StageProgress } from "@/components/StageProgress"
import { api } from "@/api/client"
import type { Answer } from "@/api/types"
import { CONTEXT_STAGES, CONTEXT_STAGE_LABELS } from "@/api/types"
import { RulesContext, useRulesContext } from "@/lib/rulesContext"
import { extractSpellNames, useSpellNames } from "@/lib/spellNames"

/** How long each stage is assumed to take, so the list advances on a run with no progress. */
const STAGE_AFTER_MS = [400, 900, 1500]

/**
 * The contextual menu: select prose from a book, click the button, read the explanation.
 *
 * Two things make this panel worth more than a text field and an answer. It shows the
 * **documents** the question will carry - the spells the selection names are attached by
 * name, and can be removed - and it shows the **stages** while the answer is being
 * assembled, because the work takes seconds and a reader who sees nothing has no way to
 * tell a slow model from a stuck one.
 */
export function RulesContextDrawerProvider({
  children,
}: {
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [selectedText, setSelectedText] = useState("")
  const [attachments, setAttachments] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(0)
  // The text the current attachments were derived from. Without it, editing the question and
  // asking again reuses the previous answer's documents - which no longer match the words on
  // screen, and would attach a spell the new text never named.
  const attachedFor = useRef("")
  const names = useSpellNames()

  // The stage list advances on a timer because the backend does not stream: the response
  // carries no progress until it is finished. It is therefore a display heuristic, and it
  // is honest about that - the elapsed readout is real, and the bar cannot run past full.
  useEffect(() => {
    if (!loading) return
    const timer = setInterval(() => {
      const ms = performance.now() - started.current
      setElapsed(ms / 1000)
      const index = STAGE_AFTER_MS.findIndex((threshold) => ms < threshold)
      setStage(index === -1 ? CONTEXT_STAGES.length - 1 : index)
    }, 100)
    return () => clearInterval(timer)
  }, [loading])

  /** The spells the prose names, found the way the renderer finds links. */
  const mentionsIn = useCallback(
    (text: string): string[] => extractSpellNames(text, names),
    [names],
  )

  const ask = useCallback(
    async (text: string, context?: string, documents?: string[]) => {
      const question = text.trim()
      if (!question) return

      // Documents may be passed in (the selection's own mentions, resolved before the click)
      // or derived here, so the drawer's own Ask works with no selection at all. A list kept
      // from an earlier question is reused only while the words are unchanged: keeping the
      // edits would attach whatever the previous text named.
      const kept =
        documents ?? (attachedFor.current === question ? attachments : [])
      const derived = kept.length > 0 ? kept : mentionsIn(question)

      setSelectedText(question)
      attachedFor.current = question
      setAttachments(derived)
      setOpen(true)
      setLoading(true)
      setStage(0)
      setElapsed(0)
      started.current = performance.now()
      setError(null)
      setAnswer(null)
      try {
        setAnswer(await api.rulesContextual(question, context, derived))
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Could not reach the rules lookup.",
        )
      } finally {
        setLoading(false)
        setStage(CONTEXT_STAGES.length)
      }
    },
    [attachments, mentionsIn],
  )

  const remove = useCallback((name: string) => {
    setAttachments((current) => current.filter((item) => item !== name))
  }, [])

  return (
    <RulesContext.Provider
      value={{
        open,
        setOpen,
        selectedText,
        setSelectedText,
        ask,
        loading,
        answer,
        error,
        attachments,
        removeAttachment: remove,
      }}
    >
      {children}
      <RulesContextDrawer stage={stage} elapsed={elapsed} />
    </RulesContext.Provider>
  )
}

function RulesContextDrawer({
  stage,
  elapsed,
}: {
  stage: number
  elapsed: number
}) {
  const {
    open,
    setOpen,
    selectedText,
    setSelectedText,
    ask,
    loading,
    answer,
    error,
    attachments,
    removeAttachment,
  } = useRulesContext()

  // Asking twice with the same words and the same documents is the same question, so the
  // box reuses the snapshot the attachments were last derived from rather than re-deriving
  // them: a reader who removed a spell keeps it removed while they edit the wording.
  const canAsk = selectedText.trim().length > 0 && !loading

  return (
    <Drawer open={open} onOpenChange={setOpen} swipeDirection="right">
      <DrawerContent>
        <DrawerTitle className="sr-only">Rules Context</DrawerTitle>
        <DrawerDescription className="sr-only">
          An explanation of the selected text in the context of D&D 5.5e rules.
        </DrawerDescription>

        <div className="space-y-3 border-b border-void-800 p-4">
          <div className="flex gap-2">
            <Input
              placeholder="Text to explain, e.g. 2 beams"
              value={selectedText}
              onChange={(e) => setSelectedText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canAsk) ask(selectedText)
              }}
              className="flex-1"
            />
            <button
              onClick={() => ask(selectedText)}
              disabled={!canAsk}
              className="rounded-md bg-parchment px-4 py-2 text-void-900 transition-colors hover:bg-parchment/90 disabled:opacity-50"
            >
              {loading ? "…" : "Ask"}
            </button>
          </div>

          {/* Only shown while the question is still being composed. Once an answer is on
              screen the attachments describe *that* answer, so editing them would imply a
              change that has not been asked for yet. */}
          {!answer && (
            <div className="space-y-1.5">
              {attachments.length > 0 ? (
                <>
                  <p className="text-xs text-parchment/60">
                    Attached to the question:
                  </p>
                  <AttachmentChips
                    names={attachments}
                    onRemove={removeAttachment}
                  />
                </>
              ) : (
                selectedText.trim() && (
                  <p className="text-xs text-parchment/40">
                    No spell is named in this selection, so nothing is attached.
                  </p>
                )
              )}
            </div>
          )}

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="space-y-4">
              <StageProgress
                stage={stage}
                elapsed={elapsed}
                // No estimate: unlike a book, a contextual answer has no recorded runs to
                // learn one from, and a made-up number would be worse than none.
                estimate={null}
                stages={CONTEXT_STAGES}
                labels={CONTEXT_STAGE_LABELS}
              />
            </div>
          )}

          {!loading && answer && (
            <div className="space-y-3">
              {/* The provenance badge is the point of this panel: a `rules` answer is
                  quoted from the SRD and a `rules-inferred` one is the model's reading of
                  related text. Showing the second as the first is the failure the badge
                  exists to prevent. */}
              <SourceBadge source={answer.source} field={answer.field_name} />
              <Markdown text={answer.answer} className="prose-spell" />
              {answer.attachments.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs text-parchment/40">Documents read:</p>
                  <AttachmentChips
                    names={answer.attachments}
                    removable={false}
                  />
                </div>
              )}
              {answer.citations.length > 0 && (
                <p className="text-xs text-parchment/40">
                  {answer.from_cache ? "Cached · " : ""}
                  {answer.citations.map((citation) => (
                    <span key={citation}>{citation}</span>
                  ))}
                </p>
              )}
            </div>
          )}

          {!loading && !answer && (
            <p className="text-center text-parchment/60">
              Select text in a book and click the button to get an explanation.
              Any spell the selection names is attached automatically.
            </p>
          )}
        </div>

        <div className="border-t border-void-800 p-3">
          <DrawerClose
            onClick={() => setOpen(false)}
            className="flex w-full items-center justify-center gap-2 rounded-md py-2 text-sm text-parchment/60 transition-colors hover:bg-void-800 hover:text-parchment"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
            Close
          </DrawerClose>
        </div>
      </DrawerContent>
    </Drawer>
  )
}
