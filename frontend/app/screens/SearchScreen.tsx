import { useEffect, useMemo, useState } from "react"
import { Search as SearchIcon, SlidersHorizontal } from "lucide-react"

import { api, ApiError } from "@/api/client"
import type { SearchFacets, SearchParams, SearchResult } from "@/api/types"
import { SearchResults } from "@/components/SearchResults"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

const MODES = [
  {
    value: "vector",
    label: "Vector",
    hint: "Similarity search — what the recommender itself does. Needs text to embed.",
  },
  {
    value: "text",
    label: "Text",
    hint: "Substring scan over the chunk bodies. The only mode that can answer “which chunks mention X”. Empty query lists everything the filters admit.",
  },
  {
    value: "hybrid",
    label: "Hybrid",
    hint: "The vector candidates, re-ordered so hits containing the query's words come first. A ranking aid, not a retrieval algorithm.",
  },
] as const

const EXAMPLES = [
  "protect an ally from being grappled",
  "nonmagical armor",
  "a creature made of fire",
]

/**
 * What the search is restricted to.
 *
 * `all` is the default because this is the diagnostic surface: hiding the rulebook by
 * default would make "why is this spell missing" unanswerable. The recommender is the
 * opposite — it names `spell` explicitly, because a rule is not a legal pick.
 */
const DOC_TYPES = [
  { value: "all", label: "Everything", hint: "Spells, magic items and the vendored SRD." },
  { value: "spell", label: "Spells", hint: "The spell corpus only — what the recommender draws from." },
  { value: "item", label: "Items", hint: "The 22 magic items that share the corpus directory." },
  { value: "srd", label: "SRD", hint: "The vendored 2024 rulebook, one row per section." },
] as const

/**
 * Searching the vector index directly.
 *
 * This is the diagnostic surface, not the recommender. `retrieval` answers "what is legal
 * for this character"; this answers "what is in the index, and what does a query bring
 * back" — which is how a missing recommendation gets explained. It can return a spell the
 * character could never pick, on purpose.
 *
 * Three modes, because they fail differently. A vector search that returns nothing means
 * the embedding did not surface it; a text search that returns nothing means the words are
 * not in the corpus. Telling those apart is most of the work, so the mode is explicit
 * rather than inferred, and the response's own `where` clause and `note` are shown — a
 * filter that silently matches nothing is the commonest failure here.
 *
 * The class filter is applied as an `$or` over the exact class-list strings the index
 * stores, because the field is one comma-joined value and Chroma's `$contains` does not
 * match inside it. That is why the filter is a set of checkboxes over real facet values
 * rather than a free-text box: a class the index never uses would match nothing.
 */
export function SearchScreen() {
  const [query, setQuery] = useState("")
  const [mode, setMode] = useState<SearchParams["mode"]>("vector")
  const [classes, setClasses] = useState<string[]>([])
  const [school, setSchool] = useState("")
  const [levelMin, setLevelMin] = useState("")
  const [levelMax, setLevelMax] = useState("")
  const [ritual, setRitual] = useState(false)
  const [spellsOnly, setSpellsOnly] = useState(true)
  const [docType, setDocType] = useState<NonNullable<SearchParams["doc_type"]>>("all")
  const [allTerms, setAllTerms] = useState(true)
  const [showFilters, setShowFilters] = useState(false)

  const [facets, setFacets] = useState<SearchFacets | null>(null)
  const [result, setResult] = useState<SearchResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api
      .searchFacets()
      .then((body) => setFacets(body.facets))
      .catch(() => {
        // The facets only populate the filter controls; a failure here must not stop a
        // search, so it is swallowed rather than shown as a page-level error.
      })
  }, [])

  const params = useMemo<SearchParams>(
    () => ({
      query,
      mode,
      limit: 25,
      classes,
      school: school || undefined,
      level_min: levelMin === "" ? undefined : Number(levelMin),
      level_max: levelMax === "" ? undefined : Number(levelMax),
      ritual: ritual ? true : undefined,
      // The doc-type control is the single source of truth for what is searched, so
      // ``spells_only`` is derived from it rather than set independently. Two controls for
      // one question is how a reader ends up with a filter that silently does nothing.
      spells_only: docType === "all" ? spellsOnly : docType === "spell",
      all_terms: allTerms,
      doc_type: docType,
    }),
    [query, mode, classes, school, levelMin, levelMax, ritual, spellsOnly, allTerms, docType],
  )

  async function run(overrides: Partial<SearchParams> = {}) {
    setLoading(true)
    setError(null)
    try {
      setResult(await api.search({ ...params, ...overrides }))
    } catch (e) {
      setResult(null)
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  // Text mode can browse with no query, so it is the one mode worth running on arrival -
  // an empty page with no explanation is the worst first impression for a diagnostic tool.
  useEffect(() => {
    api
      .search({ mode: "text", limit: 25, spells_only: true })
      .then(setResult)
      .catch(() => {})
  }, [])

  const activeMode = MODES.find((m) => m.value === mode) ?? MODES[0]

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Search the index</CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowFilters((v) => !v)}
            aria-expanded={showFilters}
          >
            <SlidersHorizontal className="h-4 w-4" />
            Filters
            {activeFilterCount(classes, school, levelMin, levelMax, ritual, spellsOnly, docType) >
              0 && (
              <Badge tone="arcane">
                {activeFilterCount(classes, school, levelMin, levelMax, ritual, spellsOnly, docType)}
              </Badge>
            )}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              value={query}
              placeholder={
                mode === "text" ? "words to find (may be empty)" : "describe a spell"
              }
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
            />
            <Button
              onClick={() => run()}
              disabled={loading}
              aria-label="Search"
              className="shrink-0"
            >
              <SearchIcon className="h-4 w-4" />
              <span className="sr-only">Search</span>
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-1">
            {DOC_TYPES.map((option) => (
              <button
                key={option.value}
                onClick={() => setDocType(option.value)}
                title={option.hint}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs transition-colors",
                  docType === option.value
                    ? "border-radiant-500/60 bg-radiant-500/15 text-radiant-400"
                    : "border-void-700 text-parchment/60 hover:text-parchment",
                )}
              >
                {option.label}
                {facets && (
                  <span className="ml-1 text-parchment/35">
                    {option.value === "all"
                      ? facets.chunks
                      : (facets.doc_types.find((f) => f.value === option.value)?.count ?? 0)}
                  </span>
                )}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-1">
            {MODES.map((option) => (
              <button
                key={option.value}
                onClick={() => setMode(option.value)}
                title={option.hint}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs transition-colors",
                  mode === option.value
                    ? "border-arcane-500/60 bg-arcane-500/15 text-arcane-300"
                    : "border-void-700 text-parchment/60 hover:text-parchment",
                )}
              >
                {option.label}
              </button>
            ))}
            <span className="ml-1 text-xs text-parchment/45">{activeMode.hint}</span>
          </div>

          {mode === "text" && (
            <label className="flex items-center gap-2 text-xs text-parchment/60">
              <input
                type="checkbox"
                checked={allTerms}
                onChange={(e) => setAllTerms(e.target.checked)}
              />
              Require every word (off: any word matches)
            </label>
          )}

          <div className="flex flex-wrap gap-1">
            {EXAMPLES.map((example) => (
              <button
                key={example}
                onClick={() => {
                  setQuery(example)
                  run({ query: example })
                }}
                className="rounded-full border border-void-700 px-2 py-0.5 text-[0.7rem] text-parchment/60 hover:text-parchment"
              >
                {example}
              </button>
            ))}
          </div>

          {showFilters && (
            <Filters
              facets={facets}
              classes={classes}
              setClasses={setClasses}
              school={school}
              setSchool={setSchool}
              levelMin={levelMin}
              setLevelMin={setLevelMin}
              levelMax={levelMax}
              setLevelMax={setLevelMax}
              ritual={ritual}
              setRitual={setRitual}
              spellsOnly={spellsOnly}
              setSpellsOnly={setSpellsOnly}
              docType={docType}
            />
          )}
        </CardContent>
      </Card>

      {error && (
        <Card className="border-red-500/40">
          <CardContent className="pt-4 text-sm text-red-300">{error}</CardContent>
        </Card>
      )}

      {/* The same results list the Rules tab's ask box shows. Kept bespoke here only in the
          empty-state wording, because this tab can be browsed with no query at all and
          "nothing matched" would blame the reader for an empty box. */}
      {result && (
        <SearchResults
          result={result}
          emptyMessage="Nothing matched. Try a different mode or fewer filters."
        />
      )}
    </div>
  )
}

/** How many filters are narrowing the search, for the badge on the toggle. */
function activeFilterCount(
  classes: string[],
  school: string,
  levelMin: string,
  levelMax: string,
  ritual: boolean,
  spellsOnly: boolean,
  docType: string,
) {
  return (
    classes.length +
    (school ? 1 : 0) +
    (levelMin !== "" ? 1 : 0) +
    (levelMax !== "" ? 1 : 0) +
    (ritual ? 1 : 0) +
    (spellsOnly ? 0 : 1) +
    (docType !== "all" ? 1 : 0)
  )
}

/** The filter controls, populated from the index's own facets. */
function Filters({
  facets,
  classes,
  setClasses,
  school,
  setSchool,
  levelMin,
  setLevelMin,
  levelMax,
  setLevelMax,
  ritual,
  setRitual,
  spellsOnly,
  setSpellsOnly,
  docType,
}: {
  facets: SearchFacets | null
  classes: string[]
  setClasses: (value: string[]) => void
  school: string
  setSchool: (value: string) => void
  levelMin: string
  setLevelMin: (value: string) => void
  levelMax: string
  setLevelMax: (value: string) => void
  ritual: boolean
  setRitual: (value: boolean) => void
  spellsOnly: boolean
  setSpellsOnly: (value: boolean) => void
  docType: string
}) {
  const toggleClass = (name: string) =>
    setClasses(
      classes.includes(name)
        ? classes.filter((c) => c !== name)
        : [...classes, name],
    )

  return (
    <div className="space-y-3 rounded-md border border-void-800 p-3">
      <div>
        <p className="mb-1 text-xs font-medium text-parchment/70">
          Class — matches any of the selected
        </p>
        <div className="flex flex-wrap gap-1">
          {(facets?.classes ?? []).map((facet) => (
            <button
              key={facet.value}
              onClick={() => toggleClass(facet.value)}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[0.7rem] transition-colors",
                classes.includes(facet.value)
                  ? "border-arcane-500/60 bg-arcane-500/15 text-arcane-300"
                  : "border-void-700 text-parchment/60 hover:text-parchment",
              )}
            >
              {facet.value} <span className="text-parchment/35">{facet.count}</span>
            </button>
          ))}
          {!facets && <span className="text-xs text-parchment/45">Loading…</span>}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-parchment/70">
          <span className="mb-1 block">School</span>
          <select
            value={school}
            onChange={(e) => setSchool(e.target.value)}
            className="h-8 rounded-md border border-void-700 bg-void-950/70 px-2 text-xs text-parchment"
          >
            <option value="">Any</option>
            {(facets?.schools ?? []).map((facet) => (
              <option key={facet.value} value={facet.value}>
                {facet.value} ({facet.count})
              </option>
            ))}
          </select>
        </label>

        <label className="text-xs text-parchment/70">
          <span className="mb-1 block">Level from</span>
          <Input
            type="number"
            min={0}
            max={9}
            value={levelMin}
            onChange={(e) => setLevelMin(e.target.value)}
            className="h-8 w-20"
          />
        </label>
        <label className="text-xs text-parchment/70">
          <span className="mb-1 block">to</span>
          <Input
            type="number"
            min={0}
            max={9}
            value={levelMax}
            onChange={(e) => setLevelMax(e.target.value)}
            className="h-8 w-20"
          />
        </label>

        <label className="flex items-center gap-2 text-xs text-parchment/70">
          <input
            type="checkbox"
            checked={ritual}
            onChange={(e) => setRitual(e.target.checked)}
          />
          Ritual only
        </label>
        {/* Disabled while a doc type is chosen, because the two are the same question at
            different resolutions and the server lets doc_type win. Leaving it live would
            offer a control that silently does nothing. */}
        <label
          className={cn(
            "flex items-center gap-2 text-xs",
            docType === "all" ? "text-parchment/70" : "text-parchment/35",
          )}
          title={
            docType === "all"
              ? "Exclude the 22 magic items that share the corpus directory"
              : "Ignored while a document type is selected"
          }
        >
          <input
            type="checkbox"
            checked={spellsOnly}
            disabled={docType !== "all"}
            onChange={(e) => setSpellsOnly(e.target.checked)}
          />
          Spells only
        </label>
      </div>

      {facets && (
        <p className="text-[0.7rem] text-parchment/40">
          The index holds {facets.spells} spells and {facets.rituals} rituals across{" "}
          {facets.chunks} chunks
          {facets.doc_types.length > 0 && (
            <>
              {" — "}
              {facets.doc_types
                .map((facet) => `${facet.count} ${facet.value}`)
                .join(", ")}
            </>
          )}
          .
        </p>
      )}
    </div>
  )
}