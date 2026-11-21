import { Markdown } from "@/components/Markdown"

/** Show an incremental model draft while its final, validated payload is still in flight. */
export function StreamingPreview({ text }: { text: string }) {
  if (!text) return null

  return (
    <div className="space-y-2 border-l-2 border-arcane-500/40 pl-3">
      <p className="text-xs text-parchment/50">Live response</p>
      <Markdown text={text} className="prose-spell" />
    </div>
  )
}
