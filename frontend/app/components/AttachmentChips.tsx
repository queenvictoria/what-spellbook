import { FileText, X } from "lucide-react"

/**
 * The documents riding along with a question, as removable lozenges.
 *
 * This is the UI half of "attach these documents to the context": what the model will be
 * given is shown, and anything it should not be given can be taken off. That matters more
 * here than it would elsewhere, because a missing document is *invisible* in the answer -
 * "the retrieved SRD text does not cover Thorn Whip" looks like a rule the SRD lacks until
 * the reader can see that Thorn Whip was never attached.
 */
export function AttachmentChips({
  names,
  onRemove,
  removable = true,
}: {
  names: string[]
  onRemove?: (name: string) => void
  removable?: boolean
}) {
  if (names.length === 0) return null

  return (
    <ul className="flex flex-wrap gap-1.5">
      {names.map((name) => (
        <li
          key={name}
          className="inline-flex items-center gap-1.5 rounded-full border border-arcane-500/30 bg-arcane-500/10 py-1 pl-2 pr-1 text-xs text-arcane-200"
        >
          <FileText className="h-3 w-3 shrink-0" />
          <span>{name}</span>
          {removable && onRemove && (
            <button
              type="button"
              onClick={() => onRemove(name)}
              // The lozenge is one object, so the label names it rather than saying
              // "remove" on a screen where several of these may be present.
              aria-label={`Remove ${name} from the context`}
              className="rounded-full p-0.5 text-arcane-300/70 transition-colors hover:bg-arcane-500/20 hover:text-arcane-100"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}
