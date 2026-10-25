# Pact of the Tome (D&D 5.5e / 2024)

Pact rules for a Warlock who has taken the **Pact of the Tome** eldritch invocation.
Load this alongside `context/warlock/base.md` and the patron file.

This file describes the pact only. How many picks are available and at what levels is
determined by the character's level from the character sheet.

## What the pact grants

Pact of the Tome costs **one eldritch invocation pick** from the Invocations total in
`context/warlock/base.md`. In exchange it grants the **Book of Shadows**:

| Property | Value |
| --- | --- |
| Cantrips chosen | 3 |
| Ritual spells chosen | 2 (must have the Ritual tag, must be level 1) |
| Spell list access | **Any class's** spell list |
| Restriction | Must be spells not already prepared as Warlock spells |
| While held | Chosen spells count as prepared and function as Warlock spells |
| Focus | The book can be used as a spellcasting focus |
| Timing | Conjured at the end of a Short or Long Rest |
| Duration | Disappears if another book is conjured, or if the character dies |

The cantrips and ritual spells are chosen **fresh each time the book is conjured**, so
the loadout can be re-tooled between encounters. Chosen cantrips consume no slot;
chosen rituals can be cast as rituals (adding 10 minutes to the casting time and no
slot) or cast normally, spending a slot and upcasting to the slot level.

These picks are **in addition to** the Warlock cantrips and prepared spells from the
progression table. At level 5, for example, a Tome Warlock has 3 Warlock cantrips plus
3 book cantrips, and 6 prepared spells plus 2 book rituals.

## Tactics

- Because both the book and Pact Magic slots recharge on a **Short Rest**, a single
  rest yields a full spell re-tool *and* full slots. Budget the book around the
  encounter the party expects next.
- The book's **any-class** access is the main reason to take this pact: it is how a
  Warlock borrows tools its own list lacks (utility rituals, terrain control, buffs).
- Two level-1 rituals are a small budget. Prefer rituals the party will otherwise pay
  a slot or a long cast for, and avoid ones already covered by another party member.
- A ritual cast from the book does not consume a Pact Magic slot, which matters a great
  deal given how few slots a Warlock has.

## Related invocations

| Invocation | Minimum level | Note |
| --- | --- | --- |
| Pact of the Tome | 1 | Grants the Book of Shadows above |
| Gift of the Protectors | 9 | Adds a page of names to the Book of Shadows; prevents a named creature from dropping to 0 HP |

## Alternatives

Pact of the Blade and Pact of the Chain occupy the same single invocation pick and are
mutually exclusive with Pact of the Tome in practice - taking one replaces the other.
Only recommend Blade or Chain invocations if the character sheet says the character has
that pact. Do not recommend Blade or Chain features to a Tome Warlock.

## Sources

- Eldritch Invocations, Warlock, 5.5e (2024) - verified against the 2024 class data
  used by 5e.tools (`XPHB` source)
- Warlock class, 5.5e SRD (2024) - https://5e24srd.com/classes/warlock.html
