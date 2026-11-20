# Third-party notices

This file records the third-party material this project redistributes or reads, and the
licence each one requires. It is the machine-readable list's long form: the app renders the
same attributions in its footer, served by `GET /api/licensing`
(`backend/libs/licensing.py`).

**This is not a licence for this project's own code.** No licence has been chosen for it
yet, so there is no root `LICENSE` file. What follows covers only the third-party content.

## System Reference Document 5.2.1 — CC-BY-4.0

The 2024 rules text in `context/srd/` is a Markdown conversion of SRD 5.2.1, redistributed
here under the Creative Commons Attribution 4.0 International License. It is **vendored**,
so the attribution is unconditional: the files are in this repository and their text is
quoted throughout the Rules tab and used to ground recommendations.

> This work includes material taken from the System Reference Document 5.2.1 ("SRD 5.2.1")
> by Wizards of the Coast LLC and is licensed under the Creative Commons Attribution 4.0
> International License. To view a copy of this licence, visit
> <https://creativecommons.org/licenses/by/4.0/>

| | |
| --- | --- |
| Holder | Wizards of the Coast LLC |
| Licence | CC-BY-4.0 — <https://creativecommons.org/licenses/by/4.0/> |
| Source | <https://github.com/downfallx/dnd-5e-srd-markdown> |
| Official document | <https://www.dndbeyond.com/srd> |
| Full record | [`context/srd/PROVENANCE.md`](context/srd/PROVENANCE.md) |

The conversion is unmodified. The only change this project made is the file layout: the
upstream repository's files were renamed and placed under `context/srd/`.

## DnD Character Sheet Helper — GPL-3.0

An optional second 2024 rules source, read **in place** from a checkout at
`context/DnD-Character-Sheet-Helper/`. It is fetched by `scripts/fetch-context.sh` at a
pinned commit and is **not committed**, so its content is not redistributed by this
project — which is why the attribution is conditional on the checkout being present. A
clone without it owes nothing, and the app renders no notice for it.

| | |
| --- | --- |
| Holder | Ionas Politis |
| Licence | GPL-3.0 — <https://www.gnu.org/licenses/gpl-3.0.html> |
| Source | <https://github.com/IonasPolitis/DnD-Character-Sheet-Helper> |
| Full record | [`context/DnD-Character-Sheet-Helper.PROVENANCE.md`](context/DnD-Character-Sheet-Helper.PROVENANCE.md) |

The upstream `LICENSE` says GPL-3.0 while its `package.json` claims ISC. The stricter of the
two is recorded here, and the full record documents the discrepancy.

## Spell corpus

The spell descriptions in `data/` are the retrieval corpus. Their provenance is recorded in
the README's *Sources* section; they are not covered by either licence above.

## Keeping this file honest

`backend/libs/licensing.py` is the single source of the attribution text the app renders, and
`tests/test_licensing.py` asserts that the SRD sentence here and the one in the module are
the same sentence. If a licence changes, change it in the module and in this file — a notice
that disagrees with itself is worse than no notice.
