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
 * The class context files, keyed by the phrase a reader would recognise for each.
 *
 * A separate context from the spell names because the two are different kinds of thing and
 * are linked to different places: a spell opens the spell drawer, a class context file opens
 * the rule drawer on our own summary of the class. Folding them into one set would make
 * "Warlock" a spell.
 *
 * Empty until the list arrives, which simply means nothing is linked yet - the same
 * degradation the spell names have, and for the same reason: linking is an enhancement.
 */
export const ClassNamesContext = createContext<ReadonlyMap<string, string>>(new Map())

export function useClassNames(): ReadonlyMap<string, string> {
  return useContext(ClassNamesContext)
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

/**
 * Every spell name `text` mentions, deduplicated and in the corpus's own spelling.
 *
 * The same rule `splitSpells` links by, so a caller that attaches the mentioned spells to a
 * question attaches exactly the mentions the reader was shown as links. Two rules would
 * eventually disagree about whether a faint mention is attached, and the disagreement would
 * be invisible: a missing attachment reads as "the SRD does not cover this spell".
 */
export function extractSpellNames(text: string, names: ReadonlySet<string>): string[] {
  if (!buildSpellPattern(names)) return []
  const seen = new Set<string>()
  for (const [chunk, isSpell] of splitSpells(text, names)) {
    if (isSpell) seen.add(chunk)
  }
  return [...seen]
}

/** The corpus's own spelling of a name written some other way, or the text unchanged. */
function findCanonical(text: string, names: ReadonlySet<string>): string {
  const key = foldSpellName(text)
  for (const name of names) {
    if (foldSpellName(name) === key) return name
  }
  return text
}

/**
 * A regex matching any known class context name in text, or null when there is nothing to
 * match.
 *
 * The same shape as `buildSpellPattern` and for the same reasons - case-sensitive,
 * longest-first, word-boundary guarded - with one difference that matters: a **single-word**
 * name is rejected when a capitalised word sits immediately before it, exactly as a
 * single-word spell is. "Celestial Patron" is two words and links; the "Warlock" inside
 * "Celestial Warlock" does not, because two capitalised words in a row usually form one
 * longer proper name and "Celestial Warlock" is not a file.
 *
 * Case-sensitive because these are proper names: "warlock" in ordinary prose is the word,
 * and the file is the class.
 */
export function buildClassNamePattern(
  names: ReadonlyMap<string, string>,
): RegExp | null {
  if (names.size === 0) return null

  const escaped = [...names.keys()]
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
 * Splits text into plain runs and class context names.
 *
 * Returns `[text, path | null]` pairs, so the caller can render a link for the names and
 * leave everything else untouched. The path is the file to open, which is why the map is
 * keyed by name rather than being a set.
 */
export function splitClassNames(
  text: string,
  names: ReadonlyMap<string, string>,
): Array<[string, string | null]> {
  const pattern = buildClassNamePattern(names)
  if (!pattern) return [[text, null]]

  const parts: Array<[string, string | null]> = []
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > cursor) parts.push([text.slice(cursor, index), null])
    parts.push([match[0], names.get(match[0]) ?? null])
    cursor = index + match[0].length
  }
  if (cursor < text.length) parts.push([text.slice(cursor), null])
  return parts
}
