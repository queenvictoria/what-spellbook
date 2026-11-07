/**
 * Narrowing the vendored SRD's table of contents to the headings that mention what was typed.
 *
 * A keyword filter, not a search: it reads headings and nothing else. A rule's text is not in
 * the table of contents - it is fetched per section - so this cannot match a phrase that
 * appears only in a body, and it does not try. What it is for is the other half of the ask
 * box: "where in the rulebook is this a *named* rule" is answerable from headings alone, and
 * answering it costs no request.
 *
 * ## Why this is not a substring test
 *
 * Two things were measured against the live corpus (1274 headings) while building it, and
 * both changed the design:
 *
 *  - **A question is not a keyword.** Requiring every word of `how does cover work` to appear
 *    in a heading's path matched *nothing*: "how", "does" and "work" are not rulebook
 *    vocabulary, so the one word that mattered was thrown away with them. Hence `STOPWORDS`,
 *    and hence the honest reporting of what was ignored.
 *  - **Rarity in the headings is not rarity in English.** Weighting terms by how few headings
 *    contain them scores "work" (1 heading) as nine times more informative than "cover"
 *    (9 headings), which is exactly backwards in a question. The words a question can afford
 *    to lose are its *function* words, and only a stop list knows which those are.
 *
 * Words that no heading contains ("stabilize", "privilege") are reported as `unknown` rather
 * than counted as misses, because "the SRD never names this" is a different finding from "I
 * matched nothing", and only one of them means the rule is absent.
 *
 * Matching is on word prefixes once a term is four characters or longer, so "grapple" finds
 * **Grappled** and "rest" finds **Rests** - what a reader typing a stem expects. Below that
 * length it is an exact word comparison, so "a" cannot match every heading containing one.
 *
 * ## The branch is kept, not just the match
 *
 * A matching heading has to stay reachable, and in this corpus it is usually a deep one -
 * **Cover** is three levels under *Playing the Game*, and **Grappled [Condition]** four under
 * *Rules Glossary*. Dropping the ancestry would take away the instructions for what a reader
 * is looking at: "Prone" alone does not say it is a condition rather than an action. So the
 * whole path to every match is retained, the match is marked, and that mark is what tells the
 * tree which menus to expand.
 */

import type { SrdDocument, SrdHeading } from '@/api/types'
import { documentSections } from '@/lib/srd'

/**
 * How many matches the tree will build before it stops adding to the list.
 *
 * A cap rather than a promise: "creature" is a heading word in a dozen places and a path word
 * in hundreds, so a short query can legitimately name more headings than anyone will read.
 * It is reported when it bites (`truncated`) instead of applied quietly, because the count
 * above the tree is the thing the reader trusts.
 */
const MATCH_LIMIT = 40

/**
 * Words a question can lose without losing its meaning.
 *
 * Function words, question words, and the handful of generic verbs a rule question is phrased
 * with - "how does X **work**", "what **happens** when I Y". Each of those is common English
 * and rare in a heading, so a corpus-frequency measure rates them as informative and drops
 * the actual subject instead. This list is the only thing that knows the difference.
 *
 * Deliberately not exhaustive. A word wrongly stopped is a word that cannot be matched on,
 * so the list holds only words that are never a rulebook subject on their own - "use", "make"
 * and "range" are all real headings and are all absent from it.
 */
const STOPWORDS = new Set([
  // Articles, conjunctions, prepositions, pronouns.
  'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'than', 'that', 'this', 'these',
  'those', 'there', 'their', 'them', 'they', 'it', 'its', 'of', 'in', 'on', 'at', 'to',
  'for', 'from', 'with', 'without', 'about', 'into', 'over', 'under', 'by', 'as', 'so',
  'such', 'i', 'me', 'my', 'we', 'our', 'you', 'your', 'he', 'she', 'his', 'her', 'him',
  'us', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'can', 'could', 'should',
  'would', 'will', 'shall', 'may', 'might', 'must', 'not', 'no', 'any', 'all', 'some',
  // Question words.
  'how', 'what', 'when', 'where', 'why', 'which', 'who', 'whom', 'whose', 'do', 'does',
  'did', 'doing', 'done',
  // The generic verbs a rule question is built from. None of these is a heading subject.
  'work', 'works', 'worked', 'working', 'happen', 'happens', 'happened', 'mean', 'means',
  'meant', 'say', 'says', 'said', 'explain', 'explains', 'tell', 'give', 'gives', 'given',
  'get', 'gets', 'got', 'make', 'makes', 'made', 'take', 'takes', 'taken', 'know', 'knows',
  'want', 'wants', 'need', 'needs', 'go', 'goes', 'come', 'comes', 'let', 'lets', 'see',
  'look', 'looks', 'please', 'like', 'really', 'actually', 'just', 'also',
])

/** One heading, with the ancestry that makes it findable and whether it is a match. */
export interface FilteredHeading {
  text: string
  level: number
  slug: string
  /** This heading is one of the matches, as opposed to merely being on the way to one. */
  matched: boolean
  children: FilteredHeading[]
}

/** A file, kept when its title matches or it holds at least one matching heading. */
export interface FilteredDocument {
  name: string
  title: string
  /**
   * The file's own title matched, which is not the same as a heading inside it matching. The
   * file row is itself a link - clicking it opens the whole document - so a query that names
   * a file ("equipment") has to keep that row. When it is set the headings are deliberately
   * not walked at all: every heading in `equipment.md` has "Equipment" as an ancestor, so
   * treating the title as ordinary context would return all 134 of them for a query the file
   * row had already answered.
   */
  matched: boolean
  headings: FilteredHeading[]
}

/** What the filter found, and how much of it is being claimed. */
export interface SrdFilter {
  /** The words actually matched on: the query's own words, less the stop words. */
  terms: string[]
  /** Stop words dropped, so the UI can say what it ignored rather than silently dropping it. */
  ignored: string[]
  /** Terms no heading contains, so "nothing matched" is not read as "the rule is absent". */
  unknown: string[]
  documents: FilteredDocument[]
  /** Headings carrying every term that could be matched - or, failing that, the closest. */
  matches: number
  /** Rendered rows: the matches plus every heading on the path down to them. */
  sections: number
  /**
   * Not every term could be matched, so the rows are the closest headings, not the answer.
   *
   * The screen says so. A filter that quietly softens its own rule is how a reader concludes
   * a rule is absent from the corpus when their phrasing was merely unusual.
   */
  partial: boolean
  /** More matched than `limit`; only the first are shown. */
  truncated: boolean
  /** The cap that applied, so the message about it cannot disagree with the code. */
  limit: number
}

/**
 * Split a raw query into the words to match on.
 *
 * Punctuation is dropped rather than split on with a character class, so an apostrophe or a
 * hyphen marks a word boundary instead of becoming part of a term, and a contraction is read
 * as its two halves. Single characters are dropped with them: "I'm" contributes an "m" that
 * would otherwise match the *(M)* in **Material (M)**, and no heading subject in the corpus is
 * one letter long - the component is reached by typing "material".
 */
export function filterTerms(raw: string): string[] {
  return raw
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}\s]+/gu, ' ')
    .split(/\s+/)
    .filter((word) => word.length > 1)
}

/**
 * The SRD narrowed to the paths worth showing for `raw`.
 *
 * Returns `null` for an empty query, which the tree reads as "not filtering", so an
 * unfiltered browse and a filter that happens to match everything cannot be confused.
 */
export function filterDocuments(documents: SrdDocument[], raw: string): SrdFilter | null {
  const words = filterTerms(raw)
  if (words.length === 0) return null

  // A query of nothing but stop words is almost always a one-word query that happens to be on
  // the list - "work", "rest", "cover" if it ever joins them. Dropping every word would leave
  // nothing to match on, so the list is abandoned rather than the query.
  const meaningful = words.filter((word) => !STOPWORDS.has(word))
  const terms = meaningful.length > 0 ? meaningful : words
  const ignored = words.filter((word) => !terms.includes(word))

  const index = buildIndex(documents)
  // An unknown term is a finding, not a filter. Matching "nonexistentword" as a required term
  // is what returns "0 headings" - true and useless - while the word's presence in no heading
  // at all is the actual answer, which the card states. So no term is required when the query
  // is made entirely of words the corpus never writes.
  const unknown = terms.filter((term) => !index.words.has(term))
  const required = unknown.length === terms.length ? [] : terms.filter((term) => !unknown.includes(term))
  const useless = required.length === 0 && unknown.length > 0

  const candidates: Candidate[] = []
  const fileMatches = new Set<string>()

  for (const document of documents) {
    // `matchesAll` is vacuously true for an empty term list, so the guard is not decorative:
    // without it a query made only of words the corpus never writes would match all seven
    // files - the opposite of the finding, which is that it matches nothing.
    if (required.length > 0 && matchesAll(document.title, required)) {
      fileMatches.add(document.name)
      continue
    }
    // The file's own title is part of every heading's trail and is a real part of the path -
    // "Spellcasting" under *Spell Descriptions* lives in a file called Spells - so a word that
    // only ever appears in the title still keeps the branches below it.
    walk(documentSections(document), document.name, document.title, required, [], candidates)
  }

  const exact = candidates.filter((candidate) => candidate.score === required.length)
  const chosen = useless ? [] : exact.length > 0 ? exact : closest(candidates, required)
  // Set from what was actually chosen, not from the fact that no exact match existed: a
  // fallback can itself be too weak to report (`closest` refuses a single term in common), and
  // claiming "these are the closest headings" over an empty list would contradict the "no
  // heading matches" title rendered directly above it.
  const partial = chosen.length > 0 && exact.length === 0 && required.length > 0
  const truncated = chosen.length > MATCH_LIMIT
  const kept = truncated ? chosen.slice(0, MATCH_LIMIT) : chosen
  const matched = new Set(kept.map((candidate) => key(candidate.document, candidate.heading.slug)))

  // The paths are rebuilt from the chosen set rather than recalled from the walk, which is
  // what makes a heading that is both a match and an ancestor of another match render once.
  const out: FilteredDocument[] = []
  for (const document of documents) {
    if (fileMatches.has(document.name)) {
      out.push({ name: document.name, title: document.title, matched: true, headings: [] })
      continue
    }
    const headings = select(documentSections(document), matched, document.name)
    if (headings.length === 0) continue
    out.push({ name: document.name, title: document.title, matched: false, headings })
  }

  return {
    terms,
    ignored,
    unknown,
    documents: out,
    matches: kept.length + fileMatches.size,
    sections: out.reduce(
      (total, document) => total + count(document.headings) + (document.matched ? 1 : 0),
      0,
    ),
    partial,
    truncated,
    limit: MATCH_LIMIT,
  }
}

/** One heading the query named, flattened out of its document. */
export interface SrdMatch {
  document: string
  /** The file's title, for a reader scanning matches across files. */
  title: string
  text: string
  slug: string
  /** `0` for a file-level match, where the row is the document itself. */
  level: number
  /**
   * The headings above this one, outermost first, ending with the file's title.
   *
   * Carried because it is the one thing flattening the tree would otherwise lose: "Cover"
   * alone appears in two files and means a different rule in each, and the trail is what
   * tells them apart without expanding anything. The tree still shows the same information
   * as indentation; this is the version that survives being put in a list.
   */
  path: string[]
}

/**
 * Just the headings the query named, in reading order, with no ancestors of their own.
 *
 * Deliberately not the tree. The tree answers "where does this rule live", which is why it
 * keeps the whole path and opens the branches down to the match; this answers "which headings
 * name my words", which is the only question a scan of a list can answer faster than the tree
 * can. A match is worth marking *and* worth listing: the tree buries the mark under its own
 * context, so the count and the list are what a reader checks before reading anything.
 *
 * Depth-first, because that is the order the rulebook is in - and because `select` emits an
 * ancestor before its children, so a heading that is both a match and a path to another match
 * appears once, in the position the file puts it.
 */
export function matchList(filter: SrdFilter): SrdMatch[] {
  const out: SrdMatch[] = []
  for (const document of filter.documents) {
    if (document.matched) {
      // A file match has no heading of its own; the row *is* the document.
      out.push({
        document: document.name,
        title: document.title,
        text: document.title,
        slug: '',
        level: 0,
        path: [document.title],
      })
      continue
    }
    collectMatches(document.name, document.title, document.headings, [document.title], out)
  }
  return out
}

function collectMatches(
  document: string,
  title: string,
  headings: FilteredHeading[],
  ancestors: string[],
  out: SrdMatch[],
): void {
  for (const heading of headings) {
    const path = [...ancestors, heading.text]
    if (heading.matched) {
      out.push({
        document,
        title,
        text: heading.text,
        slug: heading.slug,
        level: heading.level,
        path,
      })
    }
    collectMatches(document, title, heading.children, path, out)
  }
}

/**
 * The first path that matched, as the `document:slug` pair the tree marks as selected.
 *
 * The ask box filters *and* opens, because a reader who types two words and hits enter is
 * asking where the rule is - and an expanded tree with the match buried below the fold still
 * makes them find it. Undefined when nothing matched.
 */
export function firstMatch(filter: SrdFilter): { document: string; slug: string } | undefined {
  for (const document of filter.documents) {
    // A file match is answered by the file itself: a reader who typed its name has said which
    // page they want.
    if (document.matched) return { document: document.name, slug: '' }
    const found = firstIn(document.headings)
    if (found) return { document: document.name, slug: found }
  }
  return undefined
}

interface Candidate {
  document: string
  heading: SrdHeading
  /** How many of the required terms appear in the heading, its ancestors or the file name. */
  score: number
}

/**
 * Which words appear in the headings at all.
 *
 * Built once per filter rather than per candidate, because determining that a term is
 * `unknown` is what decides whether it is required - and a term nothing contains would
 * otherwise have to be searched for once per heading.
 */
function buildIndex(documents: SrdDocument[]): { words: Set<string> } {
  const words = new Set<string>()
  const add = (text: string) => {
    for (const token of filterTerms(text)) {
      words.add(token)
      // The bare token is added as well as the token, so a term shorter than the prefix
      // threshold is looked up exactly while a longer one can still prefix-match.
      for (let length = 4; length < token.length; length++) words.add(token.slice(0, length))
    }
  }
  for (const document of documents) {
    add(document.title)
    collect(documentSections(document), add)
  }
  return { words }
}

function collect(headings: SrdHeading[], add: (text: string) => void): void {
  for (const heading of headings) {
    add(heading.text)
    collect(heading.children, add)
  }
}

/** Whether every term appears in a heading's text, on the same prefix rule as `matchesAll`. */
function matchesAll(text: string, terms: string[]): boolean {
  const tokens = filterTerms(text)
  return terms.every((term) => tokens.some((token) => isTerm(token, term)))
}

/** Prefix matching above four characters, exact below it. See the module comment. */
function isTerm(token: string, term: string): boolean {
  return term.length >= 4 ? token.startsWith(term) : token === term
}

function walk(
  headings: SrdHeading[],
  document: string,
  title: string,
  terms: string[],
  ancestors: string[],
  out: Candidate[],
): void {
  const inherited = [title, ...ancestors]
  for (const heading of headings) {
    const path = [...inherited, heading.text]
    const score = terms.filter((term) =>
      path.some((part) => filterTerms(part).some((token) => isTerm(token, term))),
    ).length
    if (score > 0) out.push({ document, heading, score })
    walk(heading.children, document, title, terms, [...inherited, heading.text], out)
  }
}

/** The candidates that account for the most terms, when none account for all of them. */
function closest(candidates: Candidate[], terms: string[]): Candidate[] {
  if (terms.length === 0) return []
  const top = candidates.reduce((best, candidate) => Math.max(best, candidate.score), 0)
  // A single term in common is not a partial match, it is noise: "how does cover work" keeps
  // "work" out of the stop list's way and would otherwise return Second-Story Work beside
  // Cover. Half the terms is the floor, rounded up so a two-word query needs both.
  const floor = Math.ceil(terms.length / 2)
  if (top < floor) return []
  return candidates.filter((candidate) => candidate.score === top)
}

/** Pass two: keep a heading when it is a match, or is on the path down to one. */
function select(
  headings: SrdHeading[],
  matched: Set<string>,
  document: string,
): FilteredHeading[] {
  const kept: FilteredHeading[] = []
  for (const heading of headings) {
    const children = select(heading.children, matched, document)
    const isMatch = matched.has(key(document, heading.slug))
    if (!isMatch && children.length === 0) continue
    kept.push({
      text: heading.text,
      level: heading.level,
      slug: heading.slug,
      matched: isMatch,
      children,
    })
  }
  return kept
}

function key(document: string, slug: string): string {
  return `${document}:${slug}`
}

function firstIn(headings: FilteredHeading[]): string | undefined {
  for (const heading of headings) {
    if (heading.matched) return heading.slug
    const found = firstIn(heading.children)
    if (found) return found
  }
  return undefined
}

function count(headings: FilteredHeading[]): number {
  return headings.reduce((total, heading) => total + 1 + count(heading.children), 0)
}
