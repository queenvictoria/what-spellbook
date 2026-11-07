import { useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { BookOpenIcon, Loader2, Search, X } from "lucide-react"

import { api, ApiError } from "@/api/client"
import type { Answer, SearchResult, Spell } from "@/api/types"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { SpellLink } from "@/components/SpellLink"
import { SpellCard } from "@/components/SpellCard"
import { SrdCard } from "@/components/SrdCard"
import { SrdPathLink } from "@/components/SrdPathLink"
import { SrdTree } from "@/components/SrdTree"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useDebouncedCallback } from "@/lib/useDebounced"
import { useSrdDocuments, useSrdSection, srdHref } from "@/lib/srd"
import { filterDocuments, firstMatch, matchList } from "@/lib/srdFilter"
import type { SrdFilter } from "@/lib/srdFilter"

/**
 * How long typing has to stop before the two requests are made.
 *
 * Long enough that a question typed at speed fires once, short enough that the pause after a
 * word does not read as the app ignoring the input. The keyword filter is deliberately not
 * subject to it: it is synchronous and answers as the reader types, which is what makes the
 * tab usable while the two requests are still in flight.
 */
const DEBOUNCE_MS = 400

/**
 * How many spell hits the index column lists.
 *
 * Twelve, because it is a glance beside two other readings rather than a browse: the Search
 * tab is the surface for paging through candidates, and a column of forty titles is not
 * scannable next to an answer. It is set here rather than at the call site so the number in
 * the copy and the number in the request cannot drift apart.
 */
const SEARCH_LIMIT = 12

/**
 * A question that names no rule gets a closest-match reading, and the card says why.
 *
 * This is the same measurement the filter is built around seen from the reader's side: three
 * of the four words in "how does cover work" name nothing, so the substitute is closer
 * headings. Saying so up front is cheaper than the reader concluding the rule is missing.
 *
 * "Heading", not "rule": the count is of headings whose text names the words, and a match is
 * not the same as an answer - the rule under a heading is the answer, and it is one click
 * away. Calling them rules would overclaim, which is the failure this whole tab is built to
 * avoid.
 */
function filterTitle(filter: SrdFilter): string {
  if (filter.matches === 0) return "No heading matches"
  if (filter.partial) return `${filter.matches} closest heading${filter.matches === 1 ? "" : "s"}`
  return `${filter.matches} heading${filter.matches === 1 ? "" : "s"} match`
}


const EXAMPLES = [
  "how does cover work",
  "what happens when you drop prone",
  "how does difficult terrain work",
]

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
  return lines.find((line) => isProse(line)) ?? lines.find((line) => !isField(line)) ?? lines[0] ?? ""
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

/**
 * Rules lookup: the `/?` command, and the target of every spell mention in the app.
 *
 * Answers are quoted from the vendored 2024 SRD in `context/srd/` and cached, so
 * repeating a question costs nothing. When no heading names the question, the answer is
 * *interpreted* from the closest related SRD text and the badge says so — an
 * interpretation is not a quotation. The 2024 SRD is not the whole 2024 rulebook, and
 * several common rules are genuinely absent from it - a Short Rest, for one. When that
 * happens the honest outcome is to say which part is missing rather than to answer from
 * memory, and a 404 is a normal result here, not an error to hide.
 *
 * `?spell=Name` opens a spell instead of a question. The text is quoted from a vendored
 * file rather than generated, so it cannot be a paraphrase of a damage die. Three sources
 * are tried in order and the card says which answered: the 2024 SRD, the retrieval corpus
 * for the ~200 spells the SRD does not carry (Tenser's Floating Disk, Bigby's Hand), and
 * our own class context for Eldritch Invocations, which the SRD does not publish at all.
 *
 * ## One box, three readings
 *
 * A typed question is answered three ways at once, each updating the panel as it resolves
 * rather than waiting for the others:
 *
 *  1. **The tree is filtered** by the question's words, synchronously, over headings only.
 *     This is what makes the tab browsable while a model call is in flight, and it is the
 *     only one of the three that can be exhaustive: 1280 headings is small enough to read
 *     all of on each keystroke.
 *  2. **The index is searched**, in `text` mode, because a question is prose rather than a
 *     description of a spell - `vector` mode would rank spells by how much the question
 *     *sounds* like them. The request carries `limit=12`, since this is one column beside
 *     two others and not the Search tab.
 *  3. **The question is asked** of the SRD, exactly as before.
 *
 * What the three do *not* do is chain. The search is not skipped because the filter matched,
 * and the ask is not skipped because the search found something: a rule can be named under
 * a heading, absent from the corpus index, and answerable by interpretation all at once, and
 * the reader chooses which reading answered their question by looking at the badges.
 *
 * The two requests are debounced - see `useDebouncedCallback` - so typing a sentence costs
 * one ask at the end rather than one per word. Nothing already on screen is cleared while
 * typing, so each lane is replaced when its own answer arrives rather than the page blanking
 * and refilling.
 */
export function RulesScreen() {
  const [params, setParams] = useSearchParams()
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // The conversation this screen is in. Held so a follow-up is read in context, and so
  // the exchange can be found again on the Chats screen.
  const [threadId, setThreadId] = useState<string | null>(null)
  const [search, setSearch] = useState<SearchResult | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  // Which request each lane is currently waiting for, as plain counters rather than booleans.
  //
  // The lanes are independent and can be in flight together, so a reply arriving out of order
  // has to be told apart from the current one. A flag cannot do that: it says "something is
  // loading", not "this reply is the one being waited for", and the failure it hides is an
  // answer to an abandoned question appearing as if it were current. Bumping a counter per
  // request makes "is this still wanted" one comparison.
  //
  // One counter **per lane**, not one between them: the two requests are fired together and
  // share no ordering, so a single counter would make whichever resolved second invalidate
  // the other's reply, and one of the two panels would silently never fill.
  const latestSearch = useRef(0)
  const latestAsk = useRef(0)

  const spellName = params.get("spell")
  const srdDocument = params.get("doc")
  const srdSlug = params.get("section")
  const { documents, error: srdError, loading: srdLoading } = useSrdDocuments()
  const {
    section,
    error: sectionError,
    loading: sectionLoading,
  } = useSrdSection(srdDocument, srdSlug)

  // The filter reads the live question rather than the settled one. It is synchronous and
  // cheap - 1274 headings, measured at well under a frame - and the whole point of this lane
  // is that it answers while the two requests are still waiting, so debouncing it would delay
  // the only reading that could have been instant. Typing one character does nothing, because
  // `filterTerms` drops single letters.
  const filtered = useMemo(
    () => (documents ? filterDocuments(documents, question) : null),
    [documents, question],
  )

  // The spell is fetched into state keyed by name, and the render reads it only when the
  // key still matches the URL. That keeps the effect free of synchronous setState - which
  // would cascade a second render on every navigation - while still clearing the card the
  // moment the query changes.
  const [loaded, setLoaded] = useState<{ name: string; spell: Spell } | null>(
    null,
  )
  const spell = loaded && loaded.name === spellName ? loaded.spell : null

  useEffect(() => {
    if (!spellName) return
    let cancelled = false
    // A name in the link list may be a spell or an Eldritch Invocation, and the list does
    // not say which. Trying the spell first and falling back keeps the front end from
    // needing a second list, and the fallback only runs on a 404 - a real failure still
    // surfaces rather than being swallowed as "not an invocation either".
    api
      .spell(spellName)
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404)
          return api.invocation(spellName)
        throw e
      })
      .then((found) => {
        if (!cancelled) setLoaded({ name: spellName, spell: found })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (e instanceof ApiError && e.status === 404) setMissing(e.message)
        else setError(e instanceof ApiError ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [spellName])

  /**
   * Open a section, or a whole file when `slug` is null.
   *
   * The spell is cleared because the two readings share the screen: leaving `?spell=` in the
   * URL would show a spell card above a rule the reader just asked for, and the address
   * would claim both.
   */
  function openSrd(document: string, slug: string | null) {
    const next: Record<string, string> = { doc: document }
    if (slug) next.section = slug
    setParams(next)
  }

  /**
   * Lane 2: the index search, fired once typing stops.
   *
   * Vector mode, which is what the Search tab defaults to: a rules question is a description
   * of a *situation* rather than words copied out of a spell, so similarity is the reading
   * that finds related spells - "protect an ally from being grappled" ranks Freedom of
   * Movement and Grasping Vine rather than everything containing the word "protect". A text
   * search over the same question is near-useless at this size: "how does cover work" matches
   * 103 of the 544 spells on "cover" or "work" alone.
   *
   * The `limit` is small on purpose. This column sits beside the filter and the answer, so a
   * dozen candidates is a glance rather than a browse; the Search tab is the surface for
   * browsing, and it is one nav click away.
   */
  async function runSearch(text: string) {
    if (!text.trim()) {
      setSearch(null)
      setSearchError(null)
      return
    }
    const run = ++latestSearch.current
    setSearching(true)
    setSearchError(null)
    try {
      const found = await api.search({
        query: text,
        mode: "vector",
        limit: SEARCH_LIMIT,
      })
      // A reply that arrives after a newer one - or after the box was cleared - is discarded
      // rather than rendered. Without this the panels fill with an answer to a question the
      // reader has already replaced, which is worse than a blank panel: it looks current.
      if (run !== latestSearch.current) return
      setSearch(found)
    } catch (e) {
      if (run !== latestSearch.current) return
      setSearch(null)
      setSearchError(e instanceof ApiError ? e.message : String(e))
    } finally {
      if (run === latestSearch.current) setSearching(false)
    }
  }

  /**
   * Lane 3: the question, asked as it always was.
   *
   * Clearing the URL is what dismisses a spell or a rule the previous question opened, since
   * the three readings share the screen and the address must not claim both.
   */
  async function look(text = question) {
    if (!text.trim()) return
    if (spellName || srdDocument) setParams({}, { replace: true })
    const run = ++latestAsk.current
    setLoading(true)
    setError(null)
    setAnswer(null)
    setMissing(null)
    try {
      const result = await api.rules(text, threadId ?? undefined)
      if (run !== latestAsk.current) return
      setAnswer(result)
      setThreadId(result.thread_id)
    } catch (e) {
      if (run !== latestAsk.current) return
      if (e instanceof ApiError && e.status === 404) {
        setMissing(e.message)
      } else {
        setError(e instanceof ApiError ? e.message : String(e))
      }
    } finally {
      if (run === latestAsk.current) setLoading(false)
    }
  }

  // One debounce for both requests, so a settled question fires them together. Each lane
  // keeps its own loading flag, so the panels fill in as they answer rather than together.
  const debouncedSearch = useDebouncedCallback(runSearch, DEBOUNCE_MS)
  const debouncedAsk = useDebouncedCallback(look, DEBOUNCE_MS)

  /**
   * Typing is the input; there is no submit to wait for.
   *
   * The requests are scheduled from the change handler rather than from an effect watching
   * the query, because an effect that reacts to the query can only *notice* it changed -
   * and the reset on an emptied box is then a synchronous setState in an effect body, which
   * cascades a render for a query nobody asked about.
   *
   * Nothing already on screen is cleared while typing. The three readings are the only record
   * of what the last searched question produced, and blanking them on the first keystroke of
   * the next one makes the page flash on every word. They are replaced when their replacements
   * arrive, which is what "updating as each resolves" means.
   */
  function type(text: string) {
    setQuestion(text)
    if (!text.trim()) {
      // An emptied box has no readings to show, so this is the one case that clears - and a
      // deliberate act rather than a keystroke on the way to a new question.
      debouncedSearch.cancel()
      debouncedAsk.cancel()
      // Whatever is already in flight is abandoned, not merely hidden: clearing the box is
      // how a reader says "none of this any more", and a reply that lands a second later
      // would refill the panels with an answer to a question no longer on screen.
      latestSearch.current++
      latestAsk.current++
      setSearching(false)
      setLoading(false)
      setSearch(null)
      setSearchError(null)
      setAnswer(null)
      setError(null)
      setMissing(null)
      return
    }
    debouncedSearch.call(text)
    debouncedAsk.call(text)
  }

  /** Everything, now, without waiting out the debounce. */
  function askNow() {
    const text = question.trim()
    if (!text) return
    debouncedSearch.cancel()
    debouncedAsk.cancel()
    runSearch(text)
    look(text)
  }

  /** Jump to the first heading the filter matched, or the whole file when one did. */
  function openFirstMatch() {
    if (!filtered) return
    const found = firstMatch(filtered)
    if (!found) return
    setParams(found.slug ? { doc: found.document, section: found.slug } : { doc: found.document })
  }

  // Which of the three readings have something to show. A pane with nothing in it is hidden
  // rather than rendered empty, because an empty column costs a third of the width to say
  // nothing - and the lanes resolve independently, so a blank pane is the normal state for
  // the first few hundred milliseconds rather than an error.
  const matches = useMemo(() => (filtered ? matchList(filtered) : []), [filtered])
  const hits = search?.hits ?? []
  const showFilter = filtered !== null && filtered.matches > 0
  const showSearch = searching || hits.length > 0 || searchError !== null
  const showAnswer = loading || answer !== null || error !== null || missing !== null

  return (
    // Wider than the other screens: the browser is two panes side by side, and at the
    // reading width the tree and the rule would each be too narrow to use.
    <div className="max-w-5xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Ask the 2024 SRD</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            {/* The clear button is inside the field's own box rather than beside the Ask
                button, because it acts on the text and not on the question: it belongs
                where the text is. It appears only when there is text to clear, so an empty
                box has no dead control next to it. */}
            <div className="relative min-w-0 flex-1">
              <Input
                value={question}
                placeholder="how does cover work"
                onChange={(e) => type(e.target.value)}
                onKeyDown={(e) => {
                  // Enter is a shortcut, not the only way in. It skips the wait the debounce
                  // would have imposed, which is what a reader who has finished typing and
                  // hit enter is asking for.
                  if (e.key === "Enter") askNow()
                  // Escape clears, which is what the button does - the same act should not
                  // need a trip to the mouse.
                  if (e.key === "Escape") type("")
                }}
                className={question ? "pr-8" : undefined}
              />
              {question !== "" && (
                <button
                  type="button"
                  onClick={() => type("")}
                  aria-label="Clear the question"
                  title="Clear"
                  className="absolute top-1/2 right-1 -translate-y-1/2 rounded p-1 text-parchment/40 hover:bg-void-800 hover:text-parchment"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <Button
              onClick={askNow}
              disabled={!question.trim()}
              aria-label="Ask"
              title="Ask the 2024 SRD"
              className="shrink-0 whitespace-nowrap"
            >
              <Search className="h-4 w-4" />
              <span className="sr-only">Ask</span>
            </Button>
          </div>
          <p className="text-xs text-parchment/45">
            Every word filters the rulebook by heading, searches the index, and asks the
            question. The three answers arrive independently — the badges say which one
            produced what you are reading.
          </p>
          <div className="flex flex-wrap gap-1">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => {
                  // Set through `type` so the example is filtered, searched and asked in one
                  // move - calling `askNow` alone would leave the tree showing the last thing
                  // that was typed.
                  type(example)
                }}
                className="rounded-full border border-void-700 px-2 py-0.5 text-[0.7rem] text-parchment/60 hover:text-parchment"
              >
                {example}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* One box, three readings, side by side.

          They used to stack, which put the answer - the longest reading and usually the one
          being asked for - below two panels that could each be a screen tall, so the best
          answer was often the one furthest from the box that produced it. Columns put the
          three at the same height instead.

          A column with nothing to show is dropped rather than rendered empty, and that is
          not only about width: the three lanes resolve independently, so for the first few
          hundred milliseconds two of them have nothing in them, and an empty bordered box
          reads as a failure rather than as a request still in flight. */}
      {(showFilter || showSearch || showAnswer) && (
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          {/* The filter's own reading, which is the only one that cannot be wrong: it lists
              where the words are, and it costs no request. `matches` counts headings that
              name the words, which is deliberately not the number of rows - the rows are
              whole paths, kept so the branch says where a rule lives. */}
          {showFilter && filtered && (
            <Card className="lg:min-w-0 lg:flex-1">
              <CardHeader className="flex-row items-center justify-between gap-2">
                <CardTitle className="text-sm">{filterTitle(filtered)}</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={openFirstMatch}
                  className="shrink-0"
                >
                  Open first
                </Button>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-parchment/55">
                {filtered.unknown.length > 0 && (
                  <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
                    No heading contains{" "}
                    <span className="font-mono">{filtered.unknown.join('", "')}</span>, so
                    nothing was required of it.
                  </p>
                )}
                {filtered.partial && (
                  <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
                    No heading names all of{" "}
                    <span className="font-mono">{filtered.terms.join('", "')}</span>, so
                    these are the closest headings rather than the answer.
                  </p>
                )}
                {filtered.truncated && (
                  <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
                    More than {filtered.limit} matched; the first {filtered.limit} are shown.
                  </p>
                )}
                {/* Bounded and scrollable: the column sits beside two others, and an
                    unbounded list would make the row as tall as the whole rulebook. */}
                <ul className="max-h-[26rem] space-y-0.5 overflow-y-auto pr-1">
                  {matches.map((match) => (
                    <li key={`${match.document}:${match.slug}`}>
                      <a
                        href={srdHref(match.document, match.slug || null)}
                        onClick={(event) => {
                          // Only a plain left click is ours; a modified click is the reader
                          // asking the browser for a new tab, which is what the href is for.
                          if (
                            event.button !== 0 ||
                            event.metaKey ||
                            event.ctrlKey ||
                            event.shiftKey ||
                            event.altKey
                          )
                            return
                          event.preventDefault()
                          openSrd(match.document, match.slug || null)
                        }}
                        className="block rounded px-1 py-0.5 hover:bg-void-800"
                        title={match.path.join(" › ")}
                      >
                        <span className="block truncate font-medium text-arcane-300">
                          {match.text}
                        </span>
                        {/* The trail, one line, clamped - it is what tells two headings of
                            the same name apart ("Cover" is a different rule in Rules
                            Glossary and in Playing the Game). */}
                        <span className="block truncate text-[0.7rem] text-parchment/35">
                          {match.path.slice(0, -1).join(" › ")}
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {/* The index's own reading, which can return a spell the character could never
              pick, on purpose: this panel is diagnostic, like the Search tab, and a spell
              missing from a recommendation is explained here.

              A title rather than the full hit card. The Search tab is the surface for
              reading a hit in full; this column is for noticing that a spell is relevant
              at all, and twelve expandable cards beside two other columns is not a glance.
              The name is a real link, so a plain click opens the drawer and a modified one
              opens the Rules tab on that spell. */}
          {showSearch && (
            <Card className="lg:min-w-0 lg:flex-1">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Search className="h-4 w-4" />
                  In the spell index
                  {searching && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-arcane-300" />
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {searchError && <p className="text-sm text-red-300">{searchError}</p>}
                {search && (
                  <>
                    <p className="text-[0.7rem] text-parchment/45">
                      {hits.length} shown · {search.total_matching} spell
                      {search.total_matching === 1 ? "" : "s"} match ·{" "}
                      <span className="font-mono">{search.elapsed_ms.toFixed(0)}ms</span>
                    </p>
                    {search.note && (
                      <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-[0.7rem] text-radiant-400">
                        {search.note}
                      </p>
                    )}
                  </>
                )}
                {!searching && !searchError && hits.length === 0 && (
                  <p className="text-sm text-parchment/60">
                    No chunk is close to that description. The Search tab has text and hybrid
                    modes, which fail differently.
                  </p>
                )}
                <ul className="max-h-[26rem] space-y-1.5 overflow-y-auto pr-1">
                  {hits.map((hit) => (
                    <li key={hit.filename + hit.name} className="min-w-0">
                      <div className="flex items-baseline gap-1.5">
                        <SpellLink name={hit.name} className="min-w-0 truncate text-xs font-medium" />
                        <span className="ml-auto shrink-0 text-[0.7rem] text-parchment/35">
                          {hit.level_label}
                        </span>
                      </div>
                      <p className="truncate text-[0.7rem] text-parchment/50">
                        {contextLine(hit.text)}
                      </p>
                    </li>
                  ))}
                </ul>
                <p className="text-[0.7rem] text-parchment/40">
                  A similarity search over chunk bodies, not the recommender. It can name a
                  spell this character could never prepare, on purpose.
                </p>
              </CardContent>
            </Card>
          )}

          {/* The question, asked as it always was. Given more width than the other two: it
              is the only reading written in sentences, and the two beside it are lists. */}
          {showAnswer && (
            <div className="space-y-4 lg:min-w-0 lg:flex-[1.4]">
              {error && (
                <Card className="border-red-500/40">
                  <CardContent className="pt-4 text-sm text-red-300">{error}</CardContent>
                </Card>
              )}

              {missing && (
                <Card className="border-radiant-500/40">
                  <CardHeader>
                    <CardTitle className="text-radiant-400">Not in the SRD</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm text-parchment/70">
                    <p>{missing}</p>
                    <p className="text-xs text-parchment/45">
                      The 2024 SRD is a subset of the 2024 rulebook. Rules that are absent here
                      are reported as absent rather than answered from memory, because a
                      confidently wrong rule is worse than a gap.
                    </p>
                  </CardContent>
                </Card>
              )}

              {(loading || answer) && (
                <Card>
                  <CardHeader className="flex-row items-center justify-between gap-2">
                    <CardTitle className="text-sm">
                      {answer ? answer.question : "Asking the SRD…"}
                      {loading && (
                        <Loader2 className="ml-2 inline h-3.5 w-3.5 animate-spin align-[-0.15em] text-arcane-300" />
                      )}
                    </CardTitle>
                    {answer && <SourceBadge source={answer.source} />}
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {answer && <Markdown text={answer.answer} className="prose-spell" />}
                    {answer && answer.citations.length > 0 && (
                      <div className="space-y-1 border-t border-void-800 pt-2">
                        {answer.citations.map((path) => (
                          <p key={path} className="truncate">
                            <SrdPathLink path={path} />
                          </p>
                        ))}
                      </div>
                    )}
                    {answer?.from_cache && (
                      <p className="text-xs text-parchment/60">Answered from cache.</p>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          )}
        </div>
      )}

      {/* The filter's finding, when it has nothing to list.

          The column above is hidden when nothing matches, which is what keeps an empty pane
          from costing a third of the width - but a word the rulebook never writes is the
          actual answer to "why did nothing match", and hiding the column would hide it with
          it. One line, only in the case that needs explaining. */}
      {!showFilter && filtered && filtered.unknown.length > 0 && (
        <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-xs text-radiant-400">
          No heading contains{" "}
          <span className="font-mono">{filtered.unknown.join('", "')}</span>, so nothing was
          required of it. A rule can still exist under a different name — the other two
          readings are the ones to check.
        </p>
      )}

      {/* A spell or a rule the reader opened by link, or the rule the answer above is about.
          Full width and outside the grid, because it is a *document* rather than one of the
          three readings of a question: a spell card is as long as the spell, and squeezing it
          into a third of the width would put its own text beside the answer about it. */}
      {spell && <SpellCard spell={spell} />}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <BookOpenIcon className="h-4 w-4" />
            Browse the 2024 SRD
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 md:flex-row">
          {/* The tree is bounded and scrolls on its own, because `spells.md` alone is 379
              headings: unbounded, expanding it pushes the rule the reader just clicked far
              below the fold, so the click looks like it did nothing. */}
          <div className="shrink-0 space-y-2 md:w-64">
            {/* The filter is reported here too, next to the tree it narrowed: the column
                above lists the matches, but this tree is the whole filtered shape - the paths
                kept so a branch says where a rule lives - and the count is only meaningful
                beside what it counts. Hidden when the column above is showing the same count,
                so the two readings of one number do not sit side by side disagreeing. */}
            {filtered && !showFilter && (
              <p className="text-[0.7rem] text-parchment/45">
                {filtered.matches} matching heading
                {filtered.matches === 1 ? "" : "s"} — the tree below is the whole rulebook
                again, so there is still somewhere to look.
              </p>
            )}
            {srdLoading && (
              <p className="flex items-center gap-2 text-sm text-parchment/60">
                <Loader2 className="h-4 w-4 animate-spin" />
                Reading the rulebook…
              </p>
            )}
            {srdError && <p className="text-sm text-red-300">{srdError}</p>}
            {documents && (
              <div className="max-h-[32rem] overflow-y-auto pr-1">
                <SrdTree
                  documents={documents}
                  // A filter that matched nothing is dropped rather than applied, which puts
                  // the whole rulebook back on screen. An empty tree beside a search column
                  // is a browse surface that has been taken away: the reader asked a question
                  // the headings cannot answer, not to lose the ability to look.
                  filter={showFilter ? filtered : null}
                  selected={
                    srdDocument ? `${srdDocument}:${srdSlug ?? ""}` : null
                  }
                  onSelect={openSrd}
                />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            {sectionLoading && (
              <p className="flex items-center gap-2 text-sm text-parchment/60">
                <Loader2 className="h-4 w-4 animate-spin" />
                Fetching the rule…
              </p>
            )}
            {sectionError && (
              <Card className="border-red-500/40">
                <CardContent className="pt-4 text-sm text-red-300">
                  {sectionError}
                </CardContent>
              </Card>
            )}
            {section && <SrdCard section={section} />}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
