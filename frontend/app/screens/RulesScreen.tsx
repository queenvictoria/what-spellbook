import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { BookOpenIcon, Loader2Icon, WandSparklesIcon } from "lucide-react"

import { api, ApiError } from "@/api/client"
import type { Answer, SearchResult, Spell } from "@/api/types"
import { AskBox } from "@/components/AskBox"
import { ClassContextCard } from "@/components/ClassContextCard"
import { ErrorNotice } from "@/components/ErrorNotice"
import { IndexHitsPanel } from "@/components/IndexHits"
import { Markdown } from "@/components/Markdown"
import { SourceBadge } from "@/components/SourceBadge"
import { SpellCard } from "@/components/SpellCard"
import { SrdCard } from "@/components/SrdCard"
import { RulePathLink } from "@/components/RulePathLink"
import { SrdTree } from "@/components/SrdTree"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useDebouncedCallback } from "@/lib/useDebounced"
import { TYPING_DEBOUNCE_MS } from "@/lib/timing"
import { useSrdDocuments, useSrdSection, srdHref } from "@/lib/srd"
import { useAnchorScroll } from "@/lib/ruleDrawer"
import { useClassContext } from "@/lib/classContext"
import { filterDocuments, matchList } from "@/lib/srdFilter"
import type { SrdFilter } from "@/lib/srdFilter"

/**
 * How many index hits the index column lists, rules and spells together.
 *
 * Twelve, because it is a glance beside two other readings rather than a browse: the Search
 * tab is the surface for paging through candidates, and a column of forty titles is not
 * scannable next to an answer. It is set here rather than at the call site so the number in
 * the copy and the number in the request cannot drift apart.
 *
 * One budget for both kinds rather than one each: a question whose answer is a rule should
 * not have the rule crowded out by spells, and a request per kind would double the cost of
 * the column to answer the same question twice. The render splits what comes back, so the
 * nearest rule is always shown even when six spells sit ahead of it.
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
  if (filter.partial)
    return `${filter.matches} closest heading${filter.matches === 1 ? "" : "s"}`
  return `${filter.matches} heading${filter.matches === 1 ? "" : "s"} match`
}

const EXAMPLES = [
  "how does cover work",
  "what happens when you drop prone",
  "how does difficult terrain work",
]

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
 * A typed question is answered three ways, each updating the panel as it resolves rather than
 * waiting for the others:
 *
 *  1. **The tree is filtered** by the question's words, synchronously, over headings only.
 *     This is what makes the tab browsable while a model call is in flight, and it is the
 *     only one of the three that can be exhaustive: 1280 headings is small enough to read
 *     all of on each keystroke.
 *  2. **The index is searched** for both rules and spells. Vector mode, because a question is
 *     a description of a *situation* rather than words copied out of a spell - a text search
 *     over the same question matches 103 of the 544 spells on "cover" or "work" alone. The
 *     request carries `limit=12` and `doc_type=all`, since this is one column beside two
 *     others and not the Search tab, and because a rules question should be able to reach the
 *     rulebook as well as the spell corpus. The result is one list in the API's own order,
 *     because the ranking is the reading - see `IndexHitsCard`.
 *  3. **The question is asked** of the SRD, exactly as before.
 *
 * What the three do *not* do is chain. The search is not skipped because the filter matched,
 * and the ask is not skipped because the search found something: a rule can be named under
 * a heading, absent from the corpus index, and answerable by interpretation all at once, and
 * the reader chooses which reading answered their question by looking at the badges.
 *
 * **Typing drives the first two; asking is a separate act.** The filter is synchronous and the
 * search costs one embedding request, so both follow the typing - the search on a debounce, so
 * a sentence typed at speed costs one request rather than one per word. The ask costs a model
 * call and takes seconds, so it waits for the Ask button or Enter. It used to be debounced
 * alongside the search, which spent a model call on every pause in a sentence the reader was
 * still composing. Nothing already on screen is cleared while typing, so each lane is replaced
 * when its own answer arrives rather than the page blanking and refilling.
 */
export function RulesScreen() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [question, setQuestion] = useState("")
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [missing, setMissing] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // The conversation this screen is in. Held so a follow-up is read in context, and so
  // the exchange can be found again under History → Conversations.
  const [threadId, setThreadId] = useState<string | null>(null)
  const [search, setSearch] = useState<SearchResult | null>(null)
  const [searchError, setSearchError] = useState<unknown>(null)
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
  // A class context file, opened by a link in an answer. It shares the screen with the SRD
  // browser rather than getting a card of its own, because it is the same kind of reading -
  // a document quoted from a file - and a fourth lane would crowd the three that answer the
  // question.
  const contextPath = params.get("context")
  // The heading to land on, when the address names one. Read from the router rather than
  // from `window.location` so a client-side navigation to a fragment is seen too - the
  // browser only scrolls for a fragment it loaded itself.
  const anchor = useLocation().hash.slice(1) || null
  const { documents, error: srdError, loading: srdLoading } = useSrdDocuments()
  const {
    section,
    error: sectionError,
    loading: sectionLoading,
  } = useSrdSection(srdDocument, srdSlug)
  const {
    document: classDocument,
    error: classError,
    loading: classLoading,
  } = useClassContext(contextPath)

  // Gated on `documents` as well as the section, because the ids come from the table of
  // contents: the section can arrive first, and scrolling before the anchors exist would
  // find nothing and never run again.
  useAnchorScroll(
    anchor,
    section && documents ? `${section.document}:${section.slug}` : null,
  )

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
        else setError(e)
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
   *
   * `anchor` names a heading *inside* the section to land on, which is how a breadcrumb opens
   * a parent at the child the reader was reading. It is dropped when it is the section's own
   * slug, because a fragment naming the heading the card already starts at is a scroll to
   * where the reader already is.
   */
  function openSrd(
    document: string,
    slug: string | null,
    anchor?: string | null,
  ) {
    const search = new URLSearchParams({ doc: document })
    if (slug) search.set("section", slug)
    navigate({
      pathname: "/rules",
      search: `?${search.toString()}`,
      // A fragment naming the heading the card already starts at is a scroll to where the
      // reader already is, so it is dropped. The hash is a field of its own rather than part
      // of the search string, because a `#` inside a query string is percent-encoded and the
      // browser would never read it as a fragment.
      hash: anchor && anchor !== slug ? `#${anchor}` : "",
    })
  }

  /**
   * Lane 2: the index search, fired once typing stops.
   *
   * Vector mode, which is what the Search tab defaults to: a rules question is a description
   * of a *situation* rather than words copied out of a spell, so similarity is the reading
   * that finds related text - "protect an ally from being grappled" ranks Freedom of
   * Movement and Grasping Vine rather than everything containing the word "protect". A text
   * search over the same question is near-useless at this size: "how does cover work" matches
   * 103 of the 544 spells on "cover" or "work" alone.
   *
   * ``doc_type: "all"``, because the collection holds the rulebook as well as the spell
   * corpus and this tab is asking a *rules* question. Leaving the default (spells only) is
   * how the lane came to answer "how does cover work" with eleven spells that mention cover
   * and never with the Cover rule - the one thing the reader named. The two kinds share the
   * collection and are told apart by ``doc_type``, so asking for both is one request.
   *
   * The `limit` is small on purpose. This column sits beside the filter and the answer, so a
   * dozen candidates is a glance rather than a browse; the Search tab is the surface for
   * browsing, and it is one nav click away. It is split in the render rather than fetched
   * separately per kind, so a question whose best match is a rule cannot have it crowded out
   * of the list by spells that happen to sit a little nearer.
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
        doc_type: "all",
      })
      // A reply that arrives after a newer one - or after the box was cleared - is discarded
      // rather than rendered. Without this the panels fill with an answer to a question the
      // reader has already replaced, which is worse than a blank panel: it looks current.
      if (run !== latestSearch.current) return
      setSearch(found)
    } catch (e) {
      if (run !== latestSearch.current) return
      setSearch(null)
      setSearchError(e)
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
    // The fragment is cleared with the query: it names a heading in the rule being dismissed,
    // and left behind it would scroll the next rule to a heading that is not in it.
    if (spellName || srdDocument)
      navigate({ pathname: "/rules", search: "", hash: "" }, { replace: true })
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
        setError(e)
      }
    } finally {
      if (run === latestAsk.current) setLoading(false)
    }
  }

  // One debounce, for the two readings that follow the typing. The ask is deliberately *not*
  // debounced: it is the one lane that costs a model call, so it waits for an explicit act
  // rather than being spent on every pause in a sentence.
  const debouncedSearch = useDebouncedCallback(runSearch, TYPING_DEBOUNCE_MS)

  /**
   * Typing is the input for the two cheap readings; asking is a separate act.
   *
   * The filter is not scheduled here at all - it reads the live question and is synchronous,
   * so it has already answered by the time this runs. What is scheduled is the index search,
   * which costs an embedding request.
   *
   * The ask used to be scheduled here too, which meant a sentence typed at speed spent a model
   * call on every pause in it. That is the wrong default for the one lane that costs money and
   * takes seconds: a reader composing a question is not asking it yet, and the answer to a
   * half-typed question is not a reading they wanted. It is now reached only from the Ask
   * button or Enter, both of which are the reader saying they are done.
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
  }

  /**
   * Ask the question, now, without waiting out the debounce.
   *
   * The pending search is cancelled rather than left to fire: the ask is the reader saying they
   * are done typing, so the search it would have run is the same search this runs immediately -
   * and letting both go would issue one request twice and leave two replies racing to fill one
   * panel.
   *
   * `text` defaults to the box's own contents, and is passed explicitly by the examples below,
   * which set the box and ask in one move - reading `question` there would ask the *previous*
   * question, because the state update has not been applied yet. It is typed as a string rather
   * than left to inference so that a caller which hands this a DOM event by mistake fails to
   * compile instead of asking a question made of an event object.
   */
  function askNow(text: string = question) {
    const asked = text.trim()
    if (!asked) return
    debouncedSearch.cancel()
    runSearch(asked)
    look(asked)
  }

  // Which of the three readings have something to show. A pane with nothing in it is hidden
  // rather than rendered empty, because an empty column costs a third of the width to say
  // nothing - and the lanes resolve independently, so a blank pane is the normal state for
  // the first few hundred milliseconds rather than an error.
  const matches = useMemo(
    () => (filtered ? matchList(filtered) : []),
    [filtered],
  )
  const hits = search?.hits ?? []
  const showFilter = filtered !== null && filtered.matches > 0
  const showSearch = searching || hits.length > 0 || searchError !== null
  const showAnswer =
    loading || answer !== null || error !== null || missing !== null

  return (
    // Wider than the other screens: the browser is two panes side by side, and at the
    // reading width the tree and the rule would each be too narrow to use.
    <div className="max-w-5xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Ask the 2024 SRD</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <AskBox
            value={question}
            onChange={type}
            onAsk={askNow}
            loading={loading}
            placeholder="how does cover work"
          />
          <p className="text-xs text-parchment/45">
            Every word filters the rulebook by heading and searches the rulebook
            and the spell index. To ask a question press Enter or the Ask
            button.
          </p>
          <div className="flex flex-wrap gap-1">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => {
                  // Set through `type` so the example is filtered and searched, then asked
                  // explicitly - the ask is no longer part of typing, and the text is passed
                  // rather than read from state, which has not been updated yet.
                  type(example)
                  askNow(example)
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
          {/* The question, asked as it always was. Given more width than the other two: it
              is the only reading written in sentences, and the two beside it are lists. */}
          {showAnswer && (
            <div className="space-y-4 lg:min-w-0 lg:flex-[1.4]">
              {error != null && <ErrorNotice error={error} onRetry={() => look()} />}

              {missing && (
                <Card className="border-radiant-500/40">
                  <CardHeader>
                    <CardTitle className="text-radiant-400">
                      Not in the SRD
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm text-parchment/70">
                    <p>{missing}</p>
                    <p className="text-xs text-parchment/45">
                      The 2024 SRD is a subset of the 2024 rulebook. Rules that
                      are absent here are reported as absent rather than
                      answered from memory, because a confidently wrong rule is
                      worse than a gap.
                    </p>
                  </CardContent>
                </Card>
              )}

              {(loading || answer) && (
                <Card>
                  <CardHeader className="flex-row items-center justify-between gap-2">
                    <CardTitle className="text-sm">
                      <WandSparklesIcon className="mr-1 inline h-3.5 w-3.5 align-[-0.15em] text-parchment/60" />
                      {answer ? answer.question : "Asking the SRD…"}
                      {loading && (
                        <Loader2Icon className="ml-2 inline h-3.5 w-3.5 animate-spin align-[-0.15em] text-arcane-300" />
                      )}
                    </CardTitle>
                    {answer && <SourceBadge source={answer.source} />}
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {answer && (
                      <Markdown text={answer.answer} className="prose-spell" />
                    )}
                    {answer && answer.citations.length > 0 && (
                      <div className="space-y-1 border-t border-void-800 pt-2">
                        {answer.citations.map((path) => (
                          <p key={path} className="truncate">
                            <RulePathLink path={path} />
                          </p>
                        ))}
                      </div>
                    )}
                    {answer?.from_cache && (
                      <p className="text-xs text-parchment/60">
                        Answered from cache.
                      </p>
                    )}
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {/* The filter's own reading, which is the only one that cannot be wrong: it lists
              where the words are, and it costs no request. `matches` counts headings that
              name the words, which is deliberately not the number of rows - the rows are
              whole paths, kept so the branch says where a rule lives. */}
          {showFilter && filtered && (
            <Card className="lg:min-w-0 lg:flex-1">
              <CardHeader className="flex-row items-center justify-between gap-2">
                <CardTitle className="text-sm">
                  <BookOpenIcon className="mr-1 inline h-3.5 w-3.5 align-[-0.15em] text-parchment/60" />
                  {filterTitle(filtered)}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-parchment/55">
                {filtered.unknown.length > 0 && (
                  <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
                    No heading contains{" "}
                    <span className="font-mono">
                      {filtered.unknown.join('", "')}
                    </span>
                    , so nothing was required of it.
                  </p>
                )}
                {filtered.partial && (
                  <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
                    No heading names all of{" "}
                    <span className="font-mono">
                      {filtered.terms.join('", "')}
                    </span>
                    , so these are the closest headings rather than the answer.
                  </p>
                )}
                {filtered.truncated && (
                  <p className="rounded-md border border-radiant-500/40 bg-radiant-500/10 px-2 py-1 text-radiant-400">
                    More than {filtered.limit} matched; the first{" "}
                    {filtered.limit} are shown.
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

              Rendered by the same component the contextual drawer uses, so a hit read
              beside a rule cannot disagree with the same hit read beside a book. The card
              owns the one list in the API's order, the preview line and the rule/spell
              opening, because those are properties of the response rather than of this
              screen. */}
          {showSearch && (
            <IndexHitsPanel
              className="lg:min-w-0 lg:flex-1"
              result={search}
              searching={searching}
              error={searchError}
            />
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
          <span className="font-mono">{filtered.unknown.join('", "')}</span>, so
          nothing was required of it. A rule can still exist under a different
          name — the other two readings are the ones to check.
        </p>
      )}

      {/* A spell or a rule the reader opened by link, or the rule the answer above is about.
          Full width and outside the grid, because it is a *document* rather than one of the
          three readings of a question: a spell card is as long as the spell, and squeezing it
          into a third of the width would put its own text beside the answer about it. */}
      {spell && <SpellCard spell={spell} />}

      {/* A class context file, opened by a link in an answer. Full width for the same reason
          a spell is: it is a document, not one of the three readings of the question. */}
      {contextPath && (
        <>
          {classLoading && (
            <p className="flex items-center gap-2 text-sm text-parchment/60">
              <Loader2Icon className="h-4 w-4 animate-spin" />
              Fetching the class rules…
            </p>
          )}
          {classError != null && <ErrorNotice error={classError} />}
          {classDocument && <ClassContextCard document={classDocument} />}
        </>
      )}

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
                {filtered.matches === 1 ? "" : "s"} — the tree below is the
                whole rulebook again, so there is still somewhere to look.
              </p>
            )}
            {srdLoading && (
              <p className="flex items-center gap-2 text-sm text-parchment/60">
                <Loader2Icon className="h-4 w-4 animate-spin" />
                Reading the rulebook…
              </p>
            )}
            {srdError != null && <ErrorNotice error={srdError} compact />}
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
                <Loader2Icon className="h-4 w-4 animate-spin" />
                Fetching the rule…
              </p>
            )}
            {sectionError != null && <ErrorNotice error={sectionError} />}
            {section && <SrdCard section={section} documents={documents} />}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
