/**
 * Renders the small markdown subset this project actually emits and stores.
 *
 * Deliberately hand-written rather than pulling in a full markdown library: the generated
 * books use only headings, bold, lists and paragraphs, and a general parser would need
 * `dangerouslySetInnerHTML` to show the result - which would put raw model output into the
 * page as HTML. Here the text is escaped by React and stays text.
 *
 * The vendored SRD widened the subset in three ways, each because the rulebook uses it and
 * dropping it would show a rule with its content missing:
 *
 * - **Tables.** The numbers in a table *are* the rule - `### Cover`'s prose only says "as
 *   detailed in the Cover table" - so a renderer that skipped tables would show a confident
 *   rule with its bonuses absent. The backend converts the SRD's HTML tables to pipe tables
 *   (`srd.to_markdown`), and the corpus already contains 107 files with pipe tables.
 * - **Blockquotes.** The SRD boxes sidebars and variant rules in them, and some contain
 *   their own heading (`> ### Breaking Your Oath`), so a quote is rendered recursively
 *   rather than flattened to a paragraph.
 * - **Heading levels.** Books use `###` for a book title and nothing else, so one size was
 *   enough. A document browser needs the nesting visible, or `#### Attack [Action]` reads
 *   as a sibling of `## Actions`.
 */

import { SpellLink } from "@/components/SpellLink"
import { splitSpells, useSpellNames } from "@/lib/spellNames"

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "ordered"; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "rule" }
  | { kind: "table"; header: string[]; rows: string[][] }

const HEADING = /^(#{1,6})\s+(.*)$/
// `•` is not a Markdown bullet, but the SRD's conversion uses it for 31 lines across
// `classes.md`, `spells.md` and `gameplay-toolbox.md`. Without it those lists render as
// paragraphs with a stray dot in front of each item.
const BULLET = /^[-*•]\s+(.*)$/
const ORDERED = /^\d+[.)]\s+(.*)$/
const RULE = /^(?:-{3,}|\*{3,}|_{3,})$/
const QUOTE = /^>\s?(.*)$/
const TABLE_ROW = /^\|/
const TABLE_SEPARATOR = /^\|[\s:|-]+\|?$/

/**
 * One pipe-table row as cells.
 *
 * A cell may contain an escaped pipe (`\|`), which the backend writes when a rule's own
 * text contains one, so the split has to respect the escape rather than splitting on every
 * `|`.
 */
function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "")
  return trimmed
    .split(/(?<!\\)\|/)
    .map((cell) => cell.trim().replace(/\\\|/g, "|"))
}

/** Split into blocks, keeping list runs together so an ordered list stays one run. */
function toBlocks(text: string): Block[] {
  const blocks: Block[] = []
  const lines = text.split("\n")
  let list: Block | null = null

  const endList = () => {
    if (list) blocks.push(list)
    list = null
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd()

    // A table is only a table when a separator row follows the header. A lone line
    // starting with `|` is prose that happens to begin with a pipe, and treating it as a
    // table would swallow the paragraph around it.
    if (
      TABLE_ROW.test(line.trim()) &&
      TABLE_SEPARATOR.test((lines[i + 1] ?? "").trim())
    ) {
      endList()
      const header = splitRow(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && TABLE_ROW.test(lines[i].trim())) {
        rows.push(splitRow(lines[i]))
        i++
      }
      // The loop leaves `i` on the first non-row line, and the outer `i++` would skip it.
      i--
      blocks.push({ kind: "table", header, rows })
      continue
    }

    const quote = QUOTE.exec(line)
    if (quote) {
      endList()
      const body: string[] = [quote[1]]
      while (i + 1 < lines.length) {
        const next = QUOTE.exec(lines[i + 1])
        if (!next) break
        body.push(next[1])
        i++
      }
      blocks.push({ kind: "quote", text: body.join("\n") })
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      endList()
      blocks.push({
        kind: "heading",
        level: heading[1].length,
        text: heading[2],
      })
      continue
    }

    if (RULE.test(line.trim())) {
      endList()
      blocks.push({ kind: "rule" })
      continue
    }

    const bullet = BULLET.exec(line.trim())
    if (bullet) {
      if (list?.kind !== "list") {
        endList()
        list = { kind: "list", items: [] }
      }
      list.items.push(bullet[1])
      continue
    }

    const ordered = ORDERED.exec(line.trim())
    if (ordered) {
      if (list?.kind !== "ordered") {
        endList()
        list = { kind: "ordered", items: [] }
      }
      list.items.push(ordered[1])
      continue
    }

    if (!line.trim()) {
      endList()
      continue
    }

    endList()
    blocks.push({ kind: "paragraph", text: line })
  }
  endList()
  return blocks
}

/**
 * Bold, then italics. Bold runs first so `**Name**` is not consumed as two italics.
 * The result is a plain string or a list of nodes, never HTML.
 *
 * Underscore italics are supported because the SRD writes them that way - every spell's
 * stats line is `_Level 3 Evocation (Sorcerer, Wizard)_`, and without this the vendored
 * text renders with its markup showing. The lookarounds keep a bare underscore inside a
 * word (a filename, an identifier) from being read as emphasis.
 *
 * Spell names are linked inside plain runs *and* inside bold runs, because the books
 * bold the spell they are recommending - the most useful mention to make clickable is
 * exactly the one that would otherwise be skipped.
 */
function inline(text: string, names: ReadonlySet<string>, linkSpells = true) {
  const parts = text
    .split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|(?<![\w])_[^_\n]+_(?![\w]))/g)
    .filter(Boolean)
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i}>
          {withSpells(part.slice(2, -2), names, i, linkSpells)}
        </strong>
      )
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          className="rounded bg-void-800 px-1 py-0.5 text-arcane-300"
        >
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return (
        <em key={i}>{withSpells(part.slice(1, -1), names, i, linkSpells)}</em>
      )
    }
    if (part.startsWith("_") && part.endsWith("_")) {
      return (
        <em key={i}>{withSpells(part.slice(1, -1), names, i, linkSpells)}</em>
      )
    }
    return withSpells(part, names, i, linkSpells)
  })
}

/** A plain run with any spell names in it turned into links. */
function withSpells(
  text: string,
  names: ReadonlySet<string>,
  key: number,
  linkSpells: boolean,
) {
  if (!linkSpells) return text
  const parts = splitSpells(text, names)
  if (parts.length === 1 && !parts[0][1]) return text
  return parts.map(([chunk, isSpell], i) =>
    isSpell ? <SpellLink key={`${key}-${i}`} name={chunk} /> : chunk,
  )
}

/**
 * The element a heading level maps to.
 *
 * Offset by one so a document's `#` title is an `h2` on the page: the screen already has an
 * `h1`, and a second one would make the document look like a new page rather than a section
 * of this one.
 */
const HEADING_TAG = ["h2", "h3", "h4", "h5", "h6", "h6"] as const

export function Markdown({
  text,
  className,
  linkSpells = true,
}: {
  text: string
  className?: string
  /** Off when the text *is* a spell, so its own title does not link back to itself. */
  linkSpells?: boolean
}) {
  const names = useSpellNames()
  const blocks = toBlocks(text)
  return (
    <div className={className}>
      {blocks.map((block, i) => {
        if (block.kind === "heading") {
          const Tag = HEADING_TAG[Math.min(block.level, 6) - 1]
          return (
            <Tag
              key={i}
              className="mt-4 mb-1 text-sm font-semibold text-arcane-300"
            >
              {inline(block.text, names, linkSpells)}
            </Tag>
          )
        }
        if (block.kind === "list") {
          return (
            <ul key={i} className="my-2 list-disc space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, names, linkSpells)}</li>
              ))}
            </ul>
          )
        }
        if (block.kind === "ordered") {
          return (
            <ol key={i} className="my-2 list-decimal space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, names, linkSpells)}</li>
              ))}
            </ol>
          )
        }
        if (block.kind === "quote") {
          return (
            <blockquote
              key={i}
              className="my-3 border-l-2 border-arcane-500/50 pl-3 text-parchment/75"
            >
              {/* Recursive, because an SRD sidebar can contain its own heading and list -
                  flattening it to a paragraph would lose the structure that makes it
                  readable. */}
              <Markdown text={block.text} linkSpells={linkSpells} />
            </blockquote>
          )
        }
        if (block.kind === "rule") {
          return <hr key={i} className="my-4 border-void-700" />
        }
        if (block.kind === "table") {
          return (
            <div key={i} className="my-3 overflow-x-auto">
              <table className="w-full border-collapse text-left text-xs">
                <thead>
                  <tr>
                    {block.header.map((cell, j) => (
                      <th
                        key={j}
                        className="border-b border-void-700 px-2 py-1 font-semibold text-parchment"
                      >
                        {inline(cell, names, linkSpells)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, j) => (
                    <tr key={j} className="align-top">
                      {row.map((cell, k) => (
                        <td
                          key={k}
                          className="border-b border-void-800/60 px-2 py-1 text-parchment/80"
                        >
                          {inline(cell, names, linkSpells)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        return (
          <p key={i} className="my-2">
            {inline(block.text, names, linkSpells)}
          </p>
        )
      })}
    </div>
  )
}
