import { Loader2, WandSparkles, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/**
 * The one box that asks a question, used by the Rules tab and by the contextual drawer.
 *
 * Both surfaces had their own: the Rules tab an `Input` beside a rounded verdant `Button`, the
 * drawer an `Input` beside a parchment `<button>`. They differed in the button's shape, its
 * colour, its icon and its disabled rule - so the same act looked like two different acts
 * depending on which panel you were in, and a change to one silently left the other behind.
 *
 * What is shared is the *shape* of the control, not the behaviour: the caller owns the text,
 * what typing does, and what asking does. That is deliberate, because the two surfaces really
 * do differ there - the Rules tab searches as you type and asks on the button, while the drawer
 * searches as you type and asks on the button with a sentence attached - and a component that
 * tried to own both would need a flag per difference.
 *
 * Three details are the component's own, because they are what "the same box" means:
 *
 * - **The clear button lives inside the field**, not beside Ask. It acts on the text rather
 *   than on the question, so it belongs where the text is, and it appears only when there is
 *   text to clear so an empty box has no dead control next to it.
 * - **Escape clears and Enter asks.** Both are the same acts the visible controls perform, so
 *   neither needs a trip to the mouse. Enter is a shortcut rather than the only way in: it
 *   skips the wait the debounce would have imposed, which is what a reader who has finished
 *   typing and hit enter is asking for.
 * - **The button is disabled while there is nothing to ask**, and shows a spinner while a
 *   question is in flight, so the one control that costs a model call says when it is spending
 *   one.
 */
export function AskBox({
  value,
  onChange,
  onAsk,
  placeholder,
  loading = false,
  disabled = false,
  className,
}: {
  value: string
  onChange: (text: string) => void
  /** Ask about the current text. Called by the button and by Enter. */
  onAsk: () => void
  placeholder?: string
  /** A question is in flight: the button spins and cannot be pressed again. */
  loading?: boolean
  /** Nothing to ask about, or the caller is not ready. */
  disabled?: boolean
  className?: string
}) {
  const canAsk = value.trim().length > 0 && !loading && !disabled

  return (
    <div className={cn("flex gap-2", className)}>
      <div className="relative min-w-0 flex-1">
        <Input
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && canAsk) onAsk()
            // Escape clears, which is what the button does - the same act should not need a
            // trip to the mouse.
            if (event.key === "Escape") onChange("")
          }}
          className={value ? "pr-8" : undefined}
        />
        {value !== "" && (
          <button
            type="button"
            onClick={() => onChange("")}
            aria-label="Clear"
            title="Clear"
            className="absolute top-1/2 right-1 -translate-y-1/2 rounded p-1 text-parchment/40 hover:bg-void-800 hover:text-parchment"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {/* The one action that costs a model call, so it is the one control labelled with what
          it does rather than with what the panel is. The wand is the same glyph the
          "interpreted" badge uses, which is the honest hint that what comes back is a reading
          and not always a quotation. */}
      <Button
        onClick={() => onAsk()}
        disabled={!canAsk}
        aria-label="Ask"
        title="Ask the 2024 SRD"
        className="shrink-0 rounded-full bg-verdant-400 whitespace-nowrap text-void-900"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <WandSparkles className="h-4 w-4" />
        )}
        <span className="hidden sm:inline">Ask</span>
      </Button>
    </div>
  )
}
