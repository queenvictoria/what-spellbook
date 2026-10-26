/**
 * Finding spell names in generated prose, and the shared list of names to look for.
 *
 * Kept apart from the provider component so the module exports only functions and the
 * context, which is what lets React Fast Refresh reload the provider without discarding
 * the page.
 */
import { createContext, useContext } from 'react'

/**
 * The corpus's spell names, loaded once by `SpellNamesProvider` and read by any renderer
 * that wants to link a mention. Empty until the list arrives, which simply means nothing
 * is linked yet.
 */
export const SpellNamesContext = createContext<ReadonlySet<string>>(new Set())

export function useSpellNames(): ReadonlySet<string> {
  return useContext(SpellNamesContext)
}

/**
 * Case- and apostrophe-insensitive key, so a name can be looked up the way prose writes it.
 *
 * The corpus stores apostrophes as typographic `’`, while the model writes a plain `'`.
 * Without folding both, "Tasha's Hideous Laughter" would only match itself in one exact
 * spelling.
 */
export function foldSpellName(name: string): string {
  return name.replace(/[’']/g, "'").toLowerCase()
}

/**
 * A regex matching any known spell name in text, or null when there is nothing to match.
 *
 * Names are matched **case-sensitively** and longest-first, and both matter:
 *
 * - Case-sensitive, because D&D prose capitalises spell names and English does not. 132 of
 *   the corpus's 544 spells are single common words ("Light", "Sleep", "Fear", "Shield"),
 *   so a case-insensitive match would link "the light of the fire" and "a deep sleep" as
 *   spells. Capitalisation is the signal that separates the spell from the word.
 * - Longest-first, so "Shield of Faith" is not matched as "Shield" followed by "of Faith".
 *
 * Word boundaries stop "Shield" matching inside "Shielded" and "Held" inside "Swordheld".
 *
 * A **single-word** name is additionally rejected when a capitalised word sits immediately
 * before it, because two capitalised words in a row usually form one longer proper name.
 * The Celestial Warlock's *Healing Light* feature is the case that forced this: without it
 * the "Light" inside it linked to the Light spell, which is a different thing entirely.
 * Multi-word names are exempt, so "Cast Eldritch Blast" still links.
 */
export function buildSpellPattern(names: ReadonlySet<string>): RegExp | null {
  if (names.size === 0) return null

  const escaped = [...names]
    .filter((name) => name.length > 2)
    .sort((a, b) => b.length - a.length)
    .map((name) => {
      const body = name
        .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
        .replace(/[’']/g, "['’]")
      return name.includes(' ') ? body : `(?<![A-Z][a-z]+ )${body}`
    })

  if (escaped.length === 0) return null
  return new RegExp(`(?<![\\w'’])(?:${escaped.join('|')})(?![\\w'’])`, 'g')
}

/**
 * Splits text into plain runs and spell names.
 *
 * Returns `[text, isSpell]` pairs so the caller can render a link for the names and leave
 * everything else untouched.
 */
export function splitSpells(
  text: string,
  names: ReadonlySet<string>,
): Array<[string, boolean]> {
  const pattern = buildSpellPattern(names)
  if (!pattern) return [[text, false]]

  const parts: Array<[string, boolean]> = []
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > cursor) parts.push([text.slice(cursor, index), false])
    // Report the corpus's own spelling so the link opens the right spell even when the
    // prose used a straight apostrophe and the corpus a typographic one.
    parts.push([findCanonical(match[0], names), true])
    cursor = index + match[0].length
  }
  if (cursor < text.length) parts.push([text.slice(cursor), false])
  return parts
}

/** The corpus's own spelling of a name written some other way, or the text unchanged. */
function findCanonical(text: string, names: ReadonlySet<string>): string {
  const key = foldSpellName(text)
  for (const name of names) {
    if (foldSpellName(name) === key) return name
  }
  return text
}
