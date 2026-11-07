import { useEffect, useState } from "react"
import { ChevronDown, ChevronRight, MessageSquare } from "lucide-react"

import { api, ApiError } from "@/api/client"
import type { Conversation, ConversationKind, ConversationSummary } from "@/api/types"
import { AttachmentChips } from "@/components/AttachmentChips"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { SrdPathLink } from "@/components/SrdPathLink"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/** The surfaces a conversation can come from, and what each one is. */
const KINDS: { value: ConversationKind; label: string }[] = [
  { value: "rules", label: "Rules" },
  { value: "character", label: "Character" },
  { value: "selection", label: "Selection" },
  { value: "refine", label: "Refine" },
]

/**
 * Every stored ask/chat conversation, newest first.
 *
 * Listed as threads rather than answers: a follow-up is only meaningful beside the
 * question it followed — "and a grapple?" is not a question on its own. Opening one shows
 * the whole exchange, with each answer's provenance, so a past answer can be re-read
 * rather than asked again.
 */
export function ChatsScreen() {
  // The listing is fetched into state keyed by the filter it was fetched for, and the
  // render reads it only when the key still matches. That keeps the effect free of
  // synchronous setState - which would cascade a second render on every filter change -
  // while still showing "Loading…" the moment the filter changes.
  const [loaded, setLoaded] = useState<{
    kind: ConversationKind | null
    threads: ConversationSummary[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<ConversationKind | null>(null)
  // Which thread is open lives here rather than inside each card, because the card's own
  // width depends on it: an open thread takes the full row, and a child cannot widen its
  // parent. Only one is open at a time, which also keeps the listing scannable.
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .conversations(kind ?? undefined)
      .then((threads) => {
        if (!cancelled) setLoaded({ kind, threads })
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [kind])

  const threads = loaded && loaded.kind === kind ? loaded.threads : null

  if (error) {
    return <p className="text-sm text-red-300">{error}</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-parchment">Conversations</h2>
        <div className="flex flex-wrap gap-1">
          <FilterButton active={kind === null} onClick={() => setKind(null)}>
            All
          </FilterButton>
          {KINDS.map((item) => (
            <FilterButton
              key={item.value}
              active={kind === item.value}
              onClick={() => setKind(item.value)}
            >
              {item.label}
            </FilterButton>
          ))}
        </div>
      </div>

      {threads === null && (
        <p className="text-sm text-parchment/60">Loading…</p>
      )}

      {threads?.length === 0 && (
        <p className="text-sm text-parchment/60">
          Nothing has been asked yet. Ask a rule on the Rules screen, or a question about
          your character, and the exchange will appear here.
        </p>
      )}

      {/* Flex rather than a grid: an opened thread needs to take the full width, and a
          grid cell cannot span its own row without knowing the column count. */}
      <div className="flex flex-wrap gap-3">
        {threads?.map((thread) => (
          <Card
            key={thread.id}
            className={cn(
              "w-full",
              openId !== thread.id && "sm:w-[calc(50%-0.375rem)]",
            )}
          >
            <CardHeader className="flex-row items-start justify-between gap-3">
              <CardTitle className="text-sm leading-6">{thread.opening}</CardTitle>
              <Badge tone="muted">{kindLabel(thread.kind)}</Badge>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-parchment/55">
              <div className="flex items-center justify-between font-mono">
                <span>{formatDate(thread.updated_at)}</span>
                <span>
                  {thread.turn_count} turn{thread.turn_count === 1 ? "" : "s"}
                </span>
              </div>
              <ViewThread
                thread={thread}
                open={openId === thread.id}
                onToggle={() => setOpenId(openId === thread.id ? null : thread.id)}
              />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}

/**
 * Re-opens the stored thread in place, so reading does not lose the listing.
 *
 * `open` is owned by the list because it drives the card's width; this component only
 * fetches the turns and reports the toggle.
 */
function ViewThread({
  thread,
  open,
  onToggle,
}: {
  thread: ConversationSummary
  open: boolean
  onToggle: () => void
}) {
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function toggle() {
    if (open) {
      onToggle()
      return
    }
    setLoading(true)
    setError(null)
    try {
      setConversation(await api.conversation(thread.id))
      onToggle()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="pt-1">
      <div className="flex gap-2 justify-between">
        <Button variant="outline" size="sm" onClick={toggle} disabled={loading}>
          {open ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
          {open ? "Hide turns" : "Read conversation"}
        </Button>
        {error && <p className="pt-1 text-red-300">{error}</p>}
      </div>
      {open && conversation && (
        <div className="mt-3 space-y-3 border-t border-void-800 pt-3">
          {conversation.turns.map((turn, i) => (
            <div key={i} className="space-y-2">
              <p className="flex items-start gap-2 text-sm text-parchment/90">
                <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-parchment/40" />
                {turn.question}
              </p>
              <div className="space-y-2 border-l border-void-800 pl-3">
                <SourceBadge source={turn.source} field={turn.field_name} />
                <Markdown text={turn.answer} className="prose-spell" />
                <AttachmentChips names={turn.attachments} removable={false} />
                {turn.citations.length > 0 && (
                  <div className="space-y-1">
                    {turn.citations.map((path) => (
                      <p key={path} className="truncate">
                        <SrdPathLink path={path} />
                      </p>
                    ))}
                  </div>
                )}
                {turn.from_cache && (
                  <p className="text-xs text-parchment/45">Answered from cache.</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-[0.7rem] transition-colors",
        active
          ? "border-arcane-500/50 bg-arcane-500/15 text-arcane-200"
          : "border-void-700 text-parchment/60 hover:text-parchment",
      )}
    >
      {children}
    </button>
  )
}

function kindLabel(kind: ConversationKind) {
  return KINDS.find((item) => item.value === kind)?.label ?? kind
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
