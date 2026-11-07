import { useRef } from "react"
import { Loader2, Search } from "lucide-react"

import type { SearchHit, SearchResult } from "@/api/types"
import { MatchDial } from "@/components/MatchDial"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { shouldDeferToBrowser, useOpenSpell } from "@/lib/spellDrawer"
import { srdHref } from "@/lib/srd"
import { useOpenRule } from "@/lib/ruleDrawer"

/**
 * The index's own reading of a query, as a titled card.
 *
 * Lifted out of the Rules tab's `IndexColumn` when the contextual drawer grew the same list,
 * for the reason `SearchResults` was lifted out of `SearchScreen`: two copies would be two
 * readings of one response, and the disagreement would be invisible - each panel would look
 * right on its own. One component, two callers.
 *
 * What it shows is a **similarity search over chunk bodies**, not the recommender. It can
 * name a spell the character could never prepare, on purpose: a spell missing from a
 * recommendation is explained here, and that explanation requires seeing what the index
 * actually holds.
 *
 * **One list, in the API's order.** The rulebook shares the collection, so a question like
 * "how does cover work" is answered by the Cover rule as well as by spells that mention cover.
 * Those used to be listed as two groups, rules first, which read as two searches - and the
 * reader had to compare a rule's dial against a spell's across a heading to know which the
 * index actually preferred. The API already sorts by distance ascending, so the ranking is
 * shown as it is: one list, nearest first, whatever kind each hit happens to be.
 *
 * **One row component for both kinds.** A rule and a spell differ in exactly two things - the
 * address they open and the label in the trailing slot - and those are the only two places the
 * row branches. Everything else (the hit region, the hover state, the preview line, the dial)
 * is shared, because a reader comparing a rule against a spell is comparing two rows of one
 * list and any difference in how they respond to the pointer reads as a bug rather than as a
 * distinction.
 */
export function IndexHitsCard({ result }: { result: SearchResult }) {
  const hits = result.hits

  return (
    <div className="space-y-2">
      <p className="text-[0.7rem] text-parchment/45">
        {hits.length} shown · {result.total_matching} document
        {result.total_matching === 1 ? "" : "s"} match ·{" "}
        <span className="font-mono">{result.elapsed_ms.toFixed(0)}ms</span>
      </p>
      {result.note && (
        <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-[0.7rem] text-radiant-400">
          {result.note}
        </p>
      )}
      {hits.length === 0 && (
        <p className="text-sm text-parchment/60">
          No chunk is close to that description. The Search tab has text and
          hybrid modes, which fail differently.
        </p>
      )}

      {hits.length > 0 && (
        <ul className="max-h-[16rem] space-y-1.5 overflow-y-auto pr-1">
          {hits.map((hit) => (
            <IndexHitRow key={hitKey(hit)} hit={hit} />
          ))}
        </ul>
      )}

      <p className="text-[0.7rem] text-parchment/40">
        A similarity search over chunk bodies, not the recommender. It can name a
        spell this character could never prepare, on purpose.
      </p>
    </div>
  )
}

/** The card itself, for the two screens that show it as a column. */
export function IndexHitsPanel({
  result,
  searching,
  error,
  className,
}: {
  result: SearchResult | null
  searching: boolean
  error: string | null
  /** Layout classes for the caller's own column or drawer width. */
  className?: string
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Search className="h-4 w-4" />
          In the index
          {searching && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-arcane-300" />
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {error && <p className="text-sm text-red-300">{error}</p>}
        {result && <IndexHitsCard result={result} />}
      </CardContent>
    </Card>
  )
}

/**
 * One hit, as a row of the list.
 *
 * The whole row is the hit region and the whole row is the hover state, for both kinds. That
 * is the point of the component: a rule used to be an `<a>` wrapping the row while a spell was
 * a `<div>` with only its name as a link, so the two had different clickable areas and
 * different hover feedback in one list - which reads as one of them being broken.
 *
 * The two branches are the address and the trailing label, and nothing else:
 *
 * - A **rule** is opened by document and slug, so it is an `<a href>` to the section. The href
 *   is real, so Ctrl+click still opens a tab and the status bar still shows where it goes; a
 *   plain left click is intercepted to open the drawer instead.
 * - A **spell** is opened by name, and `SpellLink` already owns that behaviour - including the
 *   drag detection that keeps a selection ending on a mention from navigating away. It is
 *   rendered as the row's own link rather than nested inside another one, because a link
 *   inside a link is invalid and the browser's click target becomes ambiguous.
 *
 * The label slot is the same width in both cases, so the dials line up down the column and the
 * list can be scanned by shape.
 */
function IndexHitRow({ hit }: { hit: SearchHit }) {
  const openSrd = useOpenRule()
  const openSpell = useOpenSpell()
  const isRule = hit.doc_type === "srd"
  const href = isRule
    ? hit.document
      ? srdHref(hit.document, hit.slug || null)
      : "/rules"
    : `/rules?spell=${encodeURIComponent(hit.name)}`
  // Where the pointer went down, so a click that ended a drag is left to the browser. The
  // same test `SpellLink` makes, and for the same reason: a reader dragging a selection
  // across a row must not have the row navigate out from under the highlight.
  const pressedAt = useRef<{ x: number; y: number } | null>(null)

  return (
    <li className="min-w-0">
      <a
        href={href}
        onMouseDown={(event) => {
          pressedAt.current = { x: event.clientX, y: event.clientY }
        }}
        onClick={(event) => {
          const pressed = pressedAt.current
          pressedAt.current = null
          if (
            pressed &&
            Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 4
          ) {
            event.preventDefault()
            return
          }
          if (shouldDeferToBrowser(event)) return
          event.preventDefault()
          if (isRule) {
            if (hit.document)
              openSrd({ kind: "srd", document: hit.document, slug: hit.slug || null })
          } else {
            openSpell(hit.name)
          }
        }}
        className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-void-800"
        title={
          isRule
            ? hit.document
              ? `context/srd/${hit.document}.md`
              : undefined
            : `Look up ${hit.name} in the rules`
        }
      >
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-1.5">
            <span className="min-w-0 truncate text-xs font-medium text-arcane-300">
              {hit.name}
            </span>
            <span className="ml-auto shrink-0 text-[0.7rem] text-parchment/35">
              {hit.level_label}
            </span>
          </span>
          <span className="block truncate text-[0.7rem] text-parchment/50">
            {contextLine(hit.text)}
          </span>
        </span>
        <MatchDial distance={hit.distance} />
      </a>
    </li>
  )
}

/**
 * What identifies one row, for React's reconciliation.
 *
 * A rule is identified by its document and heading and a spell by its file, because the two
 * kinds share the collection and a name alone is not unique across them - the SRD has a
 * heading called "Fireball" and the corpus has a spell of the same name.
 */
function hitKey(hit: SearchHit): string {
  return hit.doc_type === "srd"
    ? `srd:${hit.document}:${hit.slug}`
    : `${hit.doc_type}:${hit.filename || hit.name}`
}

/**
 * One line of a chunk, as the context beside a hit's title.
 *
 * The chunk is markdown, and its own markup is what a reader would otherwise see: every one
 * of these bodies opens with `**Interposing Hand.**` or a `#### ` heading, so a raw first
 * line spends its width on asterisks and hashes instead of on the words. Markup is stripped
 * rather than rendered, because this is a preview of *which* part of the spell matched, not
 * the spell - the drawer is one click away and shows it properly.
 *
 * The first line with prose on it is taken rather than the literal first line. A chunk
 * usually opens with the heading it was split at, and the markup-stripped heading is not the
 * informative part - `Using a Higher-Level Spell Slot.` says which paragraph this is, not what
 * it does. A heading is therefore skipped when it is a label rather than a sentence, which is
 * the whole difference between the two here: these names are short and unpunctuated, while the
 * prose that follows them ends in a full stop. A one-line spell description ("Solid Fog.") is
 * prose and is kept.
 */
function contextLine(text: string): string {
  const lines = text
    .split("\n")
    .map((line) => plain(line))
    .filter((line) => line.length > 0)
  // A line of nothing but stat-block fields says nothing about why this spell matched, so the
  // first line with prose on it is preferred - and the first field is shown only when the
  // whole chunk is fields, which is worse than nothing but not by much.
  return (
    lines.find((line) => isProse(line)) ??
    lines.find((line) => !isField(line)) ??
    lines[0] ??
    ""
  )
}

/** A single line of a chunk, with the markdown that would eat the width taken out. */
function plain(line: string): string {
  return (
    line
      .replace(/^\s*#{1,6}\s*/, "")
      .replace(/\*\*|__|`/g, "")
      // Single underscores are the corpus's italics - `_Using a Higher-Level Spell Slot._` -
      // so a `_` touching a non-word character is a marker and is dropped. Requiring that
      // boundary is what keeps a name with an underscore in it intact.
      .replace(/(?<![\p{L}\p{N}])_|_(?![\p{L}\p{N}])/gu, "")
      // Links become their text: the corpus points at dndbeyond for the rules it cites, and a
      // URL is the one thing that would eat the whole line. The corpus also writes those
      // citations tight against the words on either side - `grants you[Half Cover](...)against`
      // - so a space is restored on whichever side a letter would otherwise be glued to the
      // link text. Without it the preview reads `youHalf Coveragainst`, which looks like a typo
      // rather than like a link. Both sides are handled in one pass because doing it in two
      // lets the first rule consume the syntax the second was going to look past.
      .replace(
        /([\p{L}\p{N}])?\[([^\]]+)\]\([^)]*\)([\p{L}\p{N}])?/gu,
        (_, before, text, after) =>
          `${before ? `${before} ` : ""}${text}${after ? ` ${after}` : ""}`,
      )
      // The same tightness applies to the corpus's bolded sub-headings: `**Interposing
      // Hand.**The hand grants` is one line with no space after the full stop.
      .replace(/([.!?])(?=[A-Z])/g, "$1 ")
      .trim()
  )
}

/**
 * Whether a stripped line reads as a sentence rather than as a label.
 *
 * A label is a short, unpunctuated heading - `Using a Higher-Level Spell Slot.` is exactly
 * that, and it is what half these chunks open with. Prose is long or punctuated. The length
 * threshold is generous on purpose: the cost of calling a label prose is showing the label,
 * which is what the panel did before, and the cost of the reverse is skipping a real
 * one-sentence description.
 *
 * The stat block's own field lines are excluded outright. Every corpus file opens with
 * `Spell Name: X` and `Casting Time: X`, and a chunk cut at a boundary can be nothing but
 * those - each one punctuated, so each one would pass as a sentence and a dozen hits would
 * all preview as `Spell Name: Nondetection`. The colon is the tell, and a short label in
 * front of it is what separates a field from prose that happens to contain one.
 */
function isProse(line: string): boolean {
  if (isField(line)) return false
  return /[.!?:;]/.test(line.slice(0, -1)) || line.split(/\s+/).length > 12
}

/** Whether a line is a stat-block field (`Spell Name: X`) rather than prose. */
function isField(line: string): boolean {
  return /^[A-Z][A-Za-z' -]{0,24}:\s/.test(line)
}
