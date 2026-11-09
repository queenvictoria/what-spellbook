# Fetched third-party rules content

The directory `DnD-Character-Sheet-Helper/` beside this file is **not** part of this
repository and is **not** committed - this file is tracked, the directory is ignored. It
holds a checkout of a third-party Obsidian plugin whose `rulebook/` data covers 2024 rules
the SRD does not, most importantly the Warlock subclasses. It is fetched on demand:

```bash
scripts/fetch-context.sh
```

This file sits *beside* the directory rather than inside it because the directory has to
be ignored as a whole: git will not descend into an ignored directory, so a `!` negation
inside it does not stop `git add -A` from staging the nested `.git` as a gitlink. See the
comment on the rule in `.gitignore`.

| | |
| --- | --- |
| Source repository | https://github.com/IonasPolitis/DnD-Character-Sheet-Helper |
| Pinned commit | `21c7635b3c6fd7b6f9d15e727dc61d3051c39b00` (tag `2.0.5-beta`) |
| Fetched from | `https://codeload.github.com/IonasPolitis/DnD-Character-Sheet-Helper/tar.gz/21c7635b3c6fd7b6f9d15e727dc61d3051c39b00` |
| Tarball SHA-256 | `cf53241145c057de18f235b6ab3a390cea1438e68a9674d26d290018d2fa0844` |
| Retrieved | 2026-11-09 |
| Licence | GPL-3.0 (the repository's `LICENSE`; its `package.json` says ISC) |

## Why this is fetched rather than committed or submoduled

**Not committed.** The content is 3.6 MB of someone else's GPL-3.0 work. Copying it into
this repository would redistribute it under a licence this project does not otherwise
use, and would mean every upstream rule correction had to be re-copied by hand.

**Not a submodule.** A submodule records a commit pointer and nothing else, so a clone that
does not pass `--recurse-submodules` silently produces an empty directory with no
indication that anything is missing. The pin is kept here instead: same reproducibility,
no extra git commands, and a failed fetch says so.

**Pinned by commit, not by tag.** Tags move. `2.0.5-beta` was the checked-out tag when this
directory was first created, but the commit is what the checksum was taken against.

## What it is used for

The backend reads it **in place** as an *optional* second rules source, through
`backend/libs/ionas.py`. It is never copied into this repository, so nothing of it is
redistributed here, and it is never required:

- `ionas.available()` is a single `is_dir` check. When the directory is absent, `sections()`
  is empty and every caller degrades to the SRD - a machine without the checkout behaves
  exactly as it did before this source existed.
- Every row it contributes is tagged `doc_type: "ionas-politis"`, distinct from the SRD's
  `"srd"`, so a filter and a badge can name either. The UI shows them as different sources
  because they are not equally authoritative.
- The rows join the vector index alongside the spells and the SRD, and are reachable through
  `GET /api/ionas` and `GET /api/ionas/{name}` and the Rules tab's `Rulebook` filter.

It is worth reading because the 2024 SRD contains **only the Fiend Patron**, while this
rulebook carries Archfey, Celestial and Great Old One - and, for the Wizard, Abjurer,
Diviner, Evoker and Illusionist where the SRD ships only the Evoker.

## Verification against the SRD (2026-11-09)

The content was compared with `context/srd/classes.md` at the pinned commit. **No
edition divergence was found**, which is what makes it safe to read as 2024:

| Check | Result |
| --- | --- |
| Warlock progression, all 20 rows (cantrips, prepared, slots, slot level) | exact match |
| Warlock invocation list | the same 28 options, with the same level gates |
| Fiend Patron feature text | equivalent, wording aside |
| Subclass coverage | **this source is the only local one** - the SRD has one subclass per class |

Two kinds of defect *were* found, both handled rather than trusted:

**Scan artifacts.** The text is a transcription, so ~30 words are broken (`protec-tion`,
`w ith`, `f ireball`, a stray `O` for `0`) and headings are sometimes embedded in the prose
they head. `ionas.normalise()` repairs them against a dictionary built from the vendored
SRD, which is the authority on how these words are spelled. Repairs are deliberately
conservative - ambiguous cases are listed by hand, because "a ward" joins to "award" while
"a Long Rest" must not join at all - and text that cannot be repaired confidently is left
alone.

**Upstream name defects, deliberately not corrected.** `ionas.normalise()` does not rename
anything, so these are recorded here instead:

- Three invocation keys do not match the SRD: `agonizing-blade` holds **Agonizing Blast**,
  `repelling-blast` holds **Repelling Blade** (the SRD says *Repelling Blast*), and
  `lessons-of-the-first-one` holds **Lessons of the First One** (the SRD says *First Ones*).
- Eight spell files are stray copies whose `name` names a *different* spell than the file
  them (`sending.json` holds Seeming, `thorn-whip.json` holds Thaumaturgy), and the `name`
  field is believed over the filename, as it is for the SRD.
- Two feats ship as unfilled templates (`<Feat_Name>` / `<Feat_Description>`); they are
  dropped rather than offered as rules.

So a lookup for "Repelling Blast" in this source misses. That is the honest outcome: the
SRD is the authority where the two overlap, and this source is preferred only for what the
SRD does not have at all.

