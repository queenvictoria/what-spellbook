import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '@/api/client'
import { SpellNamesContext } from '@/lib/spellNames'

/**
 * Loads the corpus's spell names once and shares them, so generated prose can link to them.
 *
 * The list comes from the server rather than being hard-coded here. There is one authority
 * on which spells exist - the retrieval corpus - and a spell added to it should become
 * linkable without editing the UI.
 */
export function SpellNamesProvider({ children }: { children: ReactNode }) {
  const [names, setNames] = useState<ReadonlySet<string>>(() => new Set())

  useEffect(() => {
    let cancelled = false
    api
      .spells()
      .then((list) => {
        if (!cancelled) setNames(new Set(list))
      })
      .catch(() => {
        // Linking is an enhancement. Without the list the books still read correctly,
        // just without clickable spells, so a failure here must not surface as an error.
      })
    return () => {
      cancelled = true
    }
  }, [])

  return <SpellNamesContext.Provider value={names}>{children}</SpellNamesContext.Provider>
}
