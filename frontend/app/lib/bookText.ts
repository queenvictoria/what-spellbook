/**
 * Preparing a generated book's markdown for display.
 *
 * **This is now a legacy path.** A book generated in the delimited format arrives with its
 * title and picks already separated - `name` and `picks` on the book, `preamble` and
 * `pairings` on the generation - so there is nothing left to strip. What remains here is for
 * the runs stored before that format existed, whose title and pick list are still inside
 * `book.text` because the old format had nowhere else to put them. It can go once those runs
 * are cleaned out.
 *
 * The model used to open every book with its own title and its pick lists:
 *
 *     **Book 1 — “Peel, Stabilize, Patch”**
 *
 *     **Cantrips:** Thorn Whip, Spare the Dying, Mending
 *     **Level 1 Rituals:** Find Familiar, Unseen Servant
 *
 *     **How to use**
 *     - **Thorn Whip** is the combat peel: ...
 *
 * The panel renders all of that itself — the name in the card title, the picks as linked
 * badges the reader can click — so leaving it in the prose shows the same three things twice,
 * in a worse form.
 *
 * Kept in `lib/` rather than beside the component for the same reason `spellText.ts` is: a
 * module exporting a component and a plain function cannot be hot-reloaded without discarding
 * the page, and this is pure text handling anyway.
 */

// A book's own title line: `**Book 1 — Name**`, `## Book 1 — Name`, `**Book 1: Name**`.
// Matched on the first non-empty line only - see `withoutBookHeader`.
const TITLE_LINE = /^\s*#{0,4}\s*\*{0,2}\s*Book\s*\d+\s*[—–:-]/

// The delimited format's book marker: `=== BOOK 1 ===`. A delimiter can never be prose, which
// is the whole reason the format changed - the model's summary used to be written in the same
// shape as a book heading (`**Book 3 pairs with:**`) and was read as one.
const DELIMITED_BOOK = /^\s*={2,}\s*BOOK\s*\d+\s*={2,}\s*$/im

// A pick label: `**Cantrips:**`, `**Level 1 Rituals:**`, `- **Level 1 rituals:** ...`.
// The vocabulary is `backend/libs/spells.py`'s `_SECTION_NAMES`, and the shape is its
// `_BOOK_HEADING` - the level prefix and a leading bullet are both optional because the model
// writes "- **Rituals:** ..." as often as "**Level 1 Rituals:** ...".
//
// Case-insensitive for the same reason the backend is casefolded there: the model writes
// 'level 1 rituals' as often as 'Rituals', and the stored runs carry both spellings.
const PICK_LABEL =
  /^\s*(?:[-*+]\s+)?(?:\*{1,2}\s*)?(?:Level\s*\d+\s*)?(?:Cantrips?|Rituals?)\s*:?\s*\*{0,2}/i

/**
 * The book's prose, with its title and pick lists removed.
 *
 * Two anchored runs, and nothing else - mirroring `withoutStatLines`, which drops only the
 * leading stat block because a `**Range:**` in the middle of some future spell's description
 * must not be deleted by mistake. The same care applies here: this is model-authored prose,
 * and a book that *discusses* cantrips in its "How to use" section must keep saying so.
 *
 *  1. **The title**, and only on the first non-empty line. Every stored run writes it there -
 *     35 of 35 - and anchoring it means a later line that happens to begin "Book 2" is left
 *     alone. `withTitle: false` keeps it, for a caller that does not render the name itself.
 *  2. **The pick labels**, which are a straight run of label lines immediately after the
 *     title, with blank lines transparent because the model often separates the two lists.
 *     The run stops at the first line that is not a label, which is normally `**How to use**`
 *     or the opening sentence.
 *
 * A *bullet* is deliberately not accepted as part of the run. An earlier version continued the
 * run over bullets, on the theory that a model might write the picks beneath a bare label -
 * but the model writes "- **How to use:** Open with **Mind Sliver** …", which is that same
 * shape and is prose, so five stored books lost their entire body to it. A continuation bullet
 * appears in none of the 35 stored runs, and the asymmetry settles the design: leaving a stray
 * bullet visible is a blemish, and eating a book is not.
 *
 * Returns the text unchanged when neither run is found, so an answer in a shape this does not
 * recognise is shown rather than silently emptied.
 */
export function withoutBookHeader(
  text: string,
  { withTitle = false }: { withTitle?: boolean } = {},
) {
  const lines = text.split('\n')

  // Skip the leading blanks so the title can be tested, but keep them so the prose does not
  // jump to the top of its container.
  let start = 0
  while (start < lines.length && !lines[start].trim()) start++
  if (start >= lines.length) return text

  let end = start
  if (!withTitle && TITLE_LINE.test(lines[start])) end = start + 1

  // The pick run. Blank lines are transparent - the label run is a *run of labels*, not a
  // contiguous block - so a blank line between Cantrips and Rituals does not end it.
  let sawLabel = false
  let lastLabel = end
  for (let i = end; i < lines.length; i++) {
    if (!lines[i].trim()) continue
    if (PICK_LABEL.test(lines[i])) {
      sawLabel = true
      lastLabel = i + 1
      continue
    }
    break
  }
  if (sawLabel) end = lastLabel

  if (end === start) return text

  const kept = [...lines.slice(0, start), ...lines.slice(end)]
  // The removed lines leave their blank neighbours behind, so the gaps collapse back to a
  // single paragraph break.
  return kept.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

// Any book heading, at any depth: `**Book 1 —…**`, `## Book 2 —…`, `**Book 3: …**`.
const BOOK_HEADING = /^\s*#{0,4}\s*\*{0,2}\s*Book\s*\d+/i

/**
 * Only the reasoning that precedes the books in a whole model answer.
 *
 * `Generation.answer` is the model's entire reply - its reasoning, then every book's heading,
 * pick lists and body - and each book is rendered separately by `BookPanel`. Printing the
 * whole thing under "Overall reasoning" therefore shows every book twice, in raw markdown and
 * beside a properly rendered copy.
 *
 * Only the text before the *first* book heading is kept, and the caller is expected to render
 * nothing when that is empty. Measured over the 12 stored runs: 4 open with real reasoning and
 * 8 go straight into Book 1, so a card that always renders would be eight parts pure
 * duplication to four parts content.
 */
/**
 * The reasoning that applies to every book, for the "Overall reasoning" card.
 *
 * A delimited answer carries it in `preamble`, so the field is authoritative. A legacy answer
 * has no such field and the text before its first book heading is the reasoning - but that
 * fallback must not run on a delimited answer, because `reasoningOnly` finds no *legacy*
 * heading there and would return the whole reply, rendering every book a second time.
 */
export function preambleOf(generation: { answer: string; preamble?: string }) {
  if (generation.preamble) return generation.preamble
  if (DELIMITED_BOOK.test(generation.answer)) return ""
  return reasoningOnly(generation.answer)
}

export function reasoningOnly(answer: string) {
  const lines = answer.split('\n')
  const first = lines.findIndex((line) => BOOK_HEADING.test(line))
  if (first === -1) return answer.trim()
  return lines.slice(0, first).join('\n').trim()
}
