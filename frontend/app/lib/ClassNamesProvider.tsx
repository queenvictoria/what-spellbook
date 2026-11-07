import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '@/api/client'
import { ClassNamesContext } from '@/lib/spellNames'

/**
 * Loads the class context files once and shares them, so generated prose can link to them.
 *
 * The list comes from the server rather than being hard-coded here. There is one authority
 * on which class context files exist - `context/classes/` - and a class added to it should
 * become linkable without editing the UI.
 *
 * The map is keyed by the phrase a reader would recognise ("Warlock", "Celestial Patron")
 * and valued by the repo-relative path, because that is what a link needs: the phrase is
 * what the prose says, and the path is what the drawer opens.
 */
export function ClassNamesProvider({ children }: { children: ReactNode }) {
  const [names, setNames] = useState<ReadonlyMap<string, string>>(() => new Map())

  useEffect(() => {
    let cancelled = false
    api
      .classContextFiles()
      .then((files) => {
        if (!cancelled) setNames(new Map(files.map((file) => [file.name, file.path])))
      })
      .catch(() => {
        // Linking is an enhancement. Without the list the answers still read correctly,
        // just without clickable class names, so a failure here must not surface as an
        // error - the same rule the spell names follow.
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <ClassNamesContext.Provider value={names}>{children}</ClassNamesContext.Provider>
  )
}
