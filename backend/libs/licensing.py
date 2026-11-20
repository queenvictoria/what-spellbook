"""Third-party attribution for the content this app redistributes or reads.

Two sources need a notice, and they need *different* things:

* The 2024 SRD is **vendored** into ``context/srd/``, so its text is redistributed by this
  repository and CC-BY-4.0 requires the attribution to travel with the work. The notice is
  unconditional, because the files are always there.
* The DnD Character Sheet Helper rulebook is **fetched, never committed**, and read in
  place. Its GPL-3.0 licence obliges nothing of a checkout that does not have it, so the
  notice is conditional on the source being installed - the same ``is_dir`` check
  ``ionas.available()`` makes. A notice for content that is not present would be a claim
  about a redistribution that never happened.

The text lives here rather than in the front end so the CLI and the API cannot disagree
about what a licence is, and so a licence change is one edit. The long-form records stay in
``context/srd/PROVENANCE.md`` and ``context/DnD-Character-Sheet-Helper.PROVENANCE.md``; this
module is the short form the app can render, and it deliberately does not duplicate their
verification notes.

**This is not the licence for this project's own code.** No licence has been chosen for it,
and inventing one here would be a decision this module has no business making. What it
covers is the third-party material the app displays.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ionas, rules

# The attribution sentence CC-BY-4.0 requires, verbatim from context/srd/PROVENANCE.md.
# Kept as one string rather than assembled from fields: it is a licence requirement, and a
# sentence rebuilt from parts is a sentence that can drift from the one that was checked.
SRD_ATTRIBUTION = (
    'This work includes material taken from the System Reference Document 5.2.1 '
    '("SRD 5.2.1") by Wizards of the Coast LLC and is licensed under the Creative Commons '
    "Attribution 4.0 International License. To view a copy of this licence, visit "
    "https://creativecommons.org/licenses/by/4.0/"
)


@dataclass(frozen=True)
class Source:
    """One third-party source, and what the app owes it.

    ``present`` is the whole reason this is a dataclass rather than a constant: the SRD is
    always there and the optional rulebook usually is not, so a client renders the list it
    is given rather than deciding for itself which notices apply.
    """

    key: str
    name: str
    holder: str
    licence: str
    licence_url: str
    source_url: str
    attribution: str
    present: bool
    # What the source is *for*, in one line. A reader who has never heard of the SRD needs
    # to know why a spellbook app is quoting Wizards of the Coast at them.
    note: str = ""


def sources() -> list[Source]:
    """Every third-party source this app knows about, present or not.

    Returned in full rather than filtered so a caller can report what is *missing* as well
    as what is installed - the licensing screen says "not installed" for the optional
    rulebook rather than silently omitting it, which is the difference between "this app
    does not use that" and "this app cannot tell you".
    """
    return [
        Source(
            key="srd",
            name="System Reference Document 5.2.1",
            holder="Wizards of the Coast LLC",
            licence="CC-BY-4.0",
            licence_url="https://creativecommons.org/licenses/by/4.0/",
            source_url="https://github.com/downfallx/dnd-5e-srd-markdown",
            attribution=SRD_ATTRIBUTION,
            present=rules.srd_dir().is_dir(),
            note=(
                "The 2024 rules text quoted by the Rules tab and used to ground "
                "recommendations. Vendored as Markdown under context/srd/."
            ),
        ),
        Source(
            key="ionas-politis",
            name="DnD Character Sheet Helper",
            holder="Ionas Politis",
            licence="GPL-3.0",
            licence_url="https://www.gnu.org/licenses/gpl-3.0.html",
            source_url="https://github.com/IonasPolitis/DnD-Character-Sheet-Helper",
            attribution=(
                "The optional second rules source is read in place from a checkout of "
                "DnD Character Sheet Helper by Ionas Politis, licensed GPL-3.0. Its "
                "content is not redistributed by this project."
            ),
            present=ionas.available(),
            note=(
                "An optional second 2024 rules source, read in place when its folder is "
                "installed. It fills the subclasses the SRD does not carry."
            ),
        ),
    ]


def present_sources() -> list[Source]:
    """Only the sources whose content is actually installed.

    The list a client renders as an obligation. ``sources()`` is the list a licensing screen
    renders, because it can also say what is absent.
    """
    return [source for source in sources() if source.present]
