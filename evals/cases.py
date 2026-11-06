"""The contextual-menu cases worth measuring.

Each case is a real selection with a known-good answer, recorded from an actual session
rather than invented. A case is only worth keeping if someone would notice the answer going
wrong, which is why several of them are cases the *current* prompt gets wrong - an eval whose
cases all pass already measures nothing.

The fields:

``selection``
    What the reader highlighted, verbatim.
``context``
    The paragraph it came from. This is what the UI sends and what lets a fragment be read
    as the thing it is about.
``attachments``
    The documents the question should carry. Left empty to mean "whatever the selection
    mentions resolves to", which is also what the running app does when the reader removes
    nothing.
``must_mention`` / ``must_not_mention``
    Substrings, matched case-insensitively against the answer. Chosen to be *facts that only
    the attached document carries*, so a case cannot pass by luck or by fluent recall: the
    SRD does not contain "2d6 at 5th level", so only reading the Thorn Whip document can
    produce it.
``why``
    What the case is testing, for a failure report. A number that goes down without a reason
    attached is not actionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    name: str
    selection: str
    context: str = ""
    attachments: tuple[str, ...] = ()
    must_mention: tuple[str, ...] = ()
    must_not_mention: tuple[str, ...] = ()
    # The document text must have reached the model at all. Separate from `must_mention`
    # because an answer can be right about a spell it was never given - which is the failure
    # that matters most here, since it looks exactly like a good answer.
    must_attach: tuple[str, ...] = ()
    why: str = ""
    # Marks a case the current prompt is known to fail, so a run can report progress against
    # a baseline instead of pretending the suite was ever green.
    known_bad: bool = False


WHY_FIELD = "why"
CASES: tuple[Case, ...] = (
    Case(
        name="named-spells-are-read",
        why=(
            "The case that prompted all of this. The selection names two spells and states "
            "their rules; the answer has to come from those two documents. Reporting 'the "
            "SRD does not cover Thorn Whip' is the failure, and it was what the app did."
        ),
        selection=(
            "If Repelling Blast misses or you need a second angle, Thorn Whip is a 30-ft "
            "melee spell attack for 2d6 and pulls the rust monster 10 ft toward you"
        ),
        context=(
            "Use Eldritch Blast + Repelling Blast as the primary peel: each hit pushes the "
            "rust monster 10 ft away from the fighter/armour, and two beams can push it 20 "
            "ft. If Repelling Blast misses or you need a second angle, Thorn Whip is a 30-ft "
            "melee spell attack for 2d6 and pulls the rust monster 10 ft toward you—position "
            "so that pull drags it off the fighter."
        ),
        must_attach=("Thorn Whip", "Repelling Blast"),
        # The cantrip upgrade is in Thorn Whip's own text and nowhere else in the SRD.
        must_mention=("1d6", "druid"),
        must_not_mention=("does not cover Thorn Whip", "not cover Thorn Whip"),
    ),
    Case(
        name="an-invocation-is-not-a-spell",
        why=(
            "Repelling Blast is a class feature, not a spell, and its text comes from the "
            "SRD's class chapter through find_invocation. An answer that treats it as a spell "
            "the character casts would be a category error the app avoids everywhere else."
        ),
        selection="Repelling Blast pushes it 10 ft away on every hit",
        must_attach=("Repelling Blast",),
        must_mention=("Eldritch Blast",),
    ),
    Case(
        name="a-fragment-with-no-names-still-answers",
        why=(
            "The original fragment case, with no spell name in it at all. Nothing is "
            "attached, so this is the path where retrieval alone has to work - and it must "
            "not borrow the document machinery as a crutch."
        ),
        selection="2 beams",
        context=(
            "Eldritch Blast + Repelling Blast as the primary peel: each hit pushes the rust "
            "monster 10 ft away, and two beams can push it 20 ft."
        ),
        must_mention=("two beams",),
    ),
    Case(
        name="the-selection-overrides-the-books-numbers",
        why=(
            "A book's prose can be wrong, and the selection claims a specific number. The "
            "answer has to come from the attached document rather than agreeing with the "
            "book: Thorn Whip is 1d6, not 2d6, until 5th level. An answer that just restates "
            "the selection is worthless here."
        ),
        selection="Thorn Whip deals 3d8 piercing damage and pulls 30 ft",
        attachments=("Thorn Whip",),
        must_mention=("1d6",),
        must_not_mention=("3d8",),
    ),
    Case(
        name="a-term-the-srd-lacks-is-refused-not-invented",
        why=(
            "Rust Metal appears nowhere in the 2024 SRD, and nothing is attached, so there is "
            "no rule to quote and the honest answer names the gap. A model that explains the "
            "rust monster's 2014 ability from memory is the exact failure this project's "
            "rules-only stance exists to prevent."
        ),
        selection="Rust Metal corrodes the plate armour",
        must_mention=("not",),
        known_bad=True,
    ),
    Case(
        name="scope-is-limited-to-the-selection",
        why=(
            "The selection is about one thing; the answer should not wander into the rest of "
            "the book (Mending, Spare the Dying, Find Familiar). Long answers that mention "
            "everything are how a prompt looks thorough while being less useful."
        ),
        selection="Spare the Dying has 30-ft range at level 5",
        context=(
            "Spare the Dying has 30-ft range at level 5, so if the fighter drops and Healing "
            "Light is exhausted, stabilise from range. Find Familiar gives an owl that can "
            "Help. Mending repairs a single break."
        ),
        must_attach=("Spare the Dying",),
        must_mention=("stable",),
        must_not_mention=("mending", "find familiar"),
    ),
    Case(
        name="the-character-context-is-used",
        why=(
            "The sheet is loaded into every prompt, and a contextual answer about a Warlock "
            "should say what a Warlock can do with the spell. Nothing else in the suite "
            "checks that the character block is reaching the model at all."
        ),
        selection="Thorn Whip is a 30-ft melee spell attack",
        context="Level 1 Rituals: Find Familiar, Detect Magic",
        must_attach=("Thorn Whip",),
        must_mention=("cantrip",),
    ),
)

CASES_BY_NAME = {case.name: case for case in CASES}
