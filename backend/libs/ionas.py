"""An optional second 2024 rules source: the DnD Character Sheet Helper rulebook.

`context/srd/` is the 2024 authority and the only *required* rules text. This module reads
a **different** source - the JSON rulebook published with Ionas Politis's Obsidian plugin
"DnD Character Sheet Helper" (<https://github.com/IonasPolitis/DnD-Character-Sheet-Helper>,
GPL-3.0) - and the word "optional" is the whole design:

* It is read **in place**. Nothing is copied or vendored, so there is no second source of
  truth to drift and no licence obligation to satisfy for a checkout that does not have it.
* When the directory is missing, `available()` is False, `sections()` is empty and every
  caller degrades to the SRD. A machine without it loses nothing it had before.
* Every row carries the `ionas-politis` source tag, because a reader has to be able to tell
  this text from the SRD's. Where the two overlap it is largely the same 2024 text, but
  non-SRD *subclasses* (Celestial, Archfey, Great Old One; Abjurer, Diviner, Illusionist)
  exist only here, and its prose is a scan rather than a transcription.

**Why it is worth reading at all.** The 2024 SRD carries exactly one subclass per class -
for a Warlock, the Fiend Patron, and for a Wizard, the Evoker. Everything else a player
picks at level 3 is absent, so a question about a Celestial Warlock's Healing Light, or a
Diviner's Portent, has no answer in the SRD. That is a real gap and this is the only local
source that fills it.

**Quality.** The text is an OCR/transcription of the 2024 books, so it carries scan
artifacts the SRD does not: words broken across a hyphen (`protec-tion`), spaces inside a
word (`w ith`, `pro ficiency`, `F ireball`), a stray `O` where a zero belongs, and the odd
dropped character. `normalise` repairs them against a dictionary built from the vendored
SRD - the authority on how these words are actually spelled - so a repaired word is one the
2024 rulebook writes. Text that cannot be repaired confidently is left alone: a near-miss
is worth more than a confident wrong word, which is the same judgement the rules matcher
makes about a plausible-looking paragraph.

**Shape.** Each JSON file is read according to the object it holds, and the shapes are
genuinely different - this is a plugin's data files, not a published schema:

======================================  ==================================================
``classes/<cls>.json``                  ``{class, spellcasting, features:{level:[...]}}``
``classes/<cls>-subclasses.json``       ``{Subclass Name: {level: [{name, description}]}}``
``classes/classChoices/*.json``         either ``{name, description, badge}`` per option, or
                                        a ``{slug: "Display Name"}`` router
``feats|items|races|rules|backgrounds`` one object per file, filed under ``description`` or
                                        a list of named sub-entries
``spells/<name>.json``                  ``{name, level, school, ...}``, or a per-class list
======================================  ==================================================

One consequence worth stating, because it looks like a bug and is not: **a class feature is
emitted once per name, not once per level.** ``Eldritch Invocations`` is listed at twenty
levels in ``warlock.json``; it is one rule, and the levels it is granted at are recorded
rather than repeated into twenty identical sections.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import config, rules

# The tag every row from this source carries. Shown in the UI, and the value a Chroma
# ``doc_type`` filter selects on, so it must not collide with the SRD's or the corpus's.
SOURCE = "ionas-politis"

# Where each kind of rule lives inside the source, and what to call it. The label is the
# "document" a section belongs to, in the same sense an SRD section belongs to a file.
CLASSES = "classes"
SUBCLASS_SUFFIX = "-subclasses"
CLASS_CHOICES = "classChoices"

# File stems that hold a *router* (a `slug -> Display Name` map) or a per-class spell list
# rather than rules text. They are navigation, not content: their headings would be a bare
# spell name with no text under it, which reads as a broken section.
_ROUTERS = ("classes.json", "items.json", "races.json", "rules.json", "backgrounds.json",
            "general-feats.json", "epic-boon-feats.json")
_SPELL_LISTS = re.compile(r"^[a-z-]+-spells\.json$")

# A heading in a description that is not a heading of its own: the source embeds
# `#### Fiend Spells` inside the Fiend Spells feature's prose, so the table under it would
# otherwise arrive as bare markup.
_EMBEDDED_HEADING = re.compile(r"^#{2,6}\s+", re.M)

# The OCR repair tables.
#
# Two mechanisms, deliberately. The *words* are repaired by rule against a dictionary of
# the vendored SRD, because that is what the 2024 rulebook actually writes and a rule needs
# no maintenance as the source is re-read. The *spaces* are repaired from a table, because
# the automatic test for a glued word ("neither half is a word on its own") is true of real
# English too - "a rea", "a side" and "a ward" all join to a word while "a Long Rest" must
# not - so the ambiguous fragments are listed by hand rather than guessed.
_DICTIONARY_FILES = "*.md"

# Words broken by a hyphen at a line or column wrap. A space would otherwise be reinserted
# by the reflow above, which is the opposite of the truth: `protec-tion` is one word.
_HYPHEN_BREAKS = (
    "Alterna-tively", "Bludgeon-ing", "Dis-advantage", "Hal-berds", "Qua-sit",
    "Vul-nerabilities", "Whis-pers", "ar-mor", "ben-efit", "crea-tures", "ef-fect",
    "ef-forts", "exam-ple", "perfor-mance", "pos-sible", "pre-pared", "protec-tion",
)

# Words separated by a space that belongs to neither half. Only the fragments that a
# dictionary rule cannot safely resolve are listed; the rest are joined automatically by
# `_join_glued`. Each entry was read in its own sentence before being added, because
# several of these joins produce a word ("a ward" -> "award", "s and" -> "sand") and the
# sentence is the only thing that says which was meant.
_GLUED_WORDS = (
    "a lso", "a rea", "a side", "a nd",
    "Ar tisan", "F ireball", "Inca pacitated", "Meta magic", "Radi ance", "Star ting",
    "da mage", "figh ting", "fin ish", "fini sh", "handwrit ing", "h ave", "ha ve",
    "m inutes", "res tore", "s pell", "ta rget", "w ith", "wi th", "yo ur",
    "w ithout", "th at", "a ffect", "a llow",
)

# A stray capital O where a zero belongs: "reduce an enemy to O Hit Points". Restricted to
# the phrases a zero is actually written in, so the letter O in ordinary prose is untouched.
_OCR_ZERO = re.compile(r"(?<=\b)O(?= (?:Hit Points|HP\b))")

# Digits and periods left over from a page number or footnote that the scan swallowed:
# "within 5 fe et of yo1 .1" - the "1 .1" is a stray page marker inside the clause.
_STRAY_PAGE = re.compile(r"\s+y?o?\d\s*\.\s*\d+(?=[\s.,;)]|$)")

# The character the source uses for a non-breaking space and the soft hyphen a scan
# sometimes leaves behind.
_ODD_SPACE = re.compile(r"[\u00a0\u200b\u00ad]")

# An unfilled template. Two feats ship as `<Feat_Name>` / `<Feat_Description>`, which is a
# placeholder rather than a rule - offering it as one would put a fill-in-the-blank in the
# rulebook.
_PLACEHOLDER = re.compile(r"^\s*<.*>\s*$")

_WHITESPACE = re.compile(r"\s+")


class IonasUnavailable(RuntimeError):
    """Raised only when a caller demands the source and it is not there.

    Nothing in the app raises this: the source is optional by contract, so a missing
    directory is an empty result rather than an error. It exists for a caller that has
    explicitly asked for this text - a test, or a future "import the rulebook" command.
    """


@dataclass(frozen=True)
class Section:
    """One rule from this source, ready to index or render.

    Shaped like ``srd.Section`` in the fields a caller reads (``name``, ``title``, ``slug``,
    ``path``, ``text``) but deliberately not the same class: an SRD section is quoted from
    the 2024 rulebook, and this is a scan of it. Keeping them separate types is what stops
    one being served as the other.
    """

    name: str
    title: str
    slug: str
    path: str
    text: str
    # The kind of rule, e.g. "class", "subclass", "invocation". Shown as a badge, and the
    # reason a reader can tell an invocation from a spell at a glance.
    kind: str = "rule"
    # The index's ``level`` field. 0 is a placeholder, exactly as an SRD row uses it: this
    # is not a spell, and a spell-level filter must not classify it as a cantrip.
    level: int = 0
    # Every level the rule is granted at, for a class feature repeated across levels.
    levels: tuple[int, ...] = ()


def directory(override=None) -> Path:
    """Absolute path to the source rulebook, whether or not it exists.

    The default lives in ``config`` rather than here so there is one place to change where
    the source is looked for - and so a test can point it at a fixture without reaching into
    this module. It goes through ``config.resolve`` because a bare relative path resolves
    against the process CWD, which once made the cache and the rules context silently read a
    different directory depending on where the CLI was launched.
    """
    return config.resolve(override or config.IONAS_DIR)


def available(override=None) -> bool:
    """Whether this source is present, without reading any of it.

    A single ``is_dir`` call, so a caller can cheaply decide whether to offer it. The
    directory is the whole test: a partially-copied checkout holds fewer files, not broken
    ones, because every reader here tolerates a missing file.
    """
    return directory(override).is_dir()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "rule"


# --- OCR repair ---------------------------------------------------------------


@lru_cache(maxsize=1)
def _dictionary() -> frozenset[str]:
    """Every word the vendored SRD writes, lowercased.

    The 2024 authority on how a word is spelled, so a repair that produces a member of this
    set has produced a word the rulebook really uses. Built from the SRD rather than a system
    dictionary because the vocabulary is specific ("Bludgeoning", "Incapacitated", "Quasit")
    and a general dictionary would not contain the words most likely to be broken.
    """
    words: set[str] = set()
    for path in rules.srd_dir().glob(_DICTIONARY_FILES):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - an unreadable vendored file is not fatal
            continue
        words.update(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z']+", text))
    return frozenset(words)


def _join_hyphens(text: str) -> str:
    """Rejoin words the scan broke across a hyphen.

    Applied before the space repair, and only for the known breaks, because a hyphen is a
    legitimate character - "Cube-shaped", "ability-score" and every spell slug in the source
    must survive. A rule that joined any ``\\w+-\\w+`` would rewrite the source's own file
    names and hyphenated compounds.
    """
    for broken in _HYPHEN_BREAKS:
        text = text.replace(broken, broken.replace("-", ""))
    return text


def _join_glued(text: str) -> str:
    """Rejoin a word the scan split with a space that belongs to neither half.

    Three passes, narrowest first:

    1. The explicit table, for fragments no rule can disambiguate.
    2. A short fragment glued to a longer remainder, when the join is a word the SRD writes
       and *neither* half is ("F ireball", "Ar tisan", "Inca pacitated"). Requiring both
       halves to be non-words is what keeps real prose out: "a Long Rest" joins to "along",
       but "a" is a word, so it is left alone.
    3. A fragment ending a word at a line wrap, the mirror of (2) ("fin ish", "figh ting").
    """
    for glued in _GLUED_WORDS:
        text = text.replace(glued, glued.replace(" ", ""))

    vocabulary = _dictionary()

    def short_fragment(match: re.Match[str]) -> str:
        head, tail = match.group(1), match.group(2)
        joined = head + tail
        if joined.lower() not in vocabulary:
            return match.group(0)
        if head.lower() in vocabulary or tail.lower() in vocabulary:
            return match.group(0)
        return joined

    text = re.sub(r"(?<![A-Za-z'])([A-Za-z]{1,4}) ([A-Za-z]{2,})(?![A-Za-z])",
                  short_fragment, text)
    return re.sub(r"(?<![A-Za-z'])([A-Za-z]{2,}) ([A-Za-z]{1,3})(?![A-Za-z])",
                  short_fragment, text)


def _reflow(markdown: str) -> str:
    """Rejoin lines that a fixed-width scan wrapped mid-sentence.

    The source encodes a paragraph break as a newline and a wrapped line as a newline too,
    so the distinction has to be made from the text: a line that starts lowercase or with a
    comma continues the line above, and a line that starts a capital, a bullet, a table row
    or markup begins a new one.
    """
    out: list[str] = []
    for raw in markdown.split("\n"):
        line = raw.strip()
        if not line:
            out.append("")
            continue
        if (out and out[-1] and not out[-1].startswith(("|", "#", "-", "*", ">", "•"))
                and (line[0].islower() or line[0] in ",;)")):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return "\n".join(out)


def normalise(text) -> str:
    """Repair the scan's artifacts in one piece of the source's prose.

    Idempotent, so it is safe on text that was already repaired - which matters because a
    section's heading is normalised for display *and* its body is normalised before the two
    are joined.
    """
    result = str(text or "").replace("\r\n", "\n")
    result = _ODD_SPACE.sub(" ", result)
    result = result.replace("\t", "\n")
    result = _join_hyphens(result)
    result = _join_glued(result)
    result = _OCR_ZERO.sub("0", result)
    result = _STRAY_PAGE.sub("", result)
    # The source embeds a heading inside the prose it heads ("#### Fiend Spells" inside the
    # Fiend Spells feature), which would render as markup rather than as a title.
    result = _EMBEDDED_HEADING.sub("", result)
    return _WHITESPACE.sub(" ", result).strip() if "\n" not in result else _tidy(result)


def _tidy(markdown: str) -> str:
    """Collapse runs of blank lines, and trailing space, without flattening the layout."""
    lines = [line.rstrip() for line in _reflow(markdown).split("\n")]
    out: list[str] = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


# --- reading the source -------------------------------------------------------


def _read(path: Path):
    """Parse one JSON file, or None when it is absent or malformed.

    A malformed file is logged and skipped rather than raised: the source is third-party
    data, one bad file must not cost the reader every other rule, and the alternative -
    failing the whole index build - would let a source this project calls optional break
    the app outright.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logging.warning(f"Skipping unreadable rulebook file {path}: {e}")
        return None


def _reference(path: Path) -> str:
    """The repo-relative path a section cites, so a reader can find the file themselves."""
    try:
        return str(path.relative_to(config.ROOT))
    except ValueError:  # pragma: no cover - only when the source sits outside the repo
        return str(path)


def _section(*, name: str, title: str, text: str, kind: str, path: Path | None = None,
             levels=(), prefix: str = "", level: int = 0) -> Section | None:
    """Build a section, or None when it carries no text to show.

    A section with a name and no body is a navigation entry - the router files are full of
    them - and indexing one would put a bare spell name in the rulebook with nothing under
    it. Dropped here rather than filtered by every caller.
    """
    body = normalise(text)
    if not body:
        return None
    heading = normalise(name) or title
    if _PLACEHOLDER.match(heading) or _PLACEHOLDER.match(body):
        return None
    # The source embeds a heading inside the prose it heads, and the strip above turns it
    # into a plain line. A body line that repeats the section's own name says nothing, so it
    # is dropped - exact match only, so prose that merely mentions the name survives.
    body = "\n".join(
        line for line in body.split("\n") if line.strip().casefold() != heading.casefold()
    ).strip()
    if not body:
        return None
    slug = _slugify(f"{prefix} {heading}".strip())
    return Section(
        name=heading,
        title=normalise(title),
        slug=slug,
        path=_reference(path) if path else SOURCE,
        text=f"### {heading}\n\n{body}",
        kind=kind,
        level=level,
        levels=tuple(sorted(int(lv) for lv in levels if str(lv).isdigit())),
    )


def _class_sections(data: dict, path: Path) -> list[Section]:
    """One section per class feature, plus the spellcasting progression as a table.

    Features are grouped by name and their levels collected, because the source repeats a
    feature at every level it scales at - ``Eldritch Invocations`` appears twenty times with
    an identical description. Emitting twenty copies would fill the rulebook with duplicates
    and give a search twenty equal hits for one rule.
    """
    label = str(data.get("class") or path.stem.replace("-", " ").title()).strip()
    found: list[Section] = []

    features: dict[str, dict] = {}
    for level, entries in (data.get("features") or {}).items():
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            slot = features.setdefault(name, {"levels": [], "description": ""})
            slot["levels"].append(level)
            if entry.get("description"):
                slot["description"] = entry["description"]

    for name, slot in features.items():
        section = _section(
            name=name, title=f"{label} - {name}", text=slot["description"],
            kind="class feature", path=path, levels=slot["levels"], prefix=label,
        )
        if section is not None:
            found.append(section)

    progression = _spellcasting_table(data.get("spellcasting"), label)
    if progression:
        found.append(progression)
    return found


def _spellcasting_table(spellcasting, label: str) -> Section | None:
    """The class's per-level cantrip/prepared/slot progression, as a Markdown table.

    Rendered rather than left as the source's nested object because a reader asking "how
    many slots does a level 5 Warlock have" wants the row, and the numbers are the rule -
    the same reasoning that keeps the SRD's HTML tables as tables.
    """
    if not isinstance(spellcasting, dict) or not spellcasting:
        return None

    lines = [
        f"| Level | Cantrips | Prepared Spells | Spell Slots | Slot Level |",
        "| --- | --- | --- | --- | --- |",
    ]
    for level, entry in sorted(spellcasting.items(), key=lambda kv: int(kv[0])):
        if not isinstance(entry, dict):
            continue
        slots = [int(n) for n in entry.get("slots") or [] if isinstance(n, int)]
        total = sum(slots)
        # Every Pact Magic slot is the same level, which is the source's own encoding: the
        # slot count sits at the index of the level it is cast at.
        slot_level = (slots.index(max(slots)) + 1) if slots and max(slots) else 0
        lines.append(
            f"| {level} | {entry.get('cantrips', '')} | {entry.get('preparedSpells', '')} "
            f"| {total} | {slot_level} |"
        )

    return _section(
        name="Spellcasting progression",
        title=f"{label} - spellcasting progression",
        text="\n".join(lines),
        kind="class",
        prefix=label,
    )


def _subclass_sections(data: dict, path: Path) -> list[Section]:
    """One section per subclass feature. The file is keyed by subclass name, then level."""
    if not isinstance(data, dict):
        return []
    found: list[Section] = []
    for subclass, levels in data.items():
        if not isinstance(levels, dict):
            continue
        for level, entries in levels.items():
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                section = _section(
                    name=str(entry.get("name") or ""),
                    title=f"{subclass} - {entry.get('name', '')}",
                    text=entry.get("description"),
                    kind="subclass feature",
                    path=path,
                    levels=(level,),
                    prefix=subclass,
                )
                if section is not None:
                    found.append(section)
    return found


def _choice_sections(data, path: Path) -> list[Section]:
    """One section per class choice: an invocation, a fighting style, a metamagic option.

    Two shapes arrive here and both are real. A single option is ``{name, description,
    badge}``; the invocation *router* is ``{slug: "Display Name"}`` with no text at all, and
    contributes nothing because there is nothing to read.
    """
    if not isinstance(data, dict) or "name" not in data:
        return []
    section = _section(
        name=str(data.get("name") or ""),
        title=str(data.get("name") or ""),
        text=data.get("description"),
        kind=str(data.get("badge") or "class choice").lower(),
        path=path,
    )
    return [section] if section is not None else []


def _feat_sections(data: dict, path: Path) -> list[Section]:
    """One section per feat, whichever of the two shapes the file uses."""
    if not isinstance(data, dict) or not data.get("name"):
        return []
    text = data.get("description") or ""
    category = data.get("category")
    section = _section(
        name=str(data["name"]),
        title=f"{data['name']} (feat)",
        text=f"{text}\n\n_Category: {category}_" if category else text,
        kind="feat",
        path=path,
    )
    return [section] if section is not None else []


def _race_sections(data: dict, path: Path) -> list[Section]:
    """One section per species trait. The file holds a list of ``{name, description}``."""
    race = path.stem.replace("-", " ").title()
    found: list[Section] = []
    for trait in data.get("traits") or []:
        if not isinstance(trait, dict):
            continue
        section = _section(
            name=str(trait.get("name") or ""),
            title=f"{race} - {trait.get('name', '')}",
            text=trait.get("description"),
            kind="species trait",
            path=path,
            prefix=race,
        )
        if section is not None:
            found.append(section)
    return found


def _item_sections(data: dict, path: Path) -> list[Section]:
    """One section per item, with its mechanical fields written as stats.

    The fields are folded into the text rather than dropped because they *are* the item's
    rule - a battleaxe's ``1d8 Slashing`` is the answer to "what does a battleaxe do" - and
    the same reasoning that keeps the SRD's tables as tables applies here.
    """
    if not isinstance(data, dict) or not data.get("name"):
        return []
    stats = [
        f"{label}: {data[key]}"
        for key, label in (("type", "Type"), ("damage", "Damage"), ("ac", "AC"),
                           ("weight", "Weight"), ("cost", "Cost"))
        if data.get(key) not in (None, "")
    ]
    text = data.get("description") or ""
    section = _section(
        name=str(data["name"]),
        title=f"{data['name']} (item)",
        text=f"{text}\n\n{'; '.join(stats)}" if stats else text,
        kind="item",
        path=path,
    )
    return [section] if section is not None else []


def _rule_sections(data: dict, path: Path) -> list[Section]:
    """One section per entry in a rules file, which nests its entries under ``rules``."""
    found: list[Section] = []
    title = str(data.get("name") or path.stem.replace("-", " ").title())
    for entry in data.get("rules") or []:
        if not isinstance(entry, dict):
            continue
        section = _section(
            name=str(entry.get("name") or ""),
            title=f"{title} - {entry.get('name', '')}",
            text=entry.get("description"),
            kind=str(entry.get("badge") or "optional rule").lower(),
            path=path,
            prefix=title,
        )
        if section is not None:
            found.append(section)
    return found


def _spell_sections(data: dict, path: Path) -> list[Section]:
    """One section per spell, in the same shape a spell's stat line takes in the SRD."""
    if not isinstance(data, dict) or not data.get("name"):
        return []
    components = ", ".join(data.get("components") or [])
    stats = [
        f"{label}: {data[key]}"
        for key, label in (
            ("level", "Level"), ("school", "School"), ("castingTime", "Casting Time"),
            ("range", "Range"), ("duration", "Duration"), ("classes", "Classes"),
        )
        if data.get(key) not in (None, "")
    ]
    if components:
        stats.append(f"Components: {components}")
    if data.get("ritual"):
        stats.append("Ritual: yes")
    if data.get("concentration"):
        stats.append("Concentration: yes")
    level = data.get("level") if isinstance(data.get("level"), int) else 0
    section = _section(
        name=str(data["name"]),
        title=f"{data['name']} (spell)",
        text=f"{'; '.join(stats)}\n\n{data.get('description') or ''}",
        kind="spell",
        path=path,
        level=level,
    )
    return [section] if section is not None else []


def _sections_for(path: Path) -> list[Section]:
    """Every section one source file contributes, chosen by where the file lives.

    Dispatch is by directory and filename rather than by sniffing the JSON, because the
    shapes overlap: a class choice, a feat and an item are all ``{name, description}`` and
    would be indistinguishable without knowing which folder they came from.
    """
    if _SPELL_LISTS.match(path.name) or path.name in _ROUTERS:
        return []
    data = _read(path)
    if data is None:
        return []

    parent = path.parent.name
    if parent == CLASS_CHOICES:
        return _choice_sections(data, path)
    if parent in (CLASSES,):
        if path.stem.endswith(SUBCLASS_SUFFIX):
            return _subclass_sections(data, path)
        return _class_sections(data, path)
    if parent == "spells":
        return _spell_sections(data, path)
    if parent == "feats":
        return _feat_sections(data, path)
    if parent == "items":
        return _item_sections(data, path)
    if parent == "races":
        return _race_sections(data, path)
    if parent == "rules":
        return _rule_sections(data, path)
    return []


def _files(root) -> list[Path]:
    """Every readable JSON file under the source, in a stable order."""
    directory_path = Path(root)
    if not directory_path.is_dir():
        return []
    # ``#past-versions`` is a previous edition's rulebook. This project is 2024-only, so it
    # is excluded for the same reason a 2014 website is refused: a mixed corpus is worse
    # than either edition alone, because nothing in the text says which one it is.
    return sorted(
        path for path in directory_path.rglob("*.json")
        if "#past-versions" not in path.parts
    )


@lru_cache(maxsize=4)
def _cached_sections(resolved: str) -> tuple[Section, ...]:
    # Keyed on the *resolved* directory, not on the caller's argument. Keying on the
    # argument would miss a different ``config.IONAS_DIR`` entirely - the argument is usually
    # None - and serve one directory's rules while the config points at another. That is the
    # silent-staleness class of bug this project has already paid for once, with
    # monkeypatched paths that kept passing while testing nothing.
    root = Path(resolved)
    found: list[Section] = []
    seen: set[tuple[str, str, str]] = set()
    for path in _files(root):
        for section in _sections_for(path):
            # The source duplicates a handful of files: eight spells appear under two names
            # with byte-identical content ("Seeming" in both `seeming.json` and
            # `sending.json`), because one file is a stray copy. Indexing both would give a
            # search two equal hits for one rule and inflate the rulebook's count. Keyed on
            # the content as well as the name, so a genuine near-duplicate - the ten
            # Dragonborn ancestry options, five of them distinct - survives.
            key = (section.kind, section.title, section.text)
            if key in seen:
                continue
            seen.add(key)
            found.append(section)
    return tuple(found)


def sections(override=None) -> list[Section]:
    """Every rule this source contributes, or an empty list when it is not installed.

    Cached, because a search and an index build both ask and the source is 3.6 MB across
    ~600 files. ``clear_cache`` exists because the files are on disk and editable.
    """
    return list(_cached_sections(str(directory(override))))


def clear_cache() -> None:
    """Drop the parsed sections and the derived dictionary, so an edit is picked up."""
    _cached_sections.cache_clear()
    _dictionary.cache_clear()


def files(override=None) -> list[dict]:
    """The source as a table of contents: one entry per file, with what it holds.

    The browsing counterpart to ``sections``, and the same split as the SRD's: a client
    needs to know what exists and what it is called before fetching any text. A source that
    is not installed returns an empty list rather than raising, because "you do not have
    this" is a normal answer for something optional.
    """
    found = []
    for path in _files(directory(override)):
        if _SPELL_LISTS.match(path.name) or path.name in _ROUTERS:
            continue
        entries = _sections_for(path)
        if not entries:
            continue
        found.append({
            "name": path.stem,
            "title": normalise(entries[0].title),
            "path": _reference(path),
            "kind": entries[0].kind,
            "sections": len(entries),
        })
    return found


def lookup(name: str, override=None) -> dict | None:
    """One rule by name, case-insensitively, or None.

    The same shape ``rules.find_spell`` and ``rules.find_invocation`` return, so a caller
    can offer this as one more place a name might resolve without a second code path. First
    match wins, and the order is the file order - a subclass feature named the same as a
    class feature resolves to the class feature, which is the more general rule.
    """
    wanted = _fold(name)
    if not wanted:
        return None
    for section in sections(override):
        if _fold(section.name) == wanted:
            return {
                "name": section.name,
                "title": section.title,
                "text": section.text,
                "path": section.path,
                "slug": section.slug,
                "kind": section.kind,
                "source": SOURCE,
            }
    return None


def names(override=None) -> list[str]:
    """Every rule name this source carries, sorted and de-duplicated."""
    return sorted({section.name for section in sections(override)})


def _fold(name: str) -> str:
    """Normalise a name for matching: apostrophes to ASCII, whitespace collapsed.

    Whitespace is collapsed but *not* removed - "Detect Magic" must not become
    "DetectMagic" - which is a bug this project has already paid for once, in the book-pick
    guard.
    """
    text = str(name or "").replace("\u2019", "'").replace("\u2018", "'").strip().lower()
    return " ".join(text.split())
