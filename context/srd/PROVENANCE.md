# Vendored 2024 SRD text

These files are the 2024 System Reference Document (SRD 5.2.1) converted to Markdown.
They are **not** authored by this project; they are redistributed under the licence below.

| | |
| --- | --- |
| Source repository | https://github.com/downfallx/dnd-5e-srd-markdown |
| Official document | https://media.dndbeyond.com/compendium-images/srd/5.2/SRD_CC_v5.2.1.pdf |
| SRD version | 5.2.1 (published 2025-05-01) |
| Retrieved | 2026-10-26 |
| Licence | Creative Commons Attribution 4.0 International (CC-BY-4.0) |

## Attribution (CC-BY-4.0, required)

This work includes material taken from the System Reference Document 5.2.1 ("SRD 5.2.1")
by Wizards of the Coast LLC and is licensed under the Creative Commons Attribution 4.0
International License. To view a copy of this licence, visit
https://creativecommons.org/licenses/by/4.0/

The files here are an unmodified copy of the Markdown conversion published at the source
repository above. Changes made by this project: none to the text; the files were renamed
from the repository's flat layout into `context/srd/`.

## Why these files and not the website

`/?` previously fetched pages from `5e24srd.com` at query time. That site serves SRD 5.2
but **omits large parts of it**, verified by crawling every page for headings:

| Rule | On 5e24srd.com | Here |
| --- | --- | --- |
| Cover, Hiding, Difficult Terrain, Travel Pace, Dropping Prone | present | present |
| **Short Rest / Long Rest** | **absent** - only passing mentions | present, under its own heading |
| **The Grappled condition** | **absent** | present |
| **The Rules Glossary** | **absent** - pages cross-reference it | present, all 154 entries |

The glossary is the important one: pages cross-reference it for definitions, so a rules
answer drawn from the website was systematically incomplete. Vendoring removes that gap
*and* the network dependency.

## Files

| File | Contains |
| --- | --- |
| `rules-glossary.md` | 154 rule and condition definitions - the definitions other pages assume |
| `playing-the-game.md` | Core mechanics: checks, combat, damage, movement |
| `gameplay-toolbox.md` | Optional and advanced systems, environmental rules |
| `equipment.md` | Weapons, armour, gear, tools |
| `spells.md` | The rules of spellcasting, plus 339 spell descriptions |
| `classes.md` | The 12 classes, their features, and the 28 Eldritch Invocation options |

`monsters*.md` and `magic-items.md` are deliberately **not** vendored: this project's
monster data lives in `data/` already, and duplicating it would create two sources of truth
that drift.

### Why `classes.md` is here

It was added for one section: **Eldritch Invocation Options**, which is the only place the
invocations' effect text exists. Our own `context/classes/warlock/` lists all 28 with their
level and prerequisite, but not what they do - so before this file was vendored the card
could answer "may I take Agonizing Blast?" and not "what does it do?".

The rest of the chapter is a side effect, and a useful one: multiclassing and the wizard's
spellbook are rules the SRD carries that were previously refused as absent. The chapter is
11,000 lines, so the invocation section is located by heading rather than by scanning for
names - indexing the whole file would offer every class feature as an invocation.

Vendoring it did surface one false positive, now guarded: "how does a spear work" was
answered with "Eldritch Spear", because the Spear itself lives inside an equipment *table*
with no heading of its own, leaving the invocation as the only heading containing the word.
A heading qualified by a distinctive word the question never mentioned is now rejected.

### Why `spells.md` is here *and* in `data/`

This is the one deliberate duplication, and it is not two sources of truth because the two
copies answer different questions:

* `data/reddit-spence_post/Spells/` is the **retrieval corpus** - 544 spells chunked and
  embedded so the recommender can rank them.
* `context/srd/spells.md` is the **display text** - the SRD's own wording, shown verbatim
  when a spell is opened.

They disagree in two ways worth knowing, both visible in the UI:

1. **Coverage.** 544 corpus spells against 339 in the SRD. The ~200 extra come from source
   books the SRD does not cover, so opening one reports that the SRD has no such spell.
2. **Naming.** The 2024 SRD removed product identity, so the corpus's "Tenser's Floating
   Disk", "Bigby's Hand" and "Mordenkainen's Faithful Hound" are the SRD's "Floating Disk",
   "Arcane Hand" and "Faithful Hound". 23 corpus files carry a wizard's name that the SRD
   does not use, and a lookup by the old name correctly misses.

Neither is a bug to paper over. The corpus is what the model may pick from; the vendored
SRD is what the rules actually say.
