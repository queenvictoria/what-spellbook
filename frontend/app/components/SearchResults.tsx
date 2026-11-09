import { useState } from "react"

import type { SearchHit, SearchResult } from "@/api/types"
import { ErrorNotice } from "@/components/ErrorNotice"
import { MatchDial } from "@/components/MatchDial"
import { SpellCard } from "@/components/SpellCard"
import { RulePathLink } from "@/components/RulePathLink"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useSpell } from "@/lib/useSpell"

/** What one document of each kind is called, for the summary line. */
const DOC_TYPE_NOUNS: Record<string, string> = {
  all: "document",
  spell: "spell",
  item: "item",
  srd: "rule",
}

/**
 * The vector search's results, in the shape both the Search tab and the Rules tab show.
 *
 * Lifted out of `SearchScreen` when the Rules tab's ask box grew a search lane of its own.
 * Two copies of this would have been two readings of the same response - the Rules tab is
 * the one building the request, so if it disagreed about what `distance` means or about
 * which count is the honest summary, the disagreement would be invisible: both panels would
 * look right on their own. One component, two callers.
 *
 * The props are deliberately the response itself rather than a list of hits. `note` and
 * `where` are how a search that returned nothing explains itself, so a caller that passed
 * only `hits` would lose the explanation - which is the commonest thing to need here.
 */
export function SearchResults({
  result,
  emptyMessage = "Nothing matched. Try a different mode or fewer filters.",
}: {
  result: SearchResult
  /** Shown when the search returned nothing and had no `note` of its own. */
  emptyMessage?: string
}) {
  const [open, setOpen] = useState<string | null>(null)

  return (
    <div className="space-y-3">
      <SearchSummary result={result} />
      {result.hits.map((hit) => (
        <SearchHitRow
          key={hit.filename + hit.name}
          hit={hit}
          open={open === hit.name}
          onToggle={() => setOpen(open === hit.name ? null : hit.name)}
        />
      ))}
      {result.hits.length === 0 && (
        <p className="text-sm text-parchment/60">
          {/* The note is already shown above when there is one, so repeating it here would
              say the same sentence twice. */}
          {result.note ? "Nothing matched." : emptyMessage}
        </p>
      )}
    </div>
  )
}

/**
 * What the search did, in one line.
 *
 * `total_matching` is the number of distinct documents the *criteria* admit, which is the
 * number that says whether a filter is too narrow. It is deliberately not called "results":
 * a vector search has no relevance threshold, so it cannot say how many documents are
 * relevant, only how many were eligible to be ranked.
 *
 * The noun follows the doc type, because the collection holds the rulebook and the magic
 * items as well as the spells. Calling 1818 mixed documents "spells" is the same category
 * error the doc-type control exists to prevent.
 */
function SearchSummary({ result }: { result: SearchResult }) {
  const noun = DOC_TYPE_NOUNS[result.filters.doc_type ?? "all"]
  return (
    <div className="space-y-2 text-xs text-parchment/55">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="muted">{result.mode}</Badge>
        <span>
          {result.hits.length} shown · {result.total_matching} {noun}
          {result.total_matching === 1 ? "" : "s"} match the criteria
        </span>
        <span className="font-mono">{result.elapsed_ms.toFixed(0)}ms</span>
      </div>
      {result.note && (
        <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
          {result.note}
        </p>
      )}
      {result.where && (
        <details>
          <summary className="cursor-pointer text-parchment/45 hover:text-parchment/70">
            Filter clause sent to Chroma
          </summary>
          <pre className="mt-1 overflow-x-auto rounded-md bg-void-950/70 p-2 font-mono text-[0.7rem] text-parchment/60">
            {JSON.stringify(result.where, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}

/**
 * One hit, expandable into the full spell card.
 *
 * The card is the same one the Rules tab and the drawer render, so a spell read here cannot
 * disagree with a spell read anywhere else. It is fetched by name rather than taken from the
 * hit's own text, because the hit's text is one *chunk* — the card shows the whole spell.
 *
 * An SRD hit takes a different path entirely: it is a *rule*, not a spell, so there is
 * nothing to fetch by name and the spell card would 404. It links to the section instead,
 * which is the same affordance every other rule in the app has.
 */
function SearchHitRow({
  hit,
  open,
  onToggle,
}: {
  hit: SearchHit
  open: boolean
  onToggle: () => void
}) {
  const isRule = hit.doc_type === "srd"
  const { spell, missing, error } = useSpell(open && !isRule ? hit.name : null)

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <button onClick={onToggle} className="text-left">
          <CardTitle className="text-sm">{hit.name}</CardTitle>
          <p className="mt-0.5 text-xs text-parchment/50">
            {isRule ? (
              <>
                Rule
                {hit.document ? ` · ${hit.document}` : ""}
              </>
            ) : (
              <>
                {hit.level_label}
                {hit.school ? ` · ${hit.school}` : ""}
                {hit.ritual ? " · Ritual" : ""}
                {!hit.is_spell ? " · Not a spell" : ""}
              </>
            )}
          </p>
        </button>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {hit.distance !== null && (
            <MatchDial distance={hit.distance} size={30} />
          )}
          <span className="text-[0.7rem] text-parchment/40">
            {hit.chunks} chunk{hit.chunks === 1 ? "" : "s"}
            {hit.terms_matched > 0 ? ` · ${hit.terms_matched} term(s)` : ""}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {hit.classes.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {hit.classes.map((name) => (
              <Badge key={name} tone="muted">
                {name}
              </Badge>
            ))}
          </div>
        )}
        {open ? (
          <>
            {isRule && hit.document && hit.slug && (
              <RulePathLink path={`context/srd/${hit.document}.md`} />
            )}
            {spell && <SpellCard spell={spell} />}
            {missing && (
              <p className="text-xs text-parchment/60">
                {missing} The chunk below is what the index matched.
              </p>
            )}
            {error != null && <ErrorNotice error={error} compact />}
            {!spell && !missing && !error && !isRule && (
              <p className="text-xs text-parchment/50">Loading…</p>
            )}
            {isRule && (
              <p className="whitespace-pre-wrap text-xs text-parchment/70">{hit.text}</p>
            )}
          </>
        ) : (
          <p className="line-clamp-3 whitespace-pre-wrap text-xs text-parchment/60">
            {hit.text}
          </p>
        )}
        <p className="font-mono text-[0.7rem] text-parchment/35">{hit.filename}</p>
      </CardContent>
    </Card>
  )
}
