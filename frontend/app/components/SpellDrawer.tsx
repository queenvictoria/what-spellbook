import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Search, X } from 'lucide-react'

import { SpellCard } from '@/components/SpellCard'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
} from '@/components/ui/drawer'
import { Input } from '@/components/ui/input'
import { OpenSpellContext, useOpenSpell } from '@/lib/spellDrawer'
import { useSpellNames } from '@/lib/spellNames'
import { useSpell } from '@/lib/useSpell'

/**
 * A pull-out panel for reading a spell without leaving the page you were on.
 *
 * The books refer to spells constantly, and following one used to mean leaving the
 * recommendation behind and using the back button to find your place again. The drawer
 * keeps the book on screen, which matters most while choosing between spells — comparing
 * two is the whole task.
 *
 * The panel is Base UI's Drawer, which is what shadcn's current drawer wraps, so Escape,
 * the focus trap and the `aria-*` wiring come from the primitive rather than being redone
 * here.
 */
export function SpellDrawerProvider({ children }: { children: ReactNode }) {
  // The open spell's name, or null. Held here rather than inside the panel so any
  // `SpellLink` in the tree can open it without prop-drilling through the markdown
  // renderer, which has no idea what a spell is.
  const [open, setOpen] = useState<string | null>(null)

  return (
    <OpenSpellContext.Provider value={setOpen}>
      {children}
      <SpellDrawer name={open} onClose={() => setOpen(null)} />
    </OpenSpellContext.Provider>
  )
}

function SpellDrawer({ name, onClose }: { name: string | null; onClose: () => void }) {
  return (
    <Drawer
      open={name !== null}
      // Escape and an outside press both arrive here as a close; the button below uses
      // DrawerClose, which the primitive handles itself.
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose()
      }}
      swipeDirection="right"
    >
      <DrawerContent>
        {/* The primitive labels the panel from its Title, so there has to be one. It is
            visually hidden because the card below already shows the spell's name, and a
            visible title would state it twice. */}
        <DrawerTitle className="sr-only">{name ? `Spell: ${name}` : 'Spell'}</DrawerTitle>
        <DrawerDescription className="sr-only">
          A spell's rules, quoted from the vendored SRD or the spell corpus.
        </DrawerDescription>

        <SpellSearch />

        <div className="flex-1 overflow-y-auto p-4">{name && <SpellBody name={name} />}</div>

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
 * Search over the whole corpus, at the top of the panel.
 *
 * Matching is on the name, deliberately. The corpus holds 546 spells and a name is what a
 * reader has: they are looking for "Shield", not for the word "shield" inside a
 * description. Matching the body would return most of the list for a common word and bury
 * the one spell being looked for.
 */
function SpellSearch() {
  const names = useSpellNames()
  const setOpen = useOpenSpell()
  const [query, setQuery] = useState('')

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (needle.length < 2) return []
    const all = [...names]
    const starts = all.filter((n) => n.toLowerCase().startsWith(needle))
    const contains = all.filter(
      (n) => !n.toLowerCase().startsWith(needle) && n.toLowerCase().includes(needle),
    )
    // A prefix match is nearly always the intended one - typing "shie" means Shield rather
    // than "Barkskin" - so those come first instead of being interleaved alphabetically.
    return [...starts, ...contains].slice(0, 8)
  }, [names, query])

  return (
    <div className="border-b border-void-800 p-4">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-parchment/35" />
        <Input
          value={query}
          placeholder="Search all spells…"
          aria-label="Search all spells"
          onChange={(e) => setQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {matches.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {matches.map((match) => (
            <li key={match}>
              <button
                onClick={() => {
                  // The same opener a link in a book uses, so a result and a mention are
                  // the same action.
                  setOpen(match)
                  setQuery('')
                }}
                className="rounded-full border border-void-700 px-2 py-0.5 text-xs text-parchment/60 transition-colors hover:border-arcane-400 hover:text-parchment"
              >
                {match}
              </button>
            </li>
          ))}
        </ul>
      )}
      {query.trim().length >= 2 && matches.length === 0 && (
        <p className="mt-2 text-xs text-parchment/40">No spell by that name.</p>
      )}
    </div>
  )
}

/** The open spell's text, its "not found" line, or its error. */
function SpellBody({ name }: { name: string }) {
  const { spell, missing, error } = useSpell(name)

  if (error) return <p className="text-sm text-red-300">{error}</p>

  if (missing) {
    return (
      <div className="space-y-2 text-sm">
        <p className="text-radiant-400">Not in the SRD or the corpus</p>
        <p className="text-parchment/60">{missing}</p>
      </div>
    )
  }

  if (!spell) return <p className="text-sm text-parchment/40">Looking up {name}…</p>

  return <SpellCard spell={spell} />
}
