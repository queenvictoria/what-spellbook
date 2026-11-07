import { useMemo, useState } from "react"
import { ChevronDown, ChevronRight } from "lucide-react"

import type { SrdDocument, SrdHeading } from "@/api/types"
import type { FilteredDocument, FilteredHeading, SrdFilter } from "@/lib/srdFilter"
import { documentSections, srdHref } from "@/lib/srd"
import { cn } from "@/lib/utils"

/**
 * The vendored SRD as an indented, collapsible list of links.
 *
 * A tree rather than a flat list because the rulebook *is* a tree, and the nesting is the
 * navigation: `#### Attack [Action]` only makes sense under `## Actions`, and a flat list of
 * 1280 headings would be unusable. Collapsed by default at every level below the file,
 * because `spells.md` alone has 379 headings and expanding it would bury the other six
 * files.
 *
 * The links are real `<a href>` elements carrying the section in the query string, so a
 * rule can be bookmarked, opened in a new tab, and reached with the back button. The click
 * handler only intercepts a plain left click - a modified click or a middle click is the
 * reader asking the browser for something else, and swallowing it would break "open in new
 * tab" on the one screen where it is most useful.
 *
 * Pass a `filter` to narrow it to headings mentioning every word of a query. The shapes are
 * separate types on purpose: the unfiltered tree renders `SrdDocument` straight from the
 * API, while the filtered one carries a `matched` flag per heading that decides what to mark.
 * Giving the plain tree those fields would mean inventing them at the call site and having
 * two sources for what a match is.
 *
 * Keyed on the query by the caller, which is load-bearing rather than incidental: a filtered
 * tree opens every branch, and that is state seeded when each node mounts. Remounting on a
 * new query is what lets the matches be visible immediately while still letting a reader
 * close a branch and have it stay closed until they ask something else.
 */
export function SrdTree({
  documents,
  filter,
  selected,
  onSelect,
}: {
  documents: SrdDocument[]
  /**
   * The filtered view of `documents`, or null when nothing is being filtered. When set, its
   * own shape is what renders and `documents` is ignored - the filter has already dropped
   * the paths that do not match, so rendering the unfiltered tree would show them again.
   */
  filter?: SrdFilter | null
  /** `document:slug` of the open section, so the tree can mark where the reader is. */
  selected: string | null
  onSelect: (document: string, slug: string | null) => void
}) {
  const nodes = useMemo<FilteredDocument[]>(
    () =>
      filter?.documents ??
      documents.map((document) => ({
        name: document.name,
        title: document.title,
        matched: false,
        headings: documentSections(document).map(plain),
      })),
    [documents, filter],
  )

  return (
    <ul className="space-y-1 text-sm">
      {nodes.map((document) => (
        <li key={document.name}>
          <FileNode
            // The document's own content is part of the key, so a node remounts when the
            // filter changes what is under it - which is what re-seeds the open state.
            key={`${document.name}:${filter?.terms.join(' ')}`}
            document={document}
            filtering={filter != null}
            selected={selected}
            onSelect={onSelect}
          />
        </li>
      ))}
    </ul>
  )
}

/** The unfiltered tree's nodes, marked as non-matches so one render path serves both. */
function plain(heading: SrdHeading): FilteredHeading {
  return {
    text: heading.text,
    level: heading.level,
    slug: heading.slug,
    matched: false,
    children: heading.children.map(plain),
  }
}

function FileNode({
  document,
  filtering,
  selected,
  onSelect,
}: {
  document: FilteredDocument
  /** A filtered list is drawn open; an unfiltered one starts closed. */
  filtering: boolean
  selected: string | null
  onSelect: (document: string, slug: string | null) => void
}) {
  // Seeded from the mode rather than kept in sync with it, because the whole tree is
  // remounted when the query changes - see the `key` on `SrdTree` - so a collapse the reader
  // chose lasts exactly as long as the question it was chosen for.
  const [open, setOpen] = useState(filtering)
  return (
    <>
      <div className="flex items-center gap-1">
        <Toggle
          open={open}
          onClick={() => setOpen((value) => !value)}
          label={document.title}
        />
        <Link
          href={srdHref(document.name, null)}
          active={selected === `${document.name}:`}
          onClick={() => onSelect(document.name, null)}
          className={cn("font-medium text-parchment", document.matched && MATCH)}
        >
          {document.title}
        </Link>
        <span className="text-[0.7rem] text-parchment/35">
          {count(document.headings)}
        </span>
      </div>
      {open && (
        <ul className="mt-1 space-y-0.5 border-l border-void-800 pl-3">
          {document.headings.map((heading) => (
            <HeadingNode
              key={heading.slug}
              document={document.name}
              heading={heading}
              selecting={filtering}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </>
  )
}

function HeadingNode({
  document,
  heading,
  selecting,
  selected,
  onSelect,
}: {
  document: string
  heading: FilteredHeading
  /**
   * A filtered tree opens every branch, so the match is visible without a click.
   *
   * This is the difference between "expanding nested menus as required" and only opening the
   * first one: **Cover** sits under *Rules Glossary > Rules Definitions*, and a mark on the
   * match is no help if it is two collapsed levels below the fold. Seeded rather than forced,
   * so the toggle still closes a branch - and because the node is remounted when the query
   * changes, that choice lasts exactly as long as the question it was made for.
   */
  selecting: boolean
  selected: string | null
  onSelect: (document: string, slug: string | null) => void
}) {
  // A heading with no children is a leaf, so it gets no toggle - an arrow that expands to
  // nothing is worse than no arrow.
  const [open, setOpen] = useState(selecting)
  const hasChildren = heading.children.length > 0
  return (
    <li>
      <div className="flex items-center gap-1">
        {hasChildren ? (
          <Toggle
            open={open}
            onClick={() => setOpen((value) => !value)}
            label={heading.text}
          />
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <Link
          href={srdHref(document, heading.slug)}
          active={selected === `${document}:${heading.slug}`}
          onClick={() => onSelect(document, heading.slug)}
          className={heading.matched ? MATCH : undefined}
        >
          {heading.text}
        </Link>
      </div>
      {hasChildren && open && (
        <ul className="mt-0.5 space-y-0.5 border-l border-void-800 pl-3">
          {heading.children.map((child) => (
            <HeadingNode
              key={child.slug}
              document={document}
              heading={child}
              selecting={selecting}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

/**
 * A match is marked, not just unreachable.
 *
 * The tree keeps the whole path to a match, so most of what a filter shows is context. Without
 * a mark, a reader looking at six rows would have to guess which one their words actually
 * named - and in this corpus the answer is usually neither the first nor the last.
 */
const MATCH = "font-medium text-arcane-300"

function Toggle({
  open,
  onClick,
  label,
}: {
  open: boolean
  onClick: () => void
  label: string
}) {
  const Icon = open ? ChevronDown : ChevronRight
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
      className="shrink-0 rounded p-0.5 text-parchment/40 hover:bg-void-800 hover:text-parchment"
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  )
}

function Link({
  href,
  active,
  onClick,
  className,
  children,
}: {
  href: string
  active: boolean
  onClick: () => void
  className?: string
  children: React.ReactNode
}) {
  return (
    <a
      href={href}
      onClick={(event) => {
        // Only a plain left click is ours. A modified click, a middle click or a drag is
        // the reader asking the browser for a new tab or window, and the whole point of a
        // real href is that those keep working.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
        if (event.button !== 0) return
        event.preventDefault()
        onClick()
      }}
      className={cn(
        "truncate rounded px-1 py-0.5 hover:bg-void-800 hover:text-parchment",
        active ? "bg-void-800 text-arcane-300" : "text-parchment/70",
        className,
      )}
    >
      {children}
    </a>
  )
}

/** How many headings a file holds, so the tree says how big a branch is before opening it. */
function count(headings: FilteredHeading[]): number {
  return headings.reduce((total, heading) => total + 1 + count(heading.children), 0)
}
