# Warlock - base class rules (D&D 5.5e / 2024)

Class-wide rules for the Warlock. Load this alongside the chosen pact and patron
files. Character-specific values (actual level, chosen spells, ability scores) come
from the character sheet, not from here.

- Pact file: `context/warlock/pact/tome.md` (or `blade.md`, `chain.md`)
- Patron file: `context/warlock/subclass/celestial.md` (or another patron)
- Casting-economy rules for combining spells: `context/spells.md`

## Progression (levels 1-20)

`Prepared` counts level 1+ spells. `Slot Level` is the level **all** slots are cast at.

| Level | Cantrips | Prepared | Spell Slots | Slot Level | Invocations |
| --- | --- | --- | --- | --- | --- |
| 1 | 2 | 2 | 1 | 1 | 1 |
| 2 | 2 | 3 | 2 | 1 | 3 |
| 3 | 2 | 4 | 2 | 2 | 3 |
| 4 | 3 | 5 | 2 | 2 | 3 |
| 5 | 3 | 6 | 2 | 3 | 5 |
| 6 | 3 | 7 | 2 | 3 | 5 |
| 7 | 3 | 8 | 2 | 4 | 6 |
| 8 | 3 | 9 | 2 | 4 | 6 |
| 9 | 3 | 10 | 2 | 5 | 7 |
| 10 | 4 | 10 | 2 | 5 | 7 |
| 11 | 4 | 11 | 3 | 5 | 7 |
| 12 | 4 | 11 | 3 | 5 | 8 |
| 13 | 4 | 12 | 3 | 5 | 8 |
| 14 | 4 | 12 | 3 | 5 | 8 |
| 15 | 4 | 13 | 3 | 5 | 9 |
| 16 | 4 | 13 | 3 | 5 | 9 |
| 17 | 4 | 14 | 4 | 5 | 9 |
| 18 | 4 | 14 | 4 | 5 | 10 |
| 19 | 4 | 15 | 4 | 5 | 10 |
| 20 | 4 | 15 | 4 | 5 | 10 |

Cantrips and prepared spells are drawn from the **Warlock** spell list. The Pact of
the Tome adds further picks from any class's list - see the pact file.

## Pact Magic - the rule that trips models up

- **Warlocks do not have slots per spell level.** Every slot is the *same* level, set
  by the Slot Level column. A level 5 Warlock has **two 3rd-level slots**, not a
  spread of 1st/2nd/3rd like a Wizard.
- Casting a lower-level spell spends a slot and **upcasts** it to the slot level. A
  1st-level spell cast with a 3rd-level slot resolves as a 3rd-level spell.
- Slot level maxes out at 5th. Higher-level casting comes only from Mystic Arcanum
  (level 11+), a separate once-per-long-rest feature.
- **All expended slots return on a Short or Long Rest.**
- Spellcasting ability is Charisma. An Arcane Focus (or the Book of Shadows, for a
  Tome Warlock) serves as the spellcasting focus.

## Class features by level

| Level | Feature | Effect |
| --- | --- | --- |
| 1 | Pact Magic | Cantrips, prepared spells and slots per the progression table |
| 1 | Eldritch Invocations | Gain invocations per the Invocations column |
| 2 | Magical Cunning | 1-minute rite regains expended slots, up to half your maximum (rounded up). Once per Long Rest |
| 3 | Warlock Subclass | Patron features at levels 3, 6, 10 and 14 - see the patron file |
| 4, 8, 12, 16 | Ability Score Improvement | +2 to one ability or +1 to two |
| 9 | Contact Patron | Contact Other Plane is always prepared; cast it without a slot to reach your patron, auto-succeeding its save. Once per Long Rest |
| 11 | Mystic Arcanum (6th) | One 6th-level Warlock spell, cast once per Long Rest without a slot |
| 13, 15, 17 | Mystic Arcanum (7th, 8th, 9th) | One further arcanum spell each, cast once per Long Rest without a slot |
| 19 | Epic Boon | One Epic Boon feat, or another feat you qualify for |
| 20 | Eldritch Master | Magical Cunning regains **all** expended slots, not just half |

Mystic Arcanum spells can be swapped for another Warlock spell of the same level when
you gain a level. They are separate from Pact Magic and are not upcast.

## Eldritch Invocations

- How many you get is the Invocations column in the progression table.
- **Pact invocations count against that total.** Taking Pact of the Tome spends one
  pick and grants the Book of Shadows; the same is true of Blade and Chain.
- You can replace one invocation whenever you gain a Warlock level. You cannot replace
  an invocation that is a prerequisite for another invocation you hold.
- You cannot take the same invocation twice unless it is marked **Repeatable**.
- A **Pact** invocation can be swapped on level-up, but doing so forfeits everything
  the old pact granted.

### Full invocation list (2024)

`Lv` is the minimum Warlock level. `Prereq` beyond level is listed separately.

| Invocation | Lv | Prereq | Repeatable |
| --- | --- | --- | --- |
| Armor of Shadows | 1 | - | No |
| Eldritch Mind | 1 | - | No |
| Pact of the Blade | 1 | - | No |
| Pact of the Chain | 1 | - | No |
| Pact of the Tome | 1 | - | No |
| Agonizing Blast | 2 | A damage-dealing Warlock cantrip | Yes |
| Devil's Sight | 2 | - | No |
| Eldritch Spear | 2 | A damage-dealing Warlock cantrip with 10+ ft range | Yes |
| Fiendish Vigor | 2 | - | No |
| Lessons of the First Ones | 2 | - | Yes |
| Mask of Many Faces | 2 | - | No |
| Misty Visions | 2 | - | No |
| Otherworldly Leap | 2 | - | No |
| Repelling Blast | 2 | An attack-roll Warlock cantrip | Yes |
| Ascendant Step | 5 | - | No |
| Eldritch Smite | 5 | Pact of the Blade | No |
| Gaze of Two Minds | 5 | - | No |
| Gift of the Depths | 5 | - | No |
| Investment of the Chain Master | 5 | Pact of the Chain | No |
| Master of Myriad Forms | 5 | - | No |
| One with Shadows | 5 | - | No |
| Thirsting Blade | 5 | Pact of the Blade | No |
| Whispers of the Grave | 7 | - | No |
| Gift of the Protectors | 9 | Pact of the Tome | No |
| Lifedrinker | 9 | Pact of the Blade | No |
| Visions of Distant Realms | 9 | - | No |
| Devouring Blade | 12 | Thirsting Blade | No |
| Witch Sight | 15 | - | No |

Only ever recommend invocations whose `Lv` is at or below the character's level **and**
whose prereq the character actually satisfies. For a Tome Warlock with no Blade or
Chain pact, the Blade/Chain-gated entries are unavailable.

Repeatable invocations still need a distinct target each time: a different eligible
cantrip (or, for Lessons of the First Ones, a different Origin feat).

## Source

Warlock class, 5.5e SRD (2024) - https://5e24srd.com/classes/warlock.html
