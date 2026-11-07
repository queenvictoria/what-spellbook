import { useState } from "react"
import type { ReactNode } from "react"
import { X } from "lucide-react"

import { SrdCard } from "@/components/SrdCard"
import { SrdTree } from "@/components/SrdTree"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
} from "@/components/ui/drawer"
import { OpenSrdContext, useOpenSrd } from "@/lib/srdDrawer"
import type { SrdTarget } from "@/lib/srdDrawer"
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
export function SrdDrawerProvider({ children }: { children: ReactNode }) {
  // The open target, or null. Held here rather than inside the panel so any path link in
  // the tree can open it without prop-drilling through the markdown renderer, which has no
  // idea what a rule is.
  const [open, setOpen] = useState<SrdTarget | null>(null)

  return (
    <OpenSrdContext.Provider value={setOpen}>
      {children}
      <SrdDrawer target={open} onClose={() => setOpen(null)} />
    </OpenSrdContext.Provider>
  )
}

function SrdDrawer({
  target,
  onClose,
}: {
  target: SrdTarget | null
  onClose: () => void
}) {
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
        <DrawerDescription className="sr-only">
          A rule quoted from the vendored 2024 SRD.
        </DrawerDescription>

        <div className="flex-1 overflow-y-auto p-4">
          {target && <SrdBody target={target} />}
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
 * The open rule, plus the tree so the reader can keep browsing.
 *
 * The tree is here rather than only on the Rules tab because the commonest next move after
 * reading one rule is reading the one beside it - "Cover" leads to "Half Cover", a
 * condition leads to the action that applies it. Sending the reader back to the tab to
 * click again would make the drawer a dead end.
 */
function SrdBody({ target }: { target: SrdTarget }) {
  const { section, error, loading } = useSrdSection(target.document, target.slug)
  const { documents } = useSrdDocuments()
  const open = useOpenSrd()

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

      {section && <SrdCard section={section} />}

      {documents && (
        <div className="border-t border-void-800 pt-3">
          <p className="mb-2 text-xs text-parchment/60">Browse the SRD</p>
          <div className="max-h-64 overflow-y-auto pr-1">
            <SrdTree
              documents={documents}
              selected={`${target.document}:${target.slug ?? ""}`}
              onSelect={(document, slug) => open({ document, slug })}
            />
          </div>
        </div>
      )}
    </div>
  )
}
