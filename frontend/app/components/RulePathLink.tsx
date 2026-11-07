import { BookOpen } from "lucide-react"

import { useOpenRule, ruleInPath } from "@/lib/ruleDrawer"
import { cn } from "@/lib/utils"

/**
 * A provenance path, clickable when it names a vendored SRD file.
 *
 * Every answer in this app ends with the file it came from, and until now that path was
 * dead text: a reader who wanted the surrounding rule had to go to the Rules tab and find
 * the heading by hand. The drawer is the same affordance spells already have, so a rule and
 * a spell are read the same way.
 *
 * A path that is *not* SRD text - the retrieval corpus, a character sheet - stays plain
 * text rather than becoming a link that cannot open. That distinction is the whole reason
 * `ruleInPath` exists: a link that fails is worse than no link, because it looks like the
 * rule is missing rather than like the path is not a rule.
 */
export function RulePathLink({
  path,
  className,
}: {
  path: string
  className?: string
}) {
  const open = useOpenRule()
  const target = ruleInPath(path)

  if (!target) {
    return (
      <span className={cn("font-mono text-xs text-parchment/60", className)}>
        {path}
      </span>
    )
  }

  return (
    <a
      href={`/rules?doc=${encodeURIComponent(target.document)}${
        target.slug ? `&section=${encodeURIComponent(target.slug)}` : ""
      }`}
      onClick={(event) => {
        // Only a plain left click is ours. A modified click is how a reader opens the Rules
        // tab in a new tab, and swallowing it would take away the one thing the href is
        // there for.
        if (
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return
        event.preventDefault()
        open(target)
      }}
      title="Read this rule"
      className={cn(
        "inline-flex items-center gap-1 rounded font-mono text-xs text-parchment/60",
        "underline decoration-dotted underline-offset-2 transition-colors",
        "hover:text-arcane-300 hover:decoration-arcane-400",
        className,
      )}
    >
      <BookOpen className="h-3 w-3 shrink-0" />
      {path}
    </a>
  )
}
