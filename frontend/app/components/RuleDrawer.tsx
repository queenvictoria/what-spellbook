import { useRef, useState } from "react"
import type { ReactNode, RefObject } from "react"
import { X } from "lucide-react"

import { ClassContextCard } from "@/components/ClassContextCard"
import { SrdCard } from "@/components/SrdCard"
import { SrdTree } from "@/components/SrdTree"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
} from "@/components/ui/drawer"
import { useClassContext } from "@/lib/classContext"
import { OpenRuleContext, useAnchorScroll, useOpenRule } from "@/lib/ruleDrawer"
import type { RuleTarget } from "@/lib/ruleDrawer"
import { useSrdDocuments, useSrdSection } from "@/lib/srd"

/**
 * A pull-out panel for reading a rule without leaving the page you were on.
 *
 * The same affordance spells already have, for the same reason: an answer ends with the
 * file it came from, and following that used to mean leaving the answer behind and finding
 * the heading by hand on the Rules tab. The drawer keeps the answer on screen, which is
 * what makes "where did this come from?" a question you can actually answer mid-read.
 *
 * The panel is Base UI's Drawer, so Escape, the focus trap and the `aria-*` wiring come
 * from the primitive rather than being redone here.
 */
export function RuleDrawerProvider({ children }: { children: ReactNode }) {
  // The open target, or null. Held here rather than inside the panel so any path link in
  // the tree can open it without prop-drilling through the markdown renderer, which has no
  // idea what a rule is.
  const [open, setOpen] = useState<RuleTarget | null>(null)

  return (
    <OpenRuleContext.Provider value={setOpen}>
      {children}
      <RuleDrawer target={open} onClose={() => setOpen(null)} />
    </OpenRuleContext.Provider>
  )
}

function RuleDrawer({
  target,
  onClose,
}: {
  target: RuleTarget | null
  onClose: () => void
}) {
  // The panel's scroll container, so a fragment scrolls the panel rather than the page
  // behind it - the same heading id exists in both when the Rules screen is showing the
  // section the drawer was opened from.
  const scroller = useRef<HTMLDivElement>(null)

  return (
    <Drawer
      open={target !== null}
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose()
      }}
      swipeDirection="right"
    >
      <DrawerContent>
        {/* The primitive labels the panel from its Title, so there has to be one. It is
            visually hidden because the card below already shows the document's name, and a
            visible title would state it twice. */}
        <DrawerTitle className="sr-only">
          {target ? `Rule: ${target.document}` : "Rule"}
        </DrawerTitle>
        {/* The description says which kind of document this is, because the two are not
            equally authoritative: the SRD is the 2024 rulebook and is quoted, while a class
            context file is our own summary of a class. A screen reader that heard "quoted
            from the SRD" for both would be told a summary is a rule. */}
        <DrawerDescription className="sr-only">
          {target?.kind === "class"
            ? "Our own class rules, read from the context files."
            : "A rule quoted from the vendored 2024 SRD."}
        </DrawerDescription>

        <div ref={scroller} className="flex-1 overflow-y-auto p-4">
          {target && <RuleBody target={target} scroller={scroller} />}
        </div>

        <div className="border-t border-void-800 p-3">
          <DrawerClose
            className="flex w-full items-center justify-center gap-2 rounded-md py-2 text-sm text-parchment/60 transition-colors hover:bg-void-800 hover:text-parchment"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
            Close
          </DrawerClose>
        </div>
      </DrawerContent>
    </Drawer>
  )
}

/**
 * The open document, whichever kind it is.
 *
 * The two kinds are fetched by different hooks and rendered by different cards, so the
 * branch is here rather than inside either card - a card that fetched its own text would
 * have to know which endpoint to ask, and the two would drift.
 */
function RuleBody({
  target,
  scroller,
}: {
  target: RuleTarget
  scroller: RefObject<HTMLDivElement | null>
}) {
  if (target.kind === "class") {
    return <ClassBody target={target} />
  }
  return <SrdBody target={target} scroller={scroller} />
}

/**
 * One of our own class context files.
 *
 * No heading tree and no breadcrumb: these files are a handful of `##` sections each, and
 * the file is the unit a reader wants. Offering a tree of three headings would be chrome
 * around nothing.
 */
function ClassBody({ target }: { target: RuleTarget }) {
  const { document, error, loading } = useClassContext(target.document)

  return (
    <div className="space-y-4">
      {loading && <p className="text-sm text-parchment/60">Fetching the rules…</p>}

      {error && (
        <div className="space-y-2 text-sm">
          <p className="text-radiant-400">No such class context file</p>
          <p className="text-parchment/60">{error}</p>
        </div>
      )}

      {document && <ClassContextCard document={document} />}
    </div>
  )
}

/**
 * The open rule, plus the tree so the reader can keep browsing.
 *
 * The tree is here rather than only on the Rules tab because the commonest next move after
 * reading one rule is reading the one beside it - "Cover" leads to "Half Cover", a
 * condition leads to the action that applies it. Sending the reader back to the tab to
 * click again would make the drawer a dead end.
 */
function SrdBody({
  target,
  scroller,
}: {
  target: RuleTarget
  scroller: RefObject<HTMLDivElement | null>
}) {
  const { section, error, loading } = useSrdSection(target.document, target.slug)
  const { documents } = useSrdDocuments()
  const open = useOpenRule()

  // A breadcrumb opens the parent rule but the reader was reading the child, so the panel
  // lands on the child rather than at the top of the parent.
  //
  // Gated on `documents` as well as the section, because the ids come from the table of
  // contents: the section can arrive first, and scrolling before the anchors exist would
  // find nothing and never run again.
  useAnchorScroll(
    target.anchor,
    section && documents ? `${section.document}:${section.slug}` : null,
    scroller,
  )

  return (
    <div className="space-y-4">
      {loading && (
        <p className="text-sm text-parchment/60">Fetching the rule…</p>
      )}

      {error && (
        <div className="space-y-2 text-sm">
          <p className="text-radiant-400">No such rule</p>
          <p className="text-parchment/60">{error}</p>
        </div>
      )}

      {section && <SrdCard section={section} documents={documents} />}

      {documents && (
        <div className="border-t border-void-800 pt-3">
          <p className="mb-2 text-xs text-parchment/60">Browse the SRD</p>
          <div className="max-h-64 overflow-y-auto pr-1">
            <SrdTree
              documents={documents}
              selected={`${target.document}:${target.slug ?? ""}`}
              onSelect={(document, slug) => open({ kind: "srd", document, slug })}
            />
          </div>
        </div>
      )}
    </div>
  )
}
