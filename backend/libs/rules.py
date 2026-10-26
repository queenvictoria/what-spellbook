"""Answer rules questions from the vendored 2024 SRD text.

The rules live in ``context/srd/`` as Markdown, redistributed from SRD 5.2.1 under
CC-BY-4.0 (see ``context/srd/PROVENANCE.md``). Three things make this more than a grep:

* **Edition.** This project is 2024-only. The vendored files are SRD 5.2.1, and the
  spell corpus's legacy naming is a separate, tracked concern - a 2014 answer would
  contradict the 2024 context the prompts are built on.
* **Heading-anchored matching.** A rule is defined *under its own heading*. Searching
  loose paragraphs is how "Grappling Hook" in a price list answered a question about
  grappling, and how a travel-pace sentence about mounts answered a question about
  short rests. A section qualifies only if its heading is about the question.
* **Tables are the rules.** The vendored Markdown carries 51 HTML tables and the SRD
  genuinely defines things there - the degrees of cover are a table, the actions are a
  table. The prose around them says "as detailed in the Cover table", so dropping the
  markup would silently leave a confident answer with its numbers missing.

Reading local files rather than fetching a website is not only faster and offline. The
source previously used, ``5e24srd.com``, **omits large parts of the SRD**: its pages
cross-reference a "Rules Glossary" it does not publish, so a short-rest or condition
question could not be answered from it at all. The glossary is vendored here.

**The cache holds the model's answer, not the retrieval.** Retrieval is a local file
read costing milliseconds, so caching it would trade a staleness risk - an edited file
would keep serving old text - for no benefit. The expensive part, the model call, is
cached under ``.cache/rules/`` keyed by the normalised question, and each entry records
the ``source`` files it used so a stale answer is attributable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from . import config

# The vendored 2024 SRD. Kept as a directory of Markdown files rather than a URL because
# the rules must keep working offline, must be diffable when the SRD is reissued, and are
# redistributable: SRD 5.2.1 is CC-BY-4.0. See ``context/srd/PROVENANCE.md``.
SRD_DIR = "context/srd"
RULES_SOURCE = "vendored-srd-5.2.1"

# The retrieval's own version, distinct from ``RULES_SOURCE``. A cached answer is only
# as good as the text it was grounded in, so changing *which* text a question retrieves
# invalidates it just as changing the source file does - and unlike the source, nothing
# about the file on disk changed to signal it. Bump this whenever the passages a question
# returns would differ, or the old answers outlive the fix.
#
# 3: question-framing verbs became stopwords, so a question phrased conversationally
#    ("explain the initiative system to me like I'm 12yo") now retrieves the rule it is
#    about instead of being refused. Answers cached under 2 were written from the refusal
#    or from the wrong passage.
# 4: a verb now folds to the noun the rulebook names the rule with, so "concentrate"
#    reaches the heading "Concentration". Questions that were refused, or answered from
#    unrelated prose, now retrieve the rule - so answers cached under 3 are stale.
RETRIEVAL_VERSION = 4

# Used when a spell is in the retrieval corpus but not the SRD. The distinction is shown
# in the UI, because the SRD is the 2024 authority and the corpus is not.
CORPUS_SOURCE = "retrieval-corpus"

# The SRD's class chapter. It is where the Eldritch Invocation options live, and it is the
# only vendored file that carries their effect text.
CLASSES_FILE = "classes.md"
# The anchor for the invocation options within that chapter. The file is 11,000 lines of
# class features, so the section is located by heading rather than by scanning for names.
INVOCATION_SECTION = "Eldritch Invocation Options"

# Used when an invocation is in our own class context but not the vendored SRD. The
# distinction is shown in the UI, because the SRD is the 2024 authority and our context is
# not - and our context carries only the level and prerequisite, not what the invocation
# does.
CLASS_SOURCE = "class-context"

# The class context files that carry invocation tables, in the order a lookup should try
# them. The base class file holds the full list; the pact files hold the handful that
# relate to that pact. These are the fallback for an invocation the SRD does not carry.
INVOCATION_FILES = (
    "classes/warlock/base.md",
    "classes/warlock/pact/tome.md",
    "classes/warlock/pact/blade.md",
    "classes/warlock/pact/chain.md",
)

# Citation shown when a question matches nothing, so the reply still points somewhere.
RULES_INDEX = "context/srd/playing-the-game.md"

# Ordered by usefulness to a rules question. The glossary is first because it is where
# the 2024 SRD defines single terms - rests, conditions, actions, "Cover" - and it is
# the part the previously-scraped website did not publish at all.
PREFERRED_FILES = (
    "rules-glossary.md",
    "playing-the-game.md",
    "gameplay-toolbox.md",
    "equipment.md",
)

# Edition guards. A source is refused *before* any text is read, so a 2014 file can never
# be silently used: this project is 2024-only and a 2014 answer would contradict the 2024
# context the prompts are built on. A real guard rather than a comment because the
# sources are files now, and a file is easy to add by mistake.
BANNED_SOURCES = {
    "5thsrd.org": "serves the 2014 SRD (5.1), not 2024; its own banner says so",
    "www.5thsrd.org": "serves the 2014 SRD (5.1), not 2024; its own banner says so",
    "5e24srd.com": (
        "omits the Rules Glossary and most conditions, so it cannot answer rest and "
        "condition questions at all; superseded by the vendored SRD"
    ),
}

_CACHE_SUBDIR = "rules"
_QUESTION_HASH_LENGTH = 12


class RulesUnavailable(RuntimeError):
    """Raised when the SRD text cannot be read or nothing in it answers the question."""


def normalise(question: str) -> str:
    """Fold a question so trivial rewording hits the same cache entry."""
    return " ".join(str(question).lower().split()).strip(" ?.!")


def question_fingerprint(question: str) -> str:
    """Short stable hash of a normalised question, used as the cache filename."""
    digest = hashlib.sha256(normalise(question).encode("utf-8")).hexdigest()
    return digest[:_QUESTION_HASH_LENGTH]


def slug(question: str, *, max_length: int = 48) -> str:
    """Readable part of the cache filename, so the directory can be browsed."""
    words = re.findall(r"[a-z0-9]+", normalise(question))
    return ("-".join(words)[:max_length].strip("-")) or "question"


def _cache_dir(cache_dir=None) -> Path:
    """``.cache/rules/`` - rules answers are cached beside the generated books."""
    root = Path(cache_dir) if cache_dir is not None else config.CACHE_DIR_PATH
    return root / _CACHE_SUBDIR


def entry_path(question: str, cache_dir=None) -> Path:
    """Cache file for a question: readable slug plus a short hash."""
    return cache_dir_path(question, cache_dir)


def cache_dir_path(question: str, cache_dir=None) -> Path:
    return _cache_dir(cache_dir) / f"{slug(question)}-{question_fingerprint(question)}.json"


def srd_dir() -> Path:
    """Absolute path to the vendored SRD directory.

    Goes through ``config.resolve`` rather than using ``SRD_DIR`` directly: a bare
    relative path resolves against the *process* CWD, so running the CLI from another
    directory would silently find no rules at all.
    """
    return config.resolve(SRD_DIR)


def source_files() -> list[Path]:
    """Every vendored SRD file, preferred ones first.

    Ordering only breaks ties. All files are searched for every question, because a rule
    can legitimately appear in more than one place and the file holding the *defining*
    section should win on match quality, not on the order the files were listed.
    """
    directory = srd_dir()
    if not directory.is_dir():
        return []
    found = [directory / name for name in PREFERRED_FILES if (directory / name).is_file()]
    extras = sorted(
        path for path in directory.glob("*.md")
        if path.name not in PREFERRED_FILES and path.name != "PROVENANCE.md"
    )
    # PROVENANCE.md is the CC-BY-4.0 attribution, not SRD text. Including it would let
    # licence boilerplate answer a question about "work" or "rights".
    return found + extras


def check_source(source) -> None:
    """Refuse a 2014 source before any text is read."""
    text = str(source).lower()
    for banned, reason in BANNED_SOURCES.items():
        if banned in text:
            raise RulesUnavailable(
                f"{banned} is not a permitted rules source ({reason}); this project is "
                "2024 only."
            )


def read_srd(path) -> str:
    """Read one SRD Markdown file, refusing a banned source first."""
    check_source(path)
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise RulesUnavailable(f"Could not read {path} ({e}).") from e


# Group markers that hold rules *within* a section: ``<details>``/``<summary>``, and the
# bold run-in labels the SRD uses for the parts of a rule ("**Special Feature.**"). They
# are promoted to headings because the SRD nests real rules this way - the literal string
# "Actions" appears nowhere in the vendored text, yet the Actions table and every
# individual action hang off exactly such a group, so without this a question about an
# action's trigger or limit cannot reach the text that answers it.
_SUMMARY = re.compile(r"^\s*<summary>\s*(.*?)\s*</summary>\s*$", re.I)

# A whole line of bold or italic: a table caption or a section name.
_RUN_IN_WHOLE = re.compile(r"^\s*(?:\*\*|_)([^*_]{2,60}?)(?:\*\*|_)\s*$")

# A run-in label followed by its text on the same line. The trailing full stop is required,
# because that is the convention and without it any sentence opening in bold would be
# promoted - splitting a paragraph into a bogus heading and a fragment.
_RUN_IN_INLINE = re.compile(r"^\s*(\*\*|_)([^*_]{2,60})\.\1\s+(.*)$")


def _promote_groups(markdown: str) -> str:
    """Turn ``<details>`` groups and run-in labels into ``###`` headings.

    A label that merely repeats the heading already in force is *not* promoted. The SRD
    captions each table with the name of the section it belongs to ("**Cover**"), and
    promoting that caption splits the rule in two - the prose under one heading, the
    numbers under another - so a retrieval limit of three sections could return the
    explanation without the table it refers to.
    """
    out = []
    current = None
    for line in markdown.splitlines():
        if heading := re.match(r"^#{1,4}\s+(.*)$", line):
            current = heading.group(1).strip().lower()
            out.append(line)
            continue
        if re.match(r"^\s*</?details[^>]*>\s*$", line, re.I):
            continue
        label = rest = None
        if match := _SUMMARY.match(line):
            label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        elif match := _RUN_IN_WHOLE.match(line):
            # The whole line is the label, and it takes no full stop: the SRD captions each
            # table with the name of its section ("**Cover**").
            label = match.group(1).strip()
        elif match := _RUN_IN_INLINE.match(line):
            # A run-in label: the convention the SRD uses throughout for the parts of a
            # rule ("_Benefits of the Rest._ When you finish...") and for cases within one
            # ("_Shove._ The target must succeed..."). It is inline - the label and its text
            # share a line - which is why the standalone pattern above caught exactly one
            # line in the whole SRD and missed all 240 of these. "Shove" is a rule defined
            # *only* this way, as the third of three cases under "Unarmed Strike", so
            # without promoting it "how do I shove a creature" had nowhere to land.
            label = match.group(2).strip()
            rest = match.group(3).strip()
        if label and label.lower() != current:
            # Promoted at ``#####``, a level no SRD file uses. It has to be *distinct* from
            # every heading the source itself writes, because the promotion is what makes a
            # run-in label a part of the rule above it rather than a rule of its own. The
            # two are separated again by :func:`markdown_to_text`, which flattens a real
            # heading to ``##`` and a promoted label to ``###``, and :func:`_sections` reads
            # that difference as the parent link.
            out.append(f"##### {label}")
            if rest:
                out.append(rest)
            continue
        out.append(line)
    return "\n".join(out)


_TAG = re.compile(r"<[^>]+>")
_ENTITY = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
           "&#39;": "'", "&mdash;": "\u2014", "&ndash;": "\u2013"}


def _unescape(text: str) -> str:
    for entity, char in _ENTITY.items():
        text = text.replace(entity, char)
    return text


def tables_to_text(markdown: str) -> str:
    """Render the SRD's embedded HTML tables as plain declarative sentences.

    **The rules are in the tables.** The vendored Markdown carries 51 HTML tables and the
    SRD genuinely defines things there - the degrees of cover are a table, the actions are
    a table, difficulty classes are a table - while the surrounding prose only says "as
    detailed in the Cover table". Stripping the markup would leave the answer as the words
    "Cover" and "Benefit to Target" with every number gone: a confident answer missing the
    numbers that make it useful.

    Each row becomes ``header: cell; header: cell.`` so a passage reads on its own and can
    be quoted. ``rowspan``/``colspan`` are not honoured: no SRD table uses them, and
    guessing at spanning would silently misalign columns.
    """
    def render(match):
        table = match.group(0)
        headers = [_unescape(_TAG.sub(" ", cell)).strip()
                   for cell in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S | re.I)]
        out = []
        for row in re.split(r"</tr>", table, flags=re.I):
            cells = [re.sub(r"\s+", " ", _unescape(_TAG.sub(" ", cell))).strip()
                     for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            parts = []
            for index, cell in enumerate(cells):
                header = headers[index] if index < len(headers) else ""
                header = re.sub(r"\s+", " ", header).rstrip(" \u2026").strip()
                parts.append(f"{header}: {cell}" if header else cell)
            # A cell often ends in its own full stop; adding another gives "behavior..".
            row_text = "; ".join(parts)
            out.append(row_text if row_text.endswith(".") else row_text + ".")
        return "\n".join(out) if out else ""

    return re.sub(r"<table>.*?</table>", render, markdown, flags=re.S | re.I)


def markdown_to_text(markdown: str) -> str:
    """Flatten SRD Markdown to headings plus prose.

    Headings are re-emitted as ``##`` sentinels because a rule is defined *under its own
    heading*. That is the whole basis of the matcher: it is the difference between the
    section titled "Cover" and a sentence that merely says "an object that covers the
    whole target", and without it nothing can tell a rule from a mention of one.
    """
    text = tables_to_text(_promote_groups(markdown))
    out = []
    for line in text.splitlines():
        if heading := re.match(r"^(#{2,5})\s+(.+?)\s*$", line):
            # ``#####`` is :func:`_promote_groups`' marker for a run-in label, so it
            # survives as ``###`` and stays distinguishable from a heading the SRD wrote.
            depth = "###" if heading.group(1) == "#####" else "##"
            out.append(f"{depth} {heading.group(2)}")
            continue
        if line.strip().startswith("```"):
            continue
        out.append(_unescape(_TAG.sub(" ", line)))
    text = "\n".join(out)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# Words that carry no retrieval signal. Without this, "what is a short rest" scores a
# passage highly for containing "is" and "a", and a passage about *when time is short*
# outranks one that actually mentions resting. Question-framing verbs ("how does X
# work", "what does X mean") are included because they name the question, not the rule.
_STOPWORDS = frozenset("""
a about am an and any are as at be been being but by can could did do does doing done
for from get gets go got had has have having he her him his how i if in into is it its
just like make makes me mean means more most much must my need no nor not of ok on or
rule rules
other our out over own said same she should so some such than that the their them then
there these they this those to too up us use used uses using very was way we what when
where whether which while who whom why will with work works would you your
""".split())

# Words that carry no retrieval signal. Without this, "what is a short rest" scores a
# passage highly for containing "is" and "a", and a passage about *when time is short*
# outranks one that actually mentions resting. Question-framing verbs ("how does X work",
# "what does X mean") are included because they name the question, not the rule.
#
# The framing verbs below are the *asking* half of that list, and they are not optional
# filler. A framing verb is rare in a rulebook - it is a word about asking, not about
# playing - so :func:`term_weight` rates it as highly distinctive, and it then wins the
# subject election in :func:`_qualifies` against the word the question is actually about.
# "explain the initiative system to me like I'm 12yo" elected "explain" (0.905) over
# "initiative" (0.881), and since no heading contains "explain" the heading-anchored gate
# refused the question outright - so a question the SRD answers perfectly well was reported
# as absent. The rarer the framing verb, the worse it fails: "elaborate on exhaustion"
# elected "elaborate" at 0.98.
#
# Every word here was checked against the real heading set, because some framing words are
# also rules and dropping them breaks working questions. "help" is the trap - "Help
# [Action]" is a heading, so "how does the help action work" must keep it. The same goes
# for "describe", "list", "find", "learn", "need", "read" and "see", all of which name
# headings. Only words that name no heading at all are listed.
#
# Inflections are spelled out rather than left to :func:`_fold`, because stopwords are
# subtracted *before* folding - so "explaining" has to be listed to be dropped, and
# "explain" alone would not cover it. "known" is deliberately absent: it folds to itself
# rather than to "know", and "Known Forms" is a heading.
_FRAMING_STOPWORDS = frozenset("""
ask asked asking asks
clarified clarifies clarify clarifying
define defined defines defining
elaborate elaborated elaborates elaborating
explain explained explaining explains
gave give given gives giving
know knowing knows
let lets letting
look looked looking looks
say saying says
show showed showing shown shows
summarise summarised summarises summarising
summarize summarized summarizes summarizing
taught teach teaches teaching
tell telling tells told
tried tries try trying
understand understanding understands understood
walk walked walking walks
want wanted wanting wants
""".split())

_STOPWORDS = _STOPWORDS | _FRAMING_STOPWORDS


def _fold(word: str) -> str:
    """One canonical form for a word, so every inflection of a root folds together.

    Order matters, and the trailing "e" is the subtlety: "stabilize" and "stabilizing"
    must fold to the same string or a question using one form cannot match a heading using
    the other. Stripping "-ing" and "-ed" leaves "stabiliz", which the unsuffixed
    "stabilize" only meets if its silent "e" is dropped too - which is why "how do I
    stabilize a creature" missed the section titled "Stabilizing a Character".
    """
    if word.endswith("s") and len(word) > 4:        # conditions -> condition
        word = word[:-1]
    if word.endswith("ing") and len(word) > 5:      # grappling  -> grappl
        word = word[:-3]
    elif word.endswith("ed") and len(word) > 4:     # grappled   -> grappl
        word = word[:-2]
    # The rulebook names a rule with the *noun* and a question asks with the *verb*:
    # "how do I concentrate on a spell" against the heading "Concentration". Folding only
    # the verb left the question asking for ``concentrat`` while the heading said
    # ``concentration``, so the glossary's own definition of Concentration could not be
    # found at all. The remainder must be a real stem, so "moment" does not become "mo".
    elif word.endswith("ion") and len(word) > 5:    # concentration -> concentrat
        word = word[:-3]
    elif word.endswith("ment") and len(word) > 7:   # attunement -> attune
        word = word[:-4]
    if word.endswith("e") and len(word) > 3:        # stabilize  -> stabiliz
        word = word[:-1]
    return word


def _terms(question: str) -> set[str]:
    """Meaningful terms in a question, folded so grammatical variants still match.

    Suffix folding rather than a stemmer: "grappling" must match "Grappled", and
    "conditions" must match "condition". Without it, "how does grappling work" found only
    the string "Grappling Hook" in an equipment list, because the rulebook says
    "Grappled" - so the answer came from a tool description.

    Only the stem is emitted, not the stem plus the original. Emitting both inflated the
    term set ("grappling" produced ``grappl``, ``grappling`` *and* a bogus ``grappll``),
    which then lowered coverage on the page that actually had the rule and let a weaker
    page win.

    Two characters, not three: the rulebook's short words are acronyms - DC, AC, HP, XP -
    and dropping them let "what is my spell save dc" match a shop entry titled "Spell
    Scroll (Cantrip, 30 GP)" on the words "spell" and "save" alone, so the answer was
    simply wrong. The English filler a two-letter match would otherwise admit is already
    in ``_STOPWORDS``.
    """
    words = {w for w in re.findall(r"[a-z]{2,}", normalise(question))}
    words -= _STOPWORDS
    return {_fold(word) for word in words}


def _term_pattern(term: str) -> re.Pattern:
    """Regex matching ``term`` and the inflections :func:`_fold` collapses.

    The inverse of the folding, spelled out as alternatives, rather than a prefix match.
    A prefix match with a left word boundary is wrong: ``\brest`` matches "Restrained"
    and "Restoration", so "what is a long rest" was answered from the Restrained
    condition, whose heading merely *starts* with the same letters. Anchoring both sides
    admits exactly what folding removes and nothing more.

    Kept in step with ``_fold`` by mirroring it; ``test_rules.py`` asserts the two are
    inverse for a sample of inflections, because a silent drift between them is invisible
    until a question quietly stops matching.
    """
    # The nominal forms mirror the "ion"/"ment" stripping in :func:`_fold`, and the plural
    # of each is needed too: "conditions" folds to ``condit``, so the pattern for
    # ``condit`` has to reach "conditions" or the fold and its inverse disagree.
    forms = {term, term + "s", term + "es", term + "e", term + "d", term + "ed",
             term + "ing", term + "ion", term + "ions", term + "ment", term + "ement"}
    forms = sorted(forms, key=len, reverse=True)
    return re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(f) for f in forms) + r")(?![a-z])")


# Text the SRD uses to point elsewhere: "as defined in \"Rules Glossary\"", "_See also_
# \"Speed.\"". Demoted, because a pointer is weaker evidence than a definition.
#
# This used to be a heavy penalty, applied because the previous source published the
# pointers but not the Rules Glossary they pointed at, so a pointer could only ever lead
# nowhere. The glossary is vendored now, so the targets exist and a cross-reference is a
# genuine hint - but still not the rule itself.
_CROSS_REFERENCE = re.compile(
    r"(see\s+also|see\s+the\s+\w+\s+table|as\s+(?:detailed|defined|described)\s+in"
    r"|defined\s+in)",
    re.I,
)

# Sections whose headings are catalogue entries rather than rule definitions.
#
# Narrowed from a long keyword list to the price pattern alone. Every keyword tried was
# also a real heading somewhere in the SRD, and the glossaries are *supposed* to hold
# single-word definitions, so an exclusion on a word like "Armor" holds the word, not a
# list: it silently discarded "Armor Class", "Armor Training", "Weapon", "Weapon Attack",
# "Improvised Weapons", "Spellcasting Focus" and "Tools". "Grappling Hook (2 GP)" is a
# catalogue entry and the price catches it; "Weapon" is a rule and must not be caught.
_ITEM_HEADING = re.compile(
    r"\([^)]*\b\d[\d,]*\s*(?:gp|sp|cp|lb)\b[^)]*\)|\(\s*varies\s*\)", re.I
)

# Headings that are structure rather than rules: the procedural "step" headings inside
# character creation, and index-like headings.
_NON_RULE_HEADINGS = re.compile(
    r"^\s*\d+:\s|\b(table|example|sample|list|expenses|conventions)\b", re.I
)

# Two thresholds, and together they are the whole of the decision to answer or refuse.
#
# The SRD defines a rule under a heading that names it, so the question is whether some
# heading names what the question is *about*. Every attempt to measure that as a ratio of
# matched words failed, because counting words cannot tell a heading that names the subject
# from one that mentions a word of it: "Cover" and "Combat Encounter Difficulty" both
# matched their question exactly once, so they competed on nothing but section length and
# the looser heading sometimes won.
#
# What separates them is how much each matched term tells you. Nearly every question
# carries a word that is everywhere in a rulebook - "creature", "spell", "weapon" - and a
# heading match on one of those is no evidence at all. "Creature" is a glossary entry, so
# "how do I shove a creature" and "how do I stabilize a creature" both *matched a heading*
# on it, and the definition of a creature came back as the answer. A heading match only
# means something when the term is distinctive.
#
# So each term is weighted by how few sections of the SRD contain it, and a question is
# answerable only when the SRD has a heading naming the question's **most distinctive
# term**, and that term is distinctive enough to be the subject of a rule at all.
#
# A floor, not the main guard. A term absent from the SRD weighs exactly zero, and no
# question about it can be answered - "how does a spear work" has no heading to land on and
# is refused. The floor additionally sets aside the handful of words so generic in a
# rulebook that a single-word question about one is not really a question: at 0.65,
# ``spell`` (0.63) is below it while ``swim``, ``skill`` and ``fly`` are above, which
# matches where the SRD actually defines a term.
#
# Deliberately not higher. Setting it at 0.75 read well ("spell is too broad") but also
# rejected ``condition`` (0.67) and ``bonus action`` (0.72), which name two of the
# glossary's own entries - refusing the SRD's own rules to keep out one generic word.
_MIN_SUBJECT_WEIGHT = 0.65

# And the winning heading must account for this fraction of the question's remaining
# substance. Set at a half: "Hide [Action]" accounts for over half of "can I hide in
# combat" (the rest is the context the question was asked in), while a heading that
# accounts for only a third is talking about something the question did not ask about.
_HEADING_SHARE = 0.5

# And the winning heading must not be *qualified* by a distinctive word the question never
# mentioned. A heading that adds a real word is naming a different thing: "how does a spear
# work" was answered with "Eldritch Spear" once the class chapter was vendored, because
# "spear" is the only weapon name that appears in any heading and the Spear itself lives
# inside an equipment table with no heading of its own.
#
# The threshold is what separates a qualifier from a stemming artifact. A word the
# question did mention but that stems differently weighs exactly zero - "wild shape" leaves
# "shape" at 0.0 against "Wild Shape", and "grappling" at 0.0 against "Grappling" - so a
# floor above zero ignores those while still catching "eldritch" at 0.93.
_MIN_QUALIFIER_WEIGHT = 0.5

# How many rules to hand the model. Passages are *rules*, not fragments: a rule's parts
# are grouped back under it before this is applied, so four is four rules rather than the
# three-and-a-half that three fragments used to buy.
_PASSAGE_LIMIT = 4


# Built once, lazily, from the vendored files: term -> number of sections containing it.
_SECTION_FREQUENCY: dict[str, int] | None = None
_SECTION_TOTAL = 0


def section_frequency() -> tuple[dict[str, int], int]:
    """How many SRD sections contain each folded term, and how many sections there are.

    Counted over section *bodies*, not headings, and that distinction is the whole point.
    "Creature" appears in only ten headings but in hundreds of sections, so measuring
    rarity against headings alone rated it almost as distinctive as "Stabilizing" - and
    "how do I stabilize a creature" was then answered with the glossary's definition of a
    creature, because a heading naming the generic object of the question looked like a
    heading naming its subject. Frequency over the text as a whole captures what actually
    matters: a word the rulebook uses everywhere cannot identify a rule.

    Computed from the vendored files rather than hard-coded, so it stays correct when the
    SRD is reissued - a term that becomes common automatically loses its power. Cached
    because it costs a pass over all four files.
    """
    global _SECTION_FREQUENCY, _SECTION_TOTAL
    if _SECTION_FREQUENCY is not None:
        return _SECTION_FREQUENCY, _SECTION_TOTAL

    counts: dict[str, int] = {}
    total = 0
    for path in source_files():
        try:
            text = markdown_to_text(read_srd(path))
        except RulesUnavailable:
            continue
        for heading, body, _parent in _sections(text):
            total += 1
            for word in {_fold(w) for w in re.findall(r"[a-z]{2,}", f"{heading} {body}".lower())}:
                counts[word] = counts.get(word, 0) + 1
    _SECTION_FREQUENCY = counts
    _SECTION_TOTAL = total
    return counts, total


def term_weight(term: str) -> float:
    """How much a term narrows the search, in ``0.0``-``1.0``.

    Zero for a term that appears in no section at all, because "how does a spear work"
    would otherwise score infinitely well on ``spear`` - which sounds helpful until you
    notice the question cannot be answered, since the SRD has no section about spears.
    Treating an unmatched term as maximally rare turns "not found" into "found", so
    absence has to be worth nothing.
    """
    counts, total = section_frequency()
    if not total or term not in counts:
        return 0.0
    # Normalised document frequency: a term everywhere in the book carries no signal, a
    # term the book uses once carries almost all of it.
    return 1.0 - (counts[term] / total) ** 0.5


def _sections(text: str) -> list[tuple[str, str, int]]:
    """Split flattened text into ``(heading, body, parent)`` triples.

    Content before the first heading is kept under an empty heading, because the
    introduction to a chapter is often real rule text.

    ``parent`` is the index of the section this one belongs to, or ``-1`` for a top-level
    section. ``###`` marks a run-in label promoted by :func:`_promote_groups`, which the
    SRD uses for the *parts* of a rule - "Ending a Grapple" inside "Grappling", "Shove"
    inside "Unarmed Strike" - so each promoted section points at the real heading that
    introduced it. Without that link the parts read as independent rules: the retrieval
    limit then filled up with the opening paragraphs and cut the rule's own conclusion,
    and "how does grappling work" was answered without the rules for escaping a grapple.

    A promoted section two levels deep ("Attacks Affected" inside "Blinded [Condition]")
    attaches to the nearest real heading above it, whichever depth that is. The level the
    SRD wrote carries no meaning here, because the flattened text has already lost it.
    """
    # Longest alternative first: as "##|###" the regex matches the first two hashes of a
    # "###" line and leaves the third in the heading, so every promoted label read as a
    # top-level heading and no parent link was ever recorded.
    parts = re.split(r"^(###|##)[ \t]*(.*)$", text, flags=re.MULTILINE)
    # re.split with capture groups yields [lead, mark1, head1, body1, mark2, head2, ...].
    marks, heads, bodies = parts[1::3], parts[2::3], parts[3::3]

    sections: list[tuple[str, str, int]] = []
    lead = parts[0].strip()
    if lead:
        sections.append(("", lead, -1))

    parent = -1
    for mark, head, body in zip(marks, heads, bodies):
        heading, body = head.strip(), body.strip()
        if mark == "##":
            # Only a real heading can be a parent, and only once it has a body to be one:
            # a heading whose text all sits under its sub-headings defines nothing itself.
            parent = -1
            if body:
                parent = len(sections)
                sections.append((heading, body, -1))
        elif body:
            sections.append((heading, body, parent))
    return sections


def _score_sections(sections: list[tuple[str, str, int]],
                    question: str) -> list[tuple[float, int, str, str, int]]:
    """Every section in ``sections`` that matches, as ``(score, position, heading, body,
    parent)``.

    Returned rather than formatted so :func:`gather` can compare matches *across files* on
    score. Comparing on anything else picks the wrong file: "what is a long rest" was
    answered from an equipment entry titled "Attune during a Short Rest" merely because
    that passage happened to be the longest.

    Each item is ``(score, position, heading, body, parent)``; ``parent`` is the index of
    the section this one is part of, which :func:`_format` uses to expand a matched rule to
    its parts rather than returning an opening paragraph with the rule missing.
    """
    terms = _terms(question)
    if not terms:
        return []
    ordered = sorted(terms)
    patterns = [_term_pattern(term) for term in ordered]
    weights = [term_weight(term) for term in ordered]
    total_weight = sum(weights) or 1.0

    scored = []
    for position, (heading, body, parent) in enumerate(sections):
        heading_lower = heading.lower()
        body_lower = body.lower()

        # A catalogue entry or a structural heading is never the rule. Only applied to
        # sub-entries: a chapter heading ("Actions") is worth matching, and its children
        # are where the rules actually live.
        if heading and (_ITEM_HEADING.search(heading) or _NON_RULE_HEADINGS.search(heading)):
            continue

        heading_hits = sum(1 for pat in patterns if pat.search(heading_lower))
        body_hits = sum(1 for pat in patterns if pat.search(body_lower))
        if not body_hits and not heading_hits:
            continue

        coverage = max(heading_hits, body_hits) / len(terms)
        # A heading hit is worth far more than a body hit: it means this section *is* the
        # rule rather than prose that happens to use the word.
        #
        # The bonus scales with *how much of the question the heading covers*, rather than
        # being all-or-nothing. A flat bonus made "Saving Throws and Damage" tie with
        # "Death Saving Throws" - both merely contained two of the question's terms - and
        # the vaguer heading then won on section length.
        # Weighted so a heading hit on a distinctive word counts for far more than one on a
        # word the rulebook uses everywhere, and so a heading naming every part of the
        # question the SRD can speak to beats one naming only part of it: "Attune during a
        # Short Rest" and the glossary's own "Short Rest" both contain every term of "what
        # is a short rest", and only match quality should separate them.
        heading_signal = sum(
            weight for weight, pat in zip(weights, patterns) if pat.search(heading_lower)
        )
        coverage = max(heading_hits, body_hits) / len(terms)
        score = (2.0 * heading_signal / total_weight
                 + coverage * (1 + 0.1 * min(body_hits, 5)))
        # Long sections are diluted: a huge appendix mentioning the term once is less
        # useful than a short dedicated rule.
        score /= 1 + len(body) / 2500
        # A pointer is weaker evidence than a definition.
        if _CROSS_REFERENCE.search(body) and not heading_hits:
            score /= 1.5
        scored.append((score, position, heading, body, parent))
    return scored


def _matched(text: str, question: str):
    """``(scored sections, folded terms, every section)`` - both entry points' working set.

    The whole section list is returned alongside the scored one so a matched rule can be
    rendered together with the parts of it that did not match on their own. A rule's parts
    are not separately relevant; they are what makes the rule complete, and the ones that
    go unmentioned often are the operative half - "Ending a Grapple" never repeats the word
    the question asked in the way the opening sentence does.
    """
    sections = _sections(text)
    return _score_sections(sections, question), _terms(question), sections


def _qualifies(scored, terms, *, min_subject_weight: float = _MIN_SUBJECT_WEIGHT) -> list:
    """The sections that genuinely answer the question, best first.

    Shared by :func:`find_passages` and :func:`gather` so the single-file path and the
    all-files path cannot drift apart and answer the same question two different ways.

    Four conditions, in order, and each one catches a failure seen in practice:

    1. The question's most distinctive term must be distinctive enough to be a subject
       (``min_subject_weight``). Without it "what is my spell save dc" is answered with
       the heading "Spell".
    2. Some section's *heading* must name that term. This is the heading-anchored rule:
       without it "Hit Points" answered questions about short rests and "Roll Two D20s"
       answered questions about two-weapon fighting, which the SRD does not contain.
    3. Among those, the best must account for half the question's remaining substance
       (``_HEADING_SHARE``). Without it "Combat Encounters" outranked "Hiding" for "can I
       hide in combat", because the two matched their question equally often.
    4. And that heading must not be qualified by a distinctive word the question never
       mentioned (``_MIN_QUALIFIER_WEIGHT``). Without it "how does a spear work" was
       answered with "Eldritch Spear" once the class chapter was vendored.

    Refusing is the honest outcome: the SRD is a subset of the 2024 rulebook, and a
    plausible-looking paragraph presented as the rule reads as sourced.

    ``min_subject_weight`` is the one thing the inferred path relaxes, and it is a
    parameter rather than a second implementation on purpose: the gates below are the
    whole of the decision to answer or refuse, and a copy of them would eventually
    disagree with this one about what a rule is.
    """
    if not scored or not terms:
        return []

    ordered = sorted(terms)
    weights = {term: term_weight(term) for term in ordered}
    subject = max(ordered, key=lambda term: weights[term])
    if weights[subject] < min_subject_weight:
        return []

    pattern = _term_pattern(subject)
    named = [item for item in scored if item[2] and pattern.search(item[2].lower())]
    if not named:
        return []

    named.sort(key=lambda item: (-item[0], item[1]))
    if _discrimination(named[0][2], set(ordered)) < _HEADING_SHARE:
        return []

    # Filtered rather than rejected: a qualified heading is a worse *candidate*, not a
    # reason to refuse the question. "how does grappling work" scores "Grappled Condition"
    # above "Grappling", and dropping the qualified one leaves the right answer.
    unqualified = [
        item for item in named
        if _qualifier_weight(item[2], set(ordered)) < _MIN_QUALIFIER_WEIGHT
    ]
    return unqualified


def _qualifier_weight(heading: str, terms) -> float:
    """The weight of the most distinctive word *qualifying* a heading, or zero.

    A qualifier is a leading modifier: English puts the head noun last, so "Eldritch
    Spear" is a kind of spear and "Arcane Hand" a kind of hand. Only the words *before* the
    first one the question matched are considered, which is what separates a qualifier from
    the rest of the heading:

    * "Eldritch Spear" for "how does a spear work" - "eldritch" leads, at 0.93. Rejected.
    * "Grappled Condition" for "how does grappling work" - "grappled" is the first match,
      so nothing leads it. Kept, and it is the right answer.
    * "Stabilizing a Character" for "how do I stabilize a creature" - "stabilizing" leads.
      Kept.
    * "Level 2: Wild Shape" - the level prefix is stripped, then "wild" leads. Kept.

    The comparison folds the heading's words the same way :func:`_terms` folds the
    question's, because the two are otherwise never equal: the question yields the stem
    ``multiclas`` while the heading says "Multiclass", and ``shap`` against "Shape".
    Comparing raw words made every legitimate heading look like it added something.

    A leading "Level 1:" is stripped first. The class chapter prefixes every feature
    heading with its level, and "level" is a word the rulebook uses everywhere, so it
    carries real weight while saying nothing about the subject.
    """
    subject = re.sub(r"^level\s+\d+\s*:\s*", "", heading.lower())
    leading = []
    for word in re.findall(r"[a-z]{2,}", subject):
        if _fold(word) in terms:
            break
        leading.append(word)
    return max((term_weight(word) for word in leading), default=0.0)


def _discrimination(heading: str, terms) -> float:
    """How much of the question's *substance* the heading accounts for, in ``0.0``-``1.0``.

    Each question term is weighted by :func:`term_weight`, and the result is the weight the
    heading carries over the weight available.
    """
    if not heading:
        return 0.0
    ordered = sorted(terms)
    available = sum(term_weight(term) for term in ordered)
    if available <= 0:
        return 0.0
    heading_lower = heading.lower()
    carried = sum(
        term_weight(term) for term in ordered if _term_pattern(term).search(heading_lower)
    )
    return carried / available


def find_passages(text: str, question: str, *, limit: int = 3) -> list[str]:
    """The sections most likely to answer ``question``, best first.

    Matching works on *sections*, not loose paragraphs, and a section whose heading
    contains the question's terms outranks one that merely mentions them in passing. A
    rule is defined under its own heading ("Cover", "Grappled"), so the heading is the
    strongest available signal - and its absence is what let "Grappling Hook" in an
    equipment list and a travel-pace sentence about mounts beat the real rule.

    Returns an empty list when nothing qualifies. That is a real outcome, not a failure:
    the SRD is a subset of the 2024 rulebook (it has no subclasses and only a few feats,
    for instance), and the caller reports the gap rather than presenting an unrelated
    passage as the rule.
    """
    scored, terms, sections = _matched(text, question)
    return _format(_qualifies(scored, terms), limit=limit, sections=sections)


def _format(scored, *, limit: int = _PASSAGE_LIMIT, sections=None) -> list[str]:
    """Best sections rendered as passages, each prefixed with its heading.

    A matched rule is rendered *whole*. A run-in label promoted by :func:`_promote_groups`
    is a part of the rule its heading introduced, so when that rule is itself about the
    question the parts come back with it - including the ones that never matched on their
    own. A rule's opening sentence names its subject far more often than its later parts
    do, so ranking the parts independently returns a definition that stops before the
    procedure: "how does grappling work" without "Ending a Grapple", or a condition listed
    with effects missing and no sign that anything had been dropped.

    The expansion is conditional, and the condition is the whole of the safety. A part is
    folded into its heading only when that heading *also* answers the question
    (``qualifying``). Grouping on the parent link alone drowns the answer instead: the
    promoted parts of the stat block ("Bonus Actions") and of the wizard's Spellcasting
    feature ("Spellbook") have broad structural headings that match nothing in the
    question, so "what is a bonus action" would return the entire stat block and "what is
    a wizard's spellbook" the whole level 1 feature. When the heading is not about the
    question, the part *is* the rule and is rendered on its own.

    Regrouping happens before the limit is applied, so a rule with four parts occupies one
    of the slots rather than all of them. ``sections`` supplies the bodies of the parts
    that did not match; without it every section is rendered on its own.
    """
    ranked = sorted(scored, key=lambda item: (-item[0], item[1]))
    if sections is None:
        return [_passage(item[2], item[3]) for item in ranked[:limit]]

    qualifying = {item[1] for item in ranked}

    passages: list[str] = []
    emitted: set[int] = set()
    for item in ranked:
        if len(passages) >= limit:
            break
        # The rule this section belongs to: itself, unless it is a promoted part of a
        # heading that answers the question too. "-1" and any non-qualifying parent mean
        # the section is its own rule.
        parent = sections[item[1]][2]
        root = parent if parent in qualifying else item[1]
        if root in emitted:
            continue
        emitted.add(root)
        passages.append("\n\n".join(
            _passage(heading, body)
            for index, (heading, body, _parent) in enumerate(sections)
            if (index == root or (index != root and _parent == root)) and (body or heading)
        ))
    return passages


def _passage(heading: str, body: str) -> str:
    """One section rendered so it reads on its own, under its own heading."""
    return (f"## {heading}\n" if heading else "") + body


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_cached(question: str, cache_dir=None) -> dict | None:
    """A previously answered rules question, or None."""
    entry = _read(entry_path(question, cache_dir))
    if not entry or not entry.get("answer"):
        return None
    if entry.get("source") != RULES_SOURCE:
        # An answer from a different source is not usable. This is what retires the
        # answers produced from the previously-scraped website: they were written against
        # a source that omitted the Rules Glossary, so several of them report a rule as
        # missing that the vendored SRD defines. Served from cache they would outlive the
        # fix, which is exactly how a "we fixed that" regression happens.
        return None
    if entry.get("retrieval_version") != RETRIEVAL_VERSION:
        # The same argument applies to retrieval that changed but left the files alone.
        # The answer was written from passages this version no longer produces, so it
        # would keep answering a question the current retrieval answers better - with the
        # new passages reported alongside it, which is worse, because the citation then
        # contradicts the answer it is meant to support.
        return None
    return entry


def save_cached(question: str, answer: str, *, passages: list[str], url: str,
                answer_source: str = "rules", cache_dir=None) -> Path:
    """Store a rules answer with the source text it was grounded in. Never raises.

    ``answer_source`` records whether the answer was *quoted* from a rule the SRD defines
    under its own heading (``rules``) or *interpreted* from related text (``rules-inferred``).
    It is stored rather than recomputed because a cache hit skips retrieval entirely, so
    the distinction would otherwise be lost and an interpreted answer would be served as a
    quotation.
    """
    from datetime import datetime, timezone

    path = entry_path(question, cache_dir)
    entry = {
        "question": question.strip(),
        "normalised": normalise(question),
        "answer": answer,
        "passages": passages,
        "url": url,
        "source": RULES_SOURCE,
        "answer_source": answer_source,
        "retrieval_version": RETRIEVAL_VERSION,
        "answered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logging.warning(f"Could not cache the rules answer ({e}).")
    return path


def candidate_files(*, search_all: bool = True) -> list[Path]:
    """Every SRD file worth searching, preferred ones first.

    The ``search_all`` split is kept from the fetching version so the shape of
    :func:`gather` is unchanged, but it no longer saves anything: reading four local files
    costs milliseconds, where the crawl it used to skip cost dozens of HTTP round trips.
    """
    files = source_files()
    if search_all:
        return files
    preferred = set(PREFERRED_FILES)
    return [path for path in files if path.name in preferred]


def _reference(path) -> str:
    """Repo-relative path, used as the citation shown with an answer.

    Relative rather than absolute so a citation is stable across machines, and a path
    rather than a URL because the source genuinely is a file now - a URL would look
    clickable and lead nowhere.
    """
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(config.ROOT))
    except (ValueError, OSError):
        return str(candidate)


def gather(question: str, *, files=None, cache_dir=None, timeout: float = 20.0,
           search_all: bool = True) -> dict:
    """Retrieve the SRD passages for a question, and report any cached answer.

    Returns ``{"passages", "url", "text", "from_cache"}``. Raises ``RulesUnavailable``
    when nothing matches, so the caller can say so rather than answering from model recall
    and presenting it as sourced.

    ``from_cache`` reports whether a previous *answer* exists, not whether retrieval was
    skipped - retrieval always runs, because it is a local file read and caching it would
    mean an edited SRD file kept serving stale text. ``timeout`` is accepted and ignored,
    and ``files`` overrides discovery, so callers written against the fetching version
    keep working.
    """
    if (cached := load_cached(question, cache_dir)) is not None:
        return {
            "passages": cached.get("passages") or [],
            "url": cached.get("url", RULES_INDEX),
            "text": "\n\n".join(cached.get("passages") or []),
            "from_cache": True,
        }

    candidates = list(files) if files is not None else candidate_files(search_all=search_all)
    if not candidates:
        raise RulesUnavailable(
            f"No SRD text found at {srd_dir()}. The vendored rules are required for "
            "lookups; see context/srd/PROVENANCE.md."
        )

    # Every file is scored and the best *match* wins, on the matcher's own score - not on
    # how much text a file happens to contain, which is a different question entirely and
    # quietly chose the wrong answer.
    best = None
    for path in candidates:
        try:
            text = markdown_to_text(read_srd(path))
        except RulesUnavailable as e:
            logging.debug(f"Skipping {path}: {e}")
            continue
        scored, terms, sections = _matched(text, question)
        qualifying = _qualifies(scored, terms)
        if not qualifying:
            continue
        top = qualifying[0][0]
        if best is None or top > best[0]:
            best = (top, _reference(path), qualifying, sections)

    if best is None:
        raise RulesUnavailable(
            f"The 2024 SRD has no section matching '{question}'. The SRD covers the core "
            "rules, not every option in the Player's Handbook."
        )

    _score, used, scored, sections = best
    found = _format(scored, sections=sections)
    return {"passages": found, "url": used, "text": "\n\n".join(found),
            "from_cache": False}


# The floor for the inferred path. Lower than ``_MIN_SUBJECT_WEIGHT`` because the inferred
# path is not claiming the text *is* the rule, only that it bears on the question - so a
# subject that is merely a bit generic ("attack" at 0.64, which names the glossary's own
# "Spell Attack") is still worth interpreting, where the precise path refuses it.
_MIN_INFERRED_WEIGHT = 0.5


def gather_inferred(question: str, *, files=None, cache_dir=None) -> dict:
    """Best-effort passages for a question no heading names, for an interpreted answer.

    The precise path refuses a question the SRD does not define under its own heading, and
    that refusal is right for a *quoted* rule. It also refuses questions the SRD plainly
    discusses: "what is a spell attack" is answered by the glossary's own "Spell Attack"
    heading, but the question's most distinctive term is the generic "attack", which the
    precise path's subject floor rejects. This runs the same gates with a lower floor, so
    the model can answer from the text - and the caller labels the result
    ``rules-inferred``, because an answer assembled from surrounding text is not a
    quotation and must not wear a quotation's badge.

    Deliberately still heading-anchored, and still refusing a qualified heading. Loosening
    either one reintroduces a failure the precise path was built to stop: without the
    heading anchor "how does two weapon fighting work" is answered from "The Order of
    Combat" (the SRD has no two-weapon rule at all), and without the qualifier gate "how
    does a spear work" is answered from "Eldritch Spear". The only thing relaxed is the
    subject floor, which is what lets a generic-but-real subject like "attack" through.

    The gates themselves are :func:`_qualifies`' own, called with a lower floor rather
    than re-implemented, so the two paths cannot drift apart about what a rule is.
    """
    candidates = list(files) if files is not None else candidate_files(search_all=True)
    if not candidates:
        raise RulesUnavailable(
            f"No SRD text found at {srd_dir()}. The vendored rules are required for "
            "lookups; see context/srd/PROVENANCE.md."
        )

    best = None
    for path in candidates:
        try:
            text = markdown_to_text(read_srd(path))
        except RulesUnavailable as e:
            logging.debug(f"Skipping {path}: {e}")
            continue
        scored, terms, sections = _matched(text, question)
        qualifying = _qualifies(scored, terms, min_subject_weight=_MIN_INFERRED_WEIGHT)
        if not qualifying:
            continue
        if best is None or qualifying[0][0] > best[0][0][0]:
            best = (qualifying, path, sections)

    if best is None:
        raise RulesUnavailable(
            f"The 2024 SRD has no section matching '{question}'. The SRD covers the core "
            "rules, not every option in the Player's Handbook."
        )

    qualifying, path, sections = best
    found = _format(qualifying, sections=sections)
    return {"passages": found, "url": _reference(path), "text": "\n\n".join(found),
            "from_cache": False}


# --- spell descriptions --------------------------------------------------------
#
# ``spells.md`` carries 341 spell descriptions alongside the casting rules, so a spell can
# be shown from the same vendored corpus a rule is. This is a *direct* lookup, not a
# search: a spell is named exactly and appears once, so nothing needs ranking.

# The spell section of ``spells.md``. Before it are the general rules of spellcasting,
# which also use ``####`` headings ("Spell Slots", "Using a Higher-Level Spell Slot") and
# would otherwise be indexed as spells.
SPELLS_SECTION = "Spell Descriptions"

# A spell's class line: "_Level 3 Evocation (Sorcerer, Wizard)_". Its presence is what
# distinguishes a spell from the machinery interleaved among them - "Animated Object",
# "Actions" and "Traits" are ``####`` headings nested inside the spells that reference
# them, and they have no level line.
_SPELL_STATS = re.compile(r"^_Level (\d)[^_]*_\s*$", re.M)
_SPELL_STATS_CANTRIP = re.compile(r"^_([^_]*Cantrip[^_]*)_\s*$", re.M)


def _spells_markdown() -> str:
    """The ``spells.md`` text, or empty string when it has not been vendored."""
    path = srd_dir() / "spells.md"
    if not path.is_file():
        return ""
    try:
        return read_srd(path)
    except RulesUnavailable:
        return ""


def spell_names() -> list[str]:
    """Every spell in the vendored SRD, sorted.

    Excludes the non-spell headings that appear within the spell section, so a caller can
    offer these as a list without offering "Actions" as if it were a spell.
    """
    return sorted(_spells_index())


def linkable_spell_names() -> list[str]:
    """Every spell name the front end may link, as the union of both sources.

    The corpus is what the model picks from, but it is not the only thing it may *name*:
    the SRD carries 22 spells the corpus does not, and they are the 2024 generic renames
    of the 2014 branded ones - the SRD's "Hideous Laughter" against the corpus's "Tasha's
    Hideous Laughter", "Floating Disk" against "Tenser's Floating Disk". A model writing
    prose may use either name, so both must be linkable or the 2024 name renders as dead
    text. The reverse also holds: 200 corpus spells are not in the SRD at all.

    The SRD's spelling wins where the two disagree, because that is the name the lookup
    resolves to first and the one the card will show.
    """
    from . import spells as spells_module

    merged: dict[str, str] = {}
    for name in spells_module.corpus_spell_names():
        merged.setdefault(_fold_name(name), name)
    for name in _spells_index().values():
        merged[_fold_name(name[0])] = name[0]
    return sorted(merged.values())


def _fold_name(name: str) -> str:
    """A comparison key for a spell name: case- and apostrophe-insensitive.

    The two sources disagree on the apostrophe - the corpus writes "Tenser_s" and the SRD
    writes a typographic one - so folding both is what makes them the same spell.
    """
    return name.replace("\u2019", "'").lower()


def _spells_index() -> dict[str, tuple[str, str]]:
    """``{lowercased name: (name as written, body)}`` for the vendored SRD's spells.

    Keyed by lowercase so lookups can ignore case, but the name is kept as the SRD writes
    it because the card shows it. The body excludes the ``####`` heading: the caller
    already has the name, and keeping it here would print the spell's name twice.
    """
    markdown = _spells_markdown()
    if not markdown:
        return {}

    start = markdown.find(f"## {SPELLS_SECTION}")
    if start < 0:
        # The document's shape changed. Returning nothing is right: indexing the whole
        # file would offer the casting *rules* as spells.
        logging.warning(f"{SPELLS_SECTION!r} not found in spells.md; no spells indexed.")
        return {}

    index: dict[str, tuple[str, str]] = {}
    # Split on ####, keeping the heading with its body: ["lead", head1, body1, ...].
    parts = re.split(r"^#### (.+)$", markdown[start:], flags=re.MULTILINE)
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip()
        body = parts[i + 1].strip()
        if not _is_spell_body(body):
            continue
        # 13 spells - Augury, Confusion, Prismatic Spray and friends - carry their table
        # inline as HTML. The renderer has no table syntax, so it would print the markup.
        index[name.lower()] = (name, tables_to_text(body))
    return index


def _is_spell_body(body: str) -> bool:
    """Whether a ``####`` body is a spell description rather than nested machinery."""
    return bool(_SPELL_STATS.search(body) or _SPELL_STATS_CANTRIP.search(body))





def find_spell(name: str) -> dict | None:
    """One spell's description, from the SRD if it has it and the corpus if it does not.

    The SRD is preferred because it is the authority on the 2024 rules, and it is what the
    `/?` answers are quoted from. But it carries only 339 spells, and the corpus carries
    544: the difference is the supplements. Thorn Whip, Lightning Lure, Gust, Mold Earth
    and Mind Sliver are all absent from the SRD, and they are exactly the cantrips a Pact
    of the Tome Warlock leans on. Answering "not in the SRD" for a spell the app itself
    just recommended would make every link in the books useless, so the corpus fills the
    gap and the response says which source it came from.

    Matched case-insensitively and on the name as written, because the corpus and the SRD
    disagree about branding rather than spelling: the corpus carries "Tenser's Floating
    Disk" where the SRD has "Floating Disk". Those are genuinely different spells in the
    SRD's eyes - product identity was removed in 2024 - so the SRD is not searched for a
    renamed equivalent; the corpus entry is returned instead.
    """
    wanted = _fold_name(" ".join(str(name).split()).strip())
    if not wanted:
        return None

    found = _spells_index().get(wanted)
    if found is not None:
        name, body = found
        return {
            "name": name,
            "text": body,
            "url": _reference(srd_dir() / "spells.md"),
            "source": RULES_SOURCE,
        }

    return _corpus_spell(wanted)


def _corpus_spell(wanted: str) -> dict | None:
    """A spell read from the retrieval corpus, or None if the corpus has no such file."""
    from . import spells as spells_module

    path = _corpus_spell_paths().get(wanted)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return {
        # The same name the index is keyed on, so the card's heading matches the link
        # the reader followed to get here.
        "name": spells_module.spell_title(text) or spells_module.prettify_name(path.stem),
        "text": normalise_corpus_spell(text),
        "url": _reference(path),
        "source": CORPUS_SOURCE,
    }


# A markdown table row: `| Agonizing Blast | 2 | A damage-dealing cantrip | Yes |`.
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
# The `| --- | --- |` separator under a table's header row.
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _invocation_rows() -> dict[str, dict]:
    """Every Eldritch Invocation our class context lists, keyed by folded name.

    The 2024 SRD does not publish invocations - the vendored files have no invocation text
    at all - so this reads our own class context instead, and the response says so. The
    tables there are the authority on the invocation's minimum level and prerequisite,
    which is what a recommendation has to respect.

    A name appearing in more than one file keeps the first, because the base class file
    holds the full list and the pact files repeat the entries that relate to them.
    """
    found: dict[str, dict] = {}
    for relative in INVOCATION_FILES:
        path = config.CONTEXT_DIR_PATH / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for row in _invocation_table_rows(text):
            name = row["name"]
            found.setdefault(_fold_name(name), {**row, "url": _reference(path)})
    return found


def _invocation_table_rows(text: str) -> list[dict]:
    """Parse the invocation tables out of one context file.

    Only tables whose header names an invocation are read, so the progression and feature
    tables in the same file are not mistaken for invocations. The columns are located by
    header name rather than by position, because the pact files order them differently
    from the base class file.
    """
    rows: list[dict] = []
    header: list[str] | None = None

    for line in text.splitlines():
        if _TABLE_RULE.match(line):
            continue
        match = _TABLE_ROW.match(line)
        if not match:
            header = None
            continue

        cells = [c.strip() for c in match.group(1).split("|")]
        if header is None:
            lowered = [c.lower() for c in cells]
            if "invocation" in lowered:
                header = lowered
            continue

        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        name = row.get("invocation", "").strip()
        if not name or name.startswith("-"):
            continue
        rows.append(
            {
                "name": name,
                "level": _first_int(row.get("lv") or row.get("minimum level") or ""),
                "prereq": _dash_to_none(row.get("prereq", "")),
                "repeatable": row.get("repeatable", "").strip().lower() == "yes",
                "note": _dash_to_none(row.get("note", "")),
            }
        )
    return rows


def _first_int(text: str) -> int | None:
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else None


def _dash_to_none(text: str) -> str | None:
    """A table's "-" means "no value", not the literal string."""
    cleaned = (text or "").strip()
    return None if cleaned in ("", "-", "\u2014") else cleaned


@lru_cache(maxsize=1)
def _invocations_index() -> dict[str, tuple[str, str]]:
    """``{folded name: (name as written, body)}`` for the SRD's Eldritch Invocations.

    Read from the ``Eldritch Invocation Options`` section of the vendored class chapter,
    which is the only place the effect text lives. The section is located by heading
    because the file is 11,000 lines of class features and the invocation names are not
    distinguishable from any other ``####`` heading without it.

    The body excludes the ``####`` heading, because the card already shows the name.
    """
    path = srd_dir() / CLASSES_FILE
    if not path.is_file():
        return {}
    try:
        markdown = read_srd(path)
    except RulesUnavailable:
        return {}

    start = markdown.find(f"### {INVOCATION_SECTION}")
    if start < 0:
        # The document's shape changed. Returning nothing is right: indexing the whole
        # chapter would offer every class feature as an invocation.
        logging.warning(
            f"{INVOCATION_SECTION!r} not found in {CLASSES_FILE}; no invocations indexed."
        )
        return {}

    # The section runs to the next `###` heading, which is the Warlock spell list.
    rest = markdown[start:]
    following = re.search(r"\n### ", rest[4:])
    section = rest[: 4 + following.start()] if following else rest

    index: dict[str, tuple[str, str]] = {}
    parts = re.split(r"^#### (.+)$", section, flags=re.MULTILINE)
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip()
        body = parts[i + 1].strip()
        if body:
            index[_fold_name(name)] = (name, body)
    return index


def find_invocation(name: str) -> dict | None:
    """One Eldritch Invocation's rules, or None if neither source has such an entry.

    Invocations are not spells, so they are looked up separately rather than folded into
    :func:`find_spell` - a class feature answering as if it were an SRD spell would be a
    category error the caller could not see.

    The vendored SRD is preferred because it carries the invocation's *effect* text, which
    is what a reader actually wants to know. Our own class context is the fallback: it
    lists all 28 invocations with their level and prerequisite, but not what they do, so
    it can only answer "may I take this?" rather than "what does it do?". The response's
    ``source`` says which one answered, because the two are not equally authoritative.
    """
    wanted = _fold_name(" ".join(str(name).split()).strip())
    if not wanted:
        return None

    found = _invocations_index().get(wanted)
    if found is not None:
        name, body = found
        return {
            "name": name,
            "text": body,
            "url": _reference(srd_dir() / CLASSES_FILE),
            "source": RULES_SOURCE,
        }

    row = _invocation_rows().get(wanted)
    if row is None:
        return None
    return {
        "name": row["name"],
        "text": _invocation_text(row),
        "url": row["url"],
        "source": CLASS_SOURCE,
    }


def _invocation_text(row: dict) -> str:
    """Render an invocation row as the same shape a spell's text takes.

    The card renders one markdown subset for both, so an invocation is written as a stats
    line and a sentence rather than as a table - the renderer has no table syntax, and a
    raw pipe row would show as literal text.
    """
    parts = []
    if row["level"] is not None:
        parts.append(f"Minimum Warlock level {row['level']}")
    if row["prereq"]:
        parts.append(f"Prerequisite: {row['prereq']}")
    if row["repeatable"]:
        parts.append("Repeatable")
    lines = [f"_{' \u00b7 '.join(parts)}_"] if parts else []
    if row["note"]:
        lines.append(row["note"])
    return "\n\n".join(lines)


def invocation_names() -> list[str]:
    """Every invocation name our class context lists, sorted.

    Offered to the front end alongside the spell names so a mention in a book becomes a
    link. Invocations are named in the same prose as spells - "Agonizing Blast on Eldritch
    Blast" - and leaving them as dead text is the same defect as an unlinked spell.
    """
    return sorted(row["name"] for row in _invocation_rows().values())


# The corpus writes a spell's title as a markdown link to D&D Beyond, and its level,
# school and class list as hashtags: `# [Fireball](https://...)` then
# `#Level3 #Evocation ( #Sorcerer, #Wizard)`.
_CORPUS_TITLE = re.compile(r"^#\s*\[([^\]]+)\]\([^)]*\)\s*$", re.M)
# 133 of the corpus's 544 spells write the title as a bare heading instead of a link.
_CORPUS_PLAIN_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.M)
# The corpus links rules terms inline - `[Concentration](https://www.dndbeyond.com/...)` -
# where the SRD writes them as plain words. The renderer has no link syntax, so the URL
# would show as literal text.
_CORPUS_INLINE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
# 73 of the corpus's spells cross-reference another spell wiki-style, `[[Wall of Force]]`.
_CORPUS_WIKI_LINK = re.compile(r"\[\[([^\]]+)\]\]")
# A spell's stats line names a level or a cantrip; a magic item's names a rarity.
_CORPUS_LEVEL = re.compile(r"#(?:Level\d+|Cantrip)\b")
# Five of the corpus's spells indent the tags line by one space, and one (Sapping Sting)
# omits the class list entirely.
_CORPUS_TAGS = re.compile(
    r"^[ \t]*#(\w+)\s+#(\w+)\s*(?:\(\s*([^)]*)\))?\s*$", re.M
)
_CORPUS_CLASS = re.compile(r"#\s*([\w' ]+)")
# The corpus bolds its run-in labels as well as italicising them, and puts the full stop
# inside the emphasis: `**_Cantrip Upgrade._**`. The SRD writes `_Cantrip Upgrade._`, so
# the bold is dropped and the label left as the group already reads.
_CORPUS_RUN_IN = re.compile(r"\*\*_([^_]+)_\*\*")


def normalise_corpus_spell(text: str) -> str:
    """Rewrite a corpus spell into the SRD's shape, so one renderer handles both.

    The two sources describe the same thing in different dialects. The SRD writes a stats
    line as `_Level 3 Evocation (Sorcerer, Wizard)_`; the corpus writes a markdown link
    title and a line of hashtags. Left alone, the corpus text renders with its markup
    showing - a heading reading `[Thorn Whip](https://www.dndbeyond.com/...)` and a
    paragraph of `#Transmutation #Cantrip ( #Druid)`.

    Normalising here rather than teaching the renderer about both dialects keeps the
    front end with one format to understand, and keeps the corpus's quirks in the module
    that already knows about the corpus.

    Only presentation is touched. Every number, range and duration is left exactly as
    written, because those are what a recommendation is built on.
    """
    # The title line is dropped rather than kept: the caller renders the name as the
    # card's heading, and the SRD's body does not repeat it either. Both spellings of the
    # title are dropped, and the plain one is matched only at the very start so a `#`
    # heading further down (a spell's own sub-heading) is left alone.
    text = _CORPUS_TITLE.sub("", text)
    text = _CORPUS_PLAIN_TITLE.sub("", text, count=1)

    def stats(match: re.Match[str]) -> str:
        first, second, classes = match.group(1), match.group(2), match.group(3)
        # One of the two tags is the level ("Level3" or "Cantrip") and the other the
        # school; which comes first varies, so identify them rather than assume an order.
        level = first if first.lower().startswith("level") or first == "Cantrip" else second
        school = second if level is first else first
        names = ", ".join(_CORPUS_CLASS.findall(classes or ""))
        # The SRD puts the level first for a levelled spell but the school first for a
        # cantrip: "Level 3 Evocation", "Evocation Cantrip". Matching that keeps the two
        # sources reading identically.
        # A spell with no class list still reads as a stats line, just a shorter one.
        suffix = f" ({names})" if names else ""
        if level == "Cantrip":
            return f"_{school} Cantrip{suffix}_"
        return f"_{re.sub(r'^Level(\d+)$', r'Level \1', level)} {school}{suffix}_"

    # The SRD leaves a blank line between the stats line and the first stat; the corpus
    # does not. Matching it keeps the two sources rendering identically.
    text = _CORPUS_TAGS.sub(lambda m: stats(m) + "\n", text)
    text = _CORPUS_RUN_IN.sub(lambda m: f"_{m.group(1)}_", text)
    # Inline links keep their text and lose their target, which is what the SRD writes.
    # The wiki form is unwrapped first: its inner brackets would otherwise be left behind
    # by the markdown pattern, which matches the inner `[Wall of Force]` and not the outer.
    text = _CORPUS_WIKI_LINK.sub(lambda m: m.group(1), text)
    text = _CORPUS_INLINE_LINK.sub(lambda m: m.group(1), text)
    # The corpus separates a run-in label from its sentence with a non-breaking space; the
    # SRD uses a plain one. Left in, it survives into the rendered paragraph.
    text = text.replace("\xa0", " ")
    # Dropping the title leaves the blank line that followed it at the top.
    return text.strip()


@lru_cache(maxsize=1)
def _corpus_spell_paths() -> dict[str, Path]:
    """Corpus spell files keyed by folded name, built once.

    Keyed on the prettified name so a lookup matches the same spelling the front end links
    with, and so "Tenser_s Floating Disk" and "Tenser's Floating Disk" are one key.

    The corpus's `Spells/` directory also holds 22 magic items - Glamerweave, Armblade,
    Docent and friends - which are not spells and must not be offered as any. They are
    told apart by their stats line: a spell has a level or the word "Cantrip", an item has
    a rarity.
    """
    from . import spells as spells_module

    root = config.DOCS_DIR_PATH
    if not root.is_dir():
        return {}
    found: dict[str, Path] = {}
    for path in root.rglob("*.md"):
        try:
            head = path.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        if not _CORPUS_LEVEL.search(head):
            continue
        # The page's own title wins over the filename, which is wrong for six files.
        name = spells_module.spell_title(head) or spells_module.prettify_name(path.stem)
        if name:
            found.setdefault(_fold_name(name), path)
    return found
