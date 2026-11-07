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
import { AskBox } from "@/components/AskBox"
import { AttachmentChips } from "@/components/AttachmentChips"
import { IndexHitsPanel } from "@/components/IndexHits"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { RulePathLink } from "@/components/RulePathLink"
import { StageProgress } from "@/components/StageProgress"
import { api } from "@/api/client"
import type { Answer, SearchResult } from "@/api/types"
import { CONTEXT_STAGES, CONTEXT_STAGE_LABELS } from "@/api/types"
import { RulesContext, useRulesContext } from "@/lib/rulesContext"
import { extractSpellNames, useSpellNames } from "@/lib/spellNames"
import { TYPING_DEBOUNCE_MS } from "@/lib/timing"
import { useDebouncedCallback } from "@/lib/useDebounced"

/** How long each stage is assumed to take, so the list advances on a run with no progress. */
const STAGE_AFTER_MS = [400, 900, 1500]

/**
 * How many index hits the drawer lists.
 *
 * The same budget the Rules tab's lane uses, and for the same reason: this panel sits over
 * the book being read, so a dozen candidates is a glance rather than a browse.
 */
const SEARCH_LIMIT = 12

/**
 * The contextual menu: select prose from a book, and it opens itself on what the words
 * retrieve; press Ask to have them explained.
 *
 * The two readings are deliberately different acts. The vector search costs no model call,
 * so it runs the moment the highlight settles and gives the reader the raw material
 * immediately. The answer is generated, so it waits for a click - and when it arrives it is
 * pushed in *above* the search, so the same panel reads top-down as answer-then-evidence.
 *
 * Three things make this panel worth more than a text field and an answer. It shows the
 * **documents** the question will carry - the spells the selection names are attached by
 * name, and can be removed - it shows the **stages** while the answer is being assembled,
 * because the work takes seconds and a reader who sees nothing has no way to tell a slow
 * model from a stuck one, and it shows the **index search**, so a selection that retrieved
 * nothing says so before a question is spent on it.
 */
export function RulesContextDrawerProvider({
  children,
}: {
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [selectedText, setSelectedTextState] = useState("")
  // The prose the selection sat in. Held because the selection is read in one gesture and
  // asked about in a later one: the sentence is what makes "2 beams" mean the Eldritch Blast
  // beams, and by the time Ask is clicked the DOM selection is long gone.
  const [selectionContext, setSelectionContext] = useState("")
  const [attachments, setAttachments] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [stage, setStage] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState<SearchResult | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  // The selection conversation. Held so a follow-up is read in context, and so the
  // exchange can be found again on the Chats screen.
  const [threadId, setThreadId] = useState<string | null>(null)
  const started = useRef(0)
  // The text the current attachments were derived from. Without it, editing the question and
  // asking again reuses the previous answer's documents - which no longer match the words on
  // screen, and would attach a spell the new text never named.
  const attachedFor = useRef("")
  // Which selection the in-flight index search belongs to. A reply that lands after a newer
  // selection is discarded rather than rendered, because the alternative is a panel showing
  // hits for words the reader has already replaced - which looks current and is wrong.
  const latestSearch = useRef(0)
  // The same guard for the answer, which is the slower of the two requests and so the one
  // most likely to arrive late. Without it, selecting new words while an answer is in flight
  // would clear the panel on `explore` and then have the old answer drop back into it, above
  // the new hits and under a badge claiming provenance for words that are no longer there.
  const latestAsk = useRef(0)
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

  /**
   * Search the index for the selection, without asking anything.
   *
   * `doc_type: "all"` because a selection is as likely to be a rule as a spell - "2 beams"
   * sits beside a rule about cantrip upgrades, and a fragment copied out of a book can name
   * either. Restricting this to spells is how the equivalent lane on the Rules tab came to
   * answer a question about cover with eleven spells and never the Cover rule.
   *
   * A failure here is reported beside the hits rather than thrown: the panel's other half is
   * still useful, and an index that cannot be reached must not stop the reader asking.
   */
  const searchIndex = useCallback(async (text: string) => {
    const query = text.trim()
    const run = ++latestSearch.current
    if (!query) {
      setSearch(null)
      setSearching(false)
      setSearchError(null)
      return
    }
    setSearching(true)
    setSearchError(null)
    try {
      const found = await api.search({
        query,
        mode: "vector",
        limit: SEARCH_LIMIT,
        doc_type: "all",
      })
      if (run !== latestSearch.current) return
      setSearch(found)
    } catch (err) {
      if (run !== latestSearch.current) return
      setSearch(null)
      setSearchError(err instanceof Error ? err.message : String(err))
    } finally {
      if (run === latestSearch.current) setSearching(false)
    }
  }, [])

  /**
   * The input's own debounced index search.
   *
   * The box is editable, and the cards below it are the index's reading of what it says - so
   * editing the words has to update them. Debounced because a sentence typed at speed would
   * otherwise issue a request per keystroke and leave several responses racing to fill one
   * list; `TYPING_DEBOUNCE_MS` is shared with the Rules tab's box so the two feel alike.
   */
  const {
    call: searchOnType,
    cancel: cancelTypedSearch,
    pending: typingSearchPending,
  } = useDebouncedCallback(searchIndex, TYPING_DEBOUNCE_MS)

  /**
   * Open the drawer on a selection and search the index for it.
   *
   * The answer from a *previous* selection is dropped here rather than kept on screen. It
   * was written for other words, and leaving it above the new hits would read as the answer
   * to the new selection - the one thing this panel must never do, since the badge that
   * says whether an answer is quoted or interpreted is attached to text the reader can no
   * longer see the question for.
   */
  const explore = useCallback(
    (text: string, context?: string, documents?: string[]) => {
      const question = text.trim()
      if (!question) return

      const derived = documents ?? mentionsIn(question)
      setSelectedTextState(question)
      setSelectionContext(context ?? "")
      attachedFor.current = question
      setAttachments(derived)
      setOpen(true)
      // The answer state is cleared but `threadId` is not: a follow-up still belongs to the
      // same conversation, and the backend reads it for context.
      setAnswer(null)
      setError(null)
      setLoading(false)
      // Claimed here so any answer already in flight for the previous selection is
      // recognised as stale when it lands, rather than dropping in above these hits.
      latestAsk.current += 1
      // A selection supersedes anything the box had scheduled. Without this, words typed
      // just before the reader selected something would fire a moment later and overwrite
      // the hits for the new selection - two searches for one panel, and the loser is the
      // one the reader actually asked for.
      cancelTypedSearch()
      void searchIndex(question)
    },
    [mentionsIn, searchIndex, cancelTypedSearch],
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

      setSelectedTextState(question)
      attachedFor.current = question
      setAttachments(derived)
      setOpen(true)
      setLoading(true)
      setStage(0)
      setElapsed(0)
      started.current = performance.now()
      setError(null)
      setAnswer(null)
      const run = ++latestAsk.current
      try {
        const result = await api.rulesContextual(
          question,
          context,
          derived,
          threadId ?? undefined,
        )
        if (run !== latestAsk.current) return
        setAnswer(result)
        setThreadId(result.thread_id)
      } catch (err) {
        if (run !== latestAsk.current) return
        setError(
          err instanceof Error
            ? err.message
            : "Could not reach the rules lookup.",
        )
      } finally {
        // A superseded run must not clear the newer one's spinner.
        if (run === latestAsk.current) {
          setLoading(false)
          setStage(CONTEXT_STAGES.length)
        }
      }
    },
    [attachments, mentionsIn, threadId],
  )

  const remove = useCallback((name: string) => {
    setAttachments((current) => current.filter((item) => item !== name))
  }, [])

  /**
   * Editing the question drops the selection's sentence, re-derives its documents, and
   * schedules the index search.
   *
   * The sentence explains *those* words. Once the reader has changed them it describes
   * something else, and passing it along would have the model read the new question in the
   * context of the old one - a mismatch nothing downstream can detect, because the prompt is
   * the only place the two are compared.
   *
   * The documents are re-derived here for the same reason, and it is what `ask` would do
   * anyway: it keeps an edited list only while the words are unchanged. Showing the old
   * chips beside cards for the new words would advertise an attachment the question is not
   * going to carry.
   *
   * The search is *scheduled* rather than awaited here, so the cards follow the typing
   * without a request per keystroke. An emptied box clears the list immediately instead of
   * after the wait: there is nothing to look up, and a panel still showing hits for words
   * that are gone is worse than an empty one.
   *
   * A generated answer is dropped rather than kept, and no request is made for it. It was
   * written for the previous words, and the badge on it is a claim about *those* words - so
   * leaving it under a box that now says something else would put a provenance claim above
   * text the reader cannot see the question for. The in-flight run is invalidated the same
   * way `explore` does it, so an answer already on its way is discarded rather than landing
   * on words it does not describe. Pressing Ask is what spends a model call, and editing is
   * not that.
   */
  const setSelectedText = useCallback(
    (text: string) => {
      setSelectedTextState(text)
      setSelectionContext("")
      attachedFor.current = text.trim()
      setAttachments(mentionsIn(text))
      setAnswer(null)
      setError(null)
      setLoading(false)
      latestAsk.current += 1
      if (text.trim()) {
        searchOnType(text)
      } else {
        cancelTypedSearch()
        void searchIndex("")
      }
    },
    [mentionsIn, searchIndex, searchOnType, cancelTypedSearch],
  )

  /** Ask about what is currently selected, with the sentence it was selected from. */
  const askSelection = useCallback(() => {
    void ask(selectedText, selectionContext || undefined)
  }, [ask, selectedText, selectionContext])

  return (
    <RulesContext.Provider
      value={{
        open,
        setOpen,
        selectedText,
        setSelectedText,
        ask,
        askSelection,
        explore,
        loading,
        answer,
        error,
        search,
        searching: searching || typingSearchPending,
        searchError,
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
    askSelection,
    loading,
    answer,
    error,
    search,
    searching,
    searchError,
    attachments,
    removeAttachment,
  } = useRulesContext()

  // Asking twice with the same words and the same documents is the same question, so the
  // box reuses the snapshot the attachments were last derived from rather than re-deriving
  // them: a reader who removed a spell keeps it removed while they edit the wording.
  //
  // Only the "nothing to ask about" half is passed on: `AskBox` already refuses while a
  // question is in flight, and stating it twice would be two places to keep in step.
  const canAsk = selectedText.trim().length > 0

  return (
    <Drawer open={open} onOpenChange={setOpen} swipeDirection="right">
      <DrawerContent>
        <DrawerTitle className="sr-only">Rules Context</DrawerTitle>
        <DrawerDescription className="sr-only">
          The selected text, the index hits it retrieves, and an explanation of it in the
          context of D&amp;D 5.5e rules.
        </DrawerDescription>

        <div className="space-y-3 border-b border-void-800 p-4">
          {/* The same box the Rules tab uses, so the one action that costs a model call looks
              and behaves the same wherever it is offered. The drawer's own difference is what
              the text *is* - a selection, with the sentence it came from - and that is the
              caller's business, not the box's. */}
          <AskBox
            value={selectedText}
            onChange={setSelectedText}
            onAsk={askSelection}
            loading={loading}
            disabled={!canAsk}
            placeholder="Text to explain, e.g. 2 beams"
          />

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
                  <p className="text-xs text-parchment/60">
                    No spell is named in this text, so nothing is attached.
                  </p>
                )
              )}
            </div>
          )}

          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {/* The answer first, because it is what was asked for. It is pushed in above the
              search results rather than replacing them: the hits are the evidence the
              answer was drawn from, and a reader checking a claim needs both on screen at
              once. */}
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
                  <p className="text-xs text-parchment/60">Documents read:</p>
                  <AttachmentChips
                    names={answer.attachments}
                    removable={false}
                  />
                </div>
              )}
              {answer.citations.length > 0 && (
                <div className="space-y-1 border-t border-void-800 pt-2">
                  {answer.from_cache && (
                    <p className="text-xs text-parchment/60">Cached</p>
                  )}
                  {answer.citations.map((citation) => (
                    <p key={citation} className="truncate">
                      <RulePathLink path={citation} />
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* The index's own reading, which is the part that needs no model and is
              therefore already on screen while the answer is still being written. It is
              rendered by the same component the Rules tab's column uses, so a hit read
              beside a book cannot disagree with the same hit read beside a rule - same
              card, same one list in the API's order, same preview line, same match dial,
              same interaction. */}
          {(searching || search !== null || searchError !== null) && (
            <div className="border-t border-void-800 pt-3">
              <IndexHitsPanel
                result={search}
                searching={searching}
                error={searchError}
              />
            </div>
          )}

          {!loading && !answer && !searching && search === null && (
            <p className="text-center text-parchment/60">
              Select text in a book to see what it retrieves, or type in the
              box above — the cards follow what you write. Press Ask to have it
              explained. Any spell the selection names is attached
              automatically.
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
