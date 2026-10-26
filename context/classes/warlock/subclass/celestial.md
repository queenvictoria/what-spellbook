# Celestial Patron (D&D 5.5e / 2024)

Subclass rules for a Warlock whose patron is a Celestial. Load this alongside
`context/warlock/base.md` and the pact file.

This file describes the subclass only. Which of these features is actually online is
determined by the character's level from the character sheet.

## Identity

Pact with an entity of the Upper Planes - an empyrean, couatl, sphinx, unicorn, or
another heavenly being. The subclass leans into **healing and radiant/fire spell
damage** rather than weapon attacks.

## Feature summary

| Level | Feature | Effect |
| --- | --- | --- |
| 3 | Celestial Spells | Always-prepared spell list, see below |
| 3 | Healing Light | Bonus Action heal from a pool of d6s, no spell slot |
| 6 | Radiant Soul | Radiant resistance, plus Charisma modifier to Radiant/Fire spell damage |
| 10 | Celestial Resilience | Temporary HP for self and up to five allies on rest / Magical Cunning |
| 14 | Searing Vengeance | Prevent a death saving throw, revive at half HP, blind and damage nearby foes |

## Celestial Spells (level 3+)

These are **always prepared** and do **not** count against the Warlock's prepared
spell count. They are added automatically at the listed Warlock level.

| Warlock Level | Spells |
| --- | --- |
| 3 | Aid, Cure Wounds, Guiding Bolt, Lesser Restoration, Light, Sacred Flame |
| 5 | Daylight, Revivify |
| 7 | Guardian of Faith, Wall of Fire |
| 9 | Greater Restoration, Summon Celestial |

Notes:

- Light and Sacred Flame are cantrips; the rest are levelled spells cast using Pact
  Magic slots (and therefore upcast to the slot level).
- Revivify and Summon Celestial are expensive here: each consumes one of the
  Warlock's very few slots.

## Healing Light (level 3)

- A pool of **d6s** fuels this heal. The pool size equals **1 + Warlock level**.
- As a **Bonus Action**, heal yourself or one creature you can see within 60 feet.
  Expend dice from the pool and restore HP equal to the total rolled.
- The maximum dice you can spend at once equals your **Charisma modifier**, minimum
  one die.
- The pool regains **all** expended dice on a **Long Rest**.

Tactics:

- This costs no spell slot, so it is the default way to top up allies between fights
  and to bring a downed ally back up.
- Spending the whole Charisma-modifier allowance in one action is usually better than
  trickling dice out, because it preserves action economy.
- Keep dice in reserve for reviving a downed ally - that is the highest-value use.

## Radiant Soul (level 6)

- **Resistance to Radiant damage.**
- **Once per turn**, when a spell you cast deals Radiant or Fire damage, add your
  **Charisma modifier** to that spell's damage against **one** of the spell's targets.

Tactics:

- The "one target, once per turn" limit means area spells gain no extra mileage from
  this - only a single target takes the bonus.
- It applies to Celestial Spells picks such as Sacred Flame, Guiding Bolt, Guardian of
  Faith and Wall of Fire.
- With very few slots, this only fires often if a Radiant/Fire **cantrip** is in the
  rotation, since cantrips are free.
- Do not overrate it. Agonizing Blast on Eldritch Blast adds the Charisma modifier to
  *every* beam and deals Force damage, which most monsters do not resist. Choosing a
  Radiant or Fire spell purely to trigger Radiant Soul is usually a downgrade.

## Celestial Resilience (level 10)

- Gain Temporary HP whenever you **use Magical Cunning** or **finish a Short or Long
  Rest**.
- Your own Temporary HP equal **Warlock level + Charisma modifier**.
- Additionally, choose **up to five creatures you can see** when you gain the points.
  Each of those gains Temporary HP equal to **half your Warlock level + Charisma
  modifier**.

Tactics:

- Free party-wide Temporary HP on every rest; it competes with and generally beats
  most other sources, so it removes the need to spend a feat on temporary-HP features.
- Take the points every rest - there is no cost and no reason to skip.

## Searing Vengeance (level 14)

- Trigger: you or an ally within **60 feet** is **about to make a Death Saving Throw**.
- The target regains HP equal to **half its HP maximum** and can end the **Prone**
  condition on itself.
- Each creature of your choice within **30 feet** of the revived creature takes Radiant
  damage equal to **2d8 + your Charisma modifier** and has the **Blinded** condition
  until the end of the current turn.
- Once used, it cannot be used again until you finish a **Long Rest**.

Tactics:

- Best held for an ally who is surrounded, since revived allies are prime targets and
  the Blinded burst protects them on the way back up.
- Prefer healing spells or Healing Light for allies who are safe; save this for the
  dangerous revives.
- It is still a rescue tool first - do not delay using it just to line up more enemies
  in the blast.

## Build implications

- **Charisma is the key ability** - it scales Healing Light's dice cap, Radiant Soul's
  damage bonus, and both halves of Celestial Resilience.
- This patron is a **support caster**, not a melee build. Keep out of reach and operate
  from range.
- Spell-slot scarcity is the defining constraint. Prefer cantrips and Healing Light for
  routine healing and damage, and reserve slots for long-duration concentration effects.

## Sources

- Celestial Patron, Warlock, 5.5e (2024) - verified against the 2024 class data used
  by 5e.tools (`XPHB` source, page 160)
- Optimisation notes - https://dungeonmister.com/guides/classes-in-dungeons-dragons/celestial-warlock-dnd-2024-guide/
- Flavour and subclass overview - https://www.dndbeyond.com/classes/2190885-warlock#CelestialPatron
  (D&D Beyond requires a subscription to read the subclass text; the mechanical
  details above were taken from the 2024 class data instead)

Caution: the **2024 SRD ships only the Fiend Patron**, so Celestial has no free SRD
page. The mechanics above are therefore drawn from the 2024 class data (`XPHB` source)
rather than an SRD page.

This file follows the 2024 (5.5e) rules. Earlier printings of the Celestial differ in
ways that matter — most notably Healing Light arrived at level 1 rather than level 3,
and Searing Vengeance could not target an ally — so do not "correct" anything here from
a 2014 source.
