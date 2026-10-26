/**
 * Renders the small markdown subset the model actually emits.
 *
 * Deliberately hand-written rather than pulling in a full markdown library: the
 * generated books use only headings, bold, lists and paragraphs, and a general parser
 * would need `dangerouslySetInnerHTML` to show the result - which would put raw model
 * output into the page as HTML. Here the text is escaped by React and stays text.
 */

import { splitSpells, useSpellNames } from '@/lib/spellNames'

interface Block {
  kind: 'heading' | 'paragraph' | 'list' | 'ordered'
  items: string[]
}

/** Split into blocks, keeping list runs together so an ordered list stays one run. */
function toBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let list: Block | null = null

  const endList = () => {
    if (list) blocks.push(list)
    list = null
  }

  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      endList()
      blocks.push({ kind: 'heading', items: [heading[2]] })
      continue
    }

    const bullet = /^[-*]\s+(.*)$/.exec(line.trim())
    if (bullet) {
      if (list?.kind !== 'list') {
        endList()
        list = { kind: 'list', items: [] }
      }
      list.items.push(bullet[1])
      continue
    }

    const ordered = /^\d+[.)]\s+(.*)$/.exec(line.trim())
    if (ordered) {
      if (list?.kind !== 'ordered') {
        endList()
        list = { kind: 'ordered', items: [] }
      }
      list.items.push(ordered[1])
      continue
    }

    if (!line.trim()) {
      endList()
      continue
    }

    endList()
    blocks.push({ kind: 'paragraph', items: [line] })
  }
  endList()
  return blocks
}

/**
 * A spell mention, rendered as a link into the rules tab.
 *
 * A real `<a href>` rather than a router link, because the rules tab is a separate
 * document in this app's routing and the browser's own navigation is what keeps the
 * back button working.
 */
function SpellLink({ name }: { name: string }) {
  return (
    <a
      href={`/rules?spell=${encodeURIComponent(name)}`}
      className="text-arcane-300 underline decoration-dotted underline-offset-2 hover:text-arcane-200"
      title={`Look up ${name} in the rules`}
    >
      {name}
    </a>
  )
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
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{withSpells(part.slice(2, -2), names, i, linkSpells)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="rounded bg-void-800 px-1 py-0.5 text-arcane-300">
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={i}>{withSpells(part.slice(1, -1), names, i, linkSpells)}</em>
    }
    if (part.startsWith('_') && part.endsWith('_')) {
      return <em key={i}>{withSpells(part.slice(1, -1), names, i, linkSpells)}</em>
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
        if (block.kind === 'heading') {
          return (
            <h3 key={i} className="mt-4 mb-1 text-sm font-semibold text-arcane-300">
              {inline(block.items[0], names, linkSpells)}
            </h3>
          )
        }
        if (block.kind === 'list') {
          return (
            <ul key={i} className="my-2 list-disc space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, names, linkSpells)}</li>
              ))}
            </ul>
          )
        }
        if (block.kind === 'ordered') {
          return (
            <ol key={i} className="my-2 list-decimal space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item, names, linkSpells)}</li>
              ))}
            </ol>
          )
        }
        return (
          <p key={i} className="my-2">
            {inline(block.items[0], names, linkSpells)}
          </p>
        )
      })}
    </div>
  )
}
