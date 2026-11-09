import { useSearchParams } from "react-router-dom"

import { HistoryConversations } from "@/screens/HistoryConversations"
import { HistoryScenarios } from "@/screens/HistoryScenarios"
import { cn } from "@/lib/utils"
import { MessageCircleIcon, WaypointsIcon } from "lucide-react"

/** The two things a stored run can be: a generated scenario, or an ask/chat thread. */
const TABS = [
  { value: "scenarios", label: "Scenarios", icon: WaypointsIcon },
  { value: "conversations", label: "Conversations", icon: MessageCircleIcon },
] as const

type Tab = (typeof TABS)[number]["value"]

/**
 * Everything the tool has stored, under one heading.
 *
 * Scenarios and conversations were separate top-level tabs, but they answer the same
 * question - "what have I already done?" - and a reader looking for a past answer does
 * not know in advance which of the two it was. They are subtabs here rather than a
 * merged list because the two are read differently: a scenario is re-opened to rate it,
 * a conversation to re-read an answer.
 *
 * The active subtab lives in the URL so it survives a reload and can be linked to.
 */
export function HistoryScreen() {
  const [params, setParams] = useSearchParams()
  const requested = params.get("tab")
  const tab: Tab = TABS.some((item) => item.value === requested)
    ? (requested as Tab)
    : "scenarios"

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-parchment">History</h2>
        <div className="flex gap-1">
          {TABS.map((item) => (
            <button
              key={item.value}
              onClick={() => setParams({ tab: item.value }, { replace: true })}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm transition-colors",
                "flex gap-1 items-center justify-center",
                tab === item.value
                  ? "bg-void-800 text-parchment"
                  : "text-parchment/60 hover:text-parchment",
              )}
            >
              <item.icon className="h-4 w-4" />
              <span className="ml-2">{item.label}</span>
            </button>
          ))}
        </div>
      </div>

      {tab === "scenarios" ? <HistoryScenarios /> : <HistoryConversations />}
    </div>
  )
}
