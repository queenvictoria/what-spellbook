import type { CharacterEntry } from "@/api/types"
import { Select } from "@/components/ui/select"

/**
 * Which sheet the Character screen is showing.
 *
 * A plain `Select` rather than a popover of cards: this chooses between a handful of fixed
 * options, which is what a native select is for, and it is reachable by keyboard and announced
 * correctly for free. The visible text is a character's name, so the control needs a label of
 * its own - `aria-label` rather than a visible `<label>`, because the card title beside it
 * (`Lois`) is the *value*, and a visible label reading "Character" next to the name "Lois" would
 * read as two competing headings.
 *
 * **The option list is the server's, but the selected value need not be in it.** The remembered
 * choice can name a sheet that has since been renamed or deleted, and a `Select` whose value
 * matches no option silently displays the first one instead - so the current value is inserted
 * when it is missing. Showing a sheet that is not in the list is honest ("this is the sheet you
 * asked for") whereas showing a different character's name is not, and the load error from the
 * screen says the sheet is gone.
 *
 * **`value` is the sheet on screen, not merely the browser's stored preference.** With nothing
 * stored the server picks a character of its own, and a picker reading "server default" beside a
 * card titled `Lois` states two different things. The caller passes the loaded sheet's id once it
 * has one, so the control always names the character being displayed; `null` is reserved for the
 * moment before that is known.
 */
export function CharacterPicker({
  entries,
  value,
  onChange,
}: {
  entries: CharacterEntry[]
  /** The stem of the sheet on screen, or null before which one that is is known. */
  value: string | null
  onChange: (name: string) => void
}) {
  // Nothing to choose between: one sheet is not a choice, and an empty list means the picker
  // could not load. Either way the title alone says everything this control would.
  if (entries.length < 2) return null

  const options = value && !entries.some((entry) => entry.id === value)
    ? [...entries, { id: value, name: value }]
    : entries

  return (
    <Select
      aria-label="Character sheet"
      className="h-7 w-auto max-w-40 px-1.5 py-0 text-xs"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
    >
      {/* Shown only while the sheet is unknown - during load, or after the load failed. There is
          nothing to choose yet, but a `Select` with no matching value displays its first option
          instead, and naming the wrong character is worse than naming none. */}
      {value === null && <option value="">unknown</option>}
      {options.map((entry) => (
        <option key={entry.id} value={entry.id}>
          {entry.name}
        </option>
      ))}
    </Select>
  )
}