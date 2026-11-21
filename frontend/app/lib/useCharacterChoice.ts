import { useCallback, useEffect, useState } from "react"

import { api } from "@/api/client"
import type { CharacterEntry } from "@/api/types"
import { readCharacter, writeCharacter } from "@/lib/browserSettings"

/**
 * Which character sheet this browser is looking at, and how to change it.
 *
 * The choice has to exist in three places at once — the list to choose from, the current value,
 * and somewhere durable to keep it — so it lives in one hook rather than being re-fetched per
 * screen. `null` means "this browser has no opinion", which is not the same as "there is no
 * character": the server's `CHARACTER` (or `--character`) decides in that case, and the screens
 * pass `undefined` so the backend applies its own default.
 *
 * **The list is fetched once, and a failure to fetch it is not fatal.** A character picker is
 * chrome on a screen whose subject is the sheet: if `GET /api/characters` fails, the right
 * behaviour is to render no picker and leave the rest of the screen working, not to replace
 * everything with an error. The caller's own request reports the real failure - and a base URL
 * that cannot answer `/api/characters` cannot answer `/api/character` either.
 */
export interface CharacterChoice {
  /** The sheets available. Empty until loaded, or if the list could not load. */
  entries: CharacterEntry[]
  /** The chosen stem, or null when this browser has no preference. */
  selected: string | null
  /** Choose a character, or clear the preference by passing null. */
  choose: (name: string | null) => void
  /** Refresh the list after importing a sheet. */
  refresh: () => Promise<void>
}

export function useCharacterChoice(): CharacterChoice {
  const [entries, setEntries] = useState<CharacterEntry[]>([])
  const [selected, setSelected] = useState<string | null>(() => readCharacter())

  const refresh = useCallback(async () => {
    try {
      setEntries(await api.characters())
    } catch {
      // The list only populates the picker; a sheet load reports the actionable error.
      setEntries([])
    }
  }, [])

  useEffect(() => {
    let live = true
    api.characters()
      .then((list) => {
        if (live) setEntries(list)
      })
      .catch(() => {
        if (live) setEntries([])
      })
    return () => {
      live = false
    }
  }, [])

  const choose = useCallback((name: string | null) => {
    // Stored before the state update so a reload during the re-fetch still remembers it. The
    // return value is ignored on purpose: storage can be unavailable (private mode, a disabled
    // datastore) and the choice still has to work for the rest of the session.
    writeCharacter(name)
    setSelected(name)
  }, [])

  return { entries, selected, choose, refresh }
}