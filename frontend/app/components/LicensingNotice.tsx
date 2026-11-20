import { Scale } from "lucide-react"

import { presentSources, useLicensing } from "@/lib/licensing"
import { cn } from "@/lib/utils"

/**
 * The third-party attributions this app owes, as a footer.
 *
 * CC-BY-4.0 requires the notice to travel with the work, and "the work" here is the app —
 * the SRD text is vendored into the repository and quoted all over the Rules tab. A notice
 * that only lived in `context/srd/PROVENANCE.md` would be a notice the reader of the app
 * never sees, which is the gap this closes.
 *
 * Only sources whose content is *installed* are rendered. The optional rulebook is fetched
 * and read in place, so a checkout without it owes nothing, and printing its attribution
 * anyway would be a claim about a redistribution that never happened. The backend decides
 * that per source and sends `present`; this component does not second-guess it.
 *
 * A failure renders nothing. The list is static text served by the backend, so a failure
 * means the API is not running — and a licensing notice that cannot be fetched is not a
 * reason to block the app. The long-form records remain in `context/*.PROVENANCE.md`.
 */
export function LicensingNotice({ className }: { className?: string }) {
  const { sources } = useLicensing()
  const present = presentSources(sources)
  if (present.length === 0) return null

  return (
    <footer className="border-t border-void-800/60 pt-4">
      <div
        className={cn(
          "flex gap-2 mx-auto max-w-6xl px-6 pb-16",
          " text-xs leading-relaxed text-parchment/40 sm:pb-8",
          className,
        )}
      >
        <Scale className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <div className="space-y-2">
          {present.map((source) => (
            <p key={source.key}>
              {source.attribution}{" "}
              <a
                href={source.licence_url}
                target="_blank"
                rel="noreferrer noopener"
                className="underline decoration-dotted underline-offset-2 hover:text-parchment/70"
              >
                {source.licence}
              </a>
              {" · "}
              <a
                href={source.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="underline decoration-dotted underline-offset-2 hover:text-parchment/70"
              >
                Source
              </a>
            </p>
          ))}
        </div>
      </div>
    </footer>
  )
}
