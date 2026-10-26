/**
 * Renders the small markdown subset the model actually emits.
 *
 * Deliberately hand-written rather than pulling in a full markdown library: the
 * generated books use only headings, bold, lists and paragraphs, and a general parser
 * would need `dangerouslySetInnerHTML` to show the result - which would put raw model
 * output into the page as HTML. Here the text is escaped by React and stays text.
 */

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
 * Bold, then italics. Bold runs first so `**Name**` is not consumed as two italics.
 * The result is a plain string or a list of nodes, never HTML.
 */
function inline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).filter(Boolean)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="rounded bg-void-800 px-1 py-0.5 text-arcane-300">
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={i}>{part.slice(1, -1)}</em>
    }
    return part
  })
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks = toBlocks(text)
  return (
    <div className={className}>
      {blocks.map((block, i) => {
        if (block.kind === 'heading') {
          return (
            <h3 key={i} className="mt-4 mb-1 text-sm font-semibold text-arcane-300">
              {inline(block.items[0])}
            </h3>
          )
        }
        if (block.kind === 'list') {
          return (
            <ul key={i} className="my-2 list-disc space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item)}</li>
              ))}
            </ul>
          )
        }
        if (block.kind === 'ordered') {
          return (
            <ol key={i} className="my-2 list-decimal space-y-1 pl-5">
              {block.items.map((item, j) => (
                <li key={j}>{inline(item)}</li>
              ))}
            </ol>
          )
        }
        return (
          <p key={i} className="my-2">
            {inline(block.items[0])}
          </p>
        )
      })}
    </div>
  )
}
