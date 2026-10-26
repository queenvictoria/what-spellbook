"""Prompt assembly for the spell recommender.

Prompt **templates** live here; rule **content** lives in ``context/``. The builders
below decide which context files apply to a character and splice them, the character
sheet, the scenario and the retrieved spell pool into the final prompt text.

Nothing here talks to a model or a vector store, so it is all unit-testable.

Stage 1 is retrieval. The scenario is deliberately *not* used to build the search
query: what the character is allowed to prepare is a rules question, and the scenario
only matters once the candidate pool is already legal. The scenario is passed to the
model instead, which ranks an already-legal pool.

``character_sheet_prompt`` is the odd one out: it is the *ingest* prompt that turns a
D&D Beyond PDF export into ``data/characters/<name>.yaml``. It is kept here so the
sheet schema has exactly one definition, shared by the ingest prompt and the tests.
"""

from __future__ import annotations

from pathlib import Path

from . import config

# Rule files that always apply, regardless of class.
BASE_CONTEXT_FILES = ("spells.md",)

# Approximate token ceiling for a local Ollama model's context window. The context
# files alone are already ~17k characters, so this guard exists to warn before a
# large context/ directory silently overflows the window and yields an empty reply.
PROMPT_CHAR_BUDGET = 60000


def prompt_budget_warning(prompt: str) -> str | None:
    """Return a warning when a built prompt is likely to exceed the model window."""
    if len(prompt) <= PROMPT_CHAR_BUDGET:
        return None
    return (
        f"Prompt is {len(prompt)} characters (~{len(prompt) // 4} tokens), above the "
        f"~{PROMPT_CHAR_BUDGET} character budget. Context files and the spell pool both "
        "grow, so a local model may run out of context and return nothing. Consider a "
        "larger model or trimming context/."
    )

# Which class context files apply for a given class/pact/subclass combination.
# Files may contain "{cls}" so future classes drop in without code changes.
CLASS_CONTEXT_TEMPLATE = "classes/{cls}/base.md"
PACT_CONTEXT_TEMPLATE = "classes/{cls}/pact/{pact}.md"
SUBCLASS_CONTEXT_TEMPLATE = "classes/{cls}/subclass/{subclass}.md"


def _slug(value: str | None) -> str:
    """Normalise a character-sheet value into a context filename stem.

    "Celestial Patron" -> "celestial", "Pact of the Tome" -> "tome".
    """
    if not value:
        return ""
    text = str(value).strip().lower()
    text = text.replace("pact of the ", "").replace(" patron", "")
    text = text.replace("pact of ", "")
    return "_".join(text.split())


def context_files_for(character: dict) -> list[str]:
    """Return the context files that apply to a character, in load order.

    Missing files are simply skipped - a character with no subclass yet still gets
    the class-wide rules.
    """
    cls = _slug(character.get("Class") or character.get("class"))
    if not cls:
        return list(BASE_CONTEXT_FILES)

    wanted = list(BASE_CONTEXT_FILES)
    wanted.append(CLASS_CONTEXT_TEMPLATE.format(cls=cls))

    pact = _slug(character.get("Pact") or character.get("pact"))
    if pact:
        wanted.append(PACT_CONTEXT_TEMPLATE.format(cls=cls, pact=pact))

    subclass = _slug(character.get("Subclass") or character.get("subclass"))
    if subclass:
        wanted.append(SUBCLASS_CONTEXT_TEMPLATE.format(cls=cls, subclass=subclass))

    return wanted


def load_rule_context(character: dict, context_dir=None) -> str:
    """Read and concatenate the applicable context files.

    Returns an empty string when nothing is found, so a missing ``context/``
    directory degrades to "no rules supplied" rather than crashing the REPL.
    """
    root = Path(context_dir) if context_dir is not None else config.CONTEXT_DIR_PATH
    if not root.is_dir():
        return ""

    blocks = []
    for relative in context_files_for(character):
        path = root / relative
        if not path.is_file():
            continue
        blocks.append(f"<!-- {relative} -->\n{path.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(blocks)


def system_prompt() -> str:
    """The role and the non-negotiable constraints.

    The hard limits are stated here rather than left to the model to derive, because
    a slot-level miscount is the failure mode that matters most in play.
    """
    return (
        "You are an expert D&D 5.5e (2024) tactical optimizer advising a Warlock who is "
        "using Pact of the Tome to rewrite their Book of Shadows during a Short Rest.\n"
        "\n"
        "You will be given the applicable rules, the character sheet, a scenario, and a "
        "pool of spells already filtered for legality.\n"
        "\n"
        "Absolute constraints:\n"
        "- Treat the supplied spell pool as the ONLY legal source of picks. Never "
        "introduce a spell that is not in it.\n"
        "- Book of Shadows picks are 3 cantrips and 2 level 1 rituals. Never exceed those "
        "counts and never put a levelled non-ritual or a non-level-1 spell in the book.\n"
        "- The pool is split into labelled sections. Book picks may come ONLY from the "
        "cantrip and level 1 ritual sections. Spells in the 'can you cast' section are "
        "levelled spells and must never be listed as a book pick, however well they fit "
        "the scenario.\n"
        "- The rules context lists spells the character always has prepared (for example "
        "a patron's granted spells). Those are NOT book options either - they cannot be "
        "put in the book and must never appear in a book's pick list.\n"
        "- Never select a spell the character already has prepared.\n"
        "- Every Warlock spell slot is the same level. Do not describe slots as a "
        "per-level spread.\n"
        "- Obey the level gates in the invocations table; do not propose an invocation "
        "above the character's level.\n"
        "\n"
        "Be concrete and tactical. Prefer naming specific spells and specific combos over "
        "general advice."
    )


def _format_spell_pool(pool_text: str, spell_text: str = "") -> str:
    """Render the candidate list, optionally with full text for shortlisted spells."""
    if not pool_text.strip():
        return "(no spells matched the eligibility filter)"
    if spell_text.strip():
        return f"{pool_text}\n\n--- FULL TEXT FOR SHORTLISTED SPELLS ---\n\n{spell_text}"
    return pool_text


def _ordinal_word(number: int) -> str:
    """'1' -> 'one', for prose in the prompt."""
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
            6: "six", 7: "seven", 8: "eight", 9: "nine"}.get(number, str(number))


def full_prompt(
    *,
    character_text: str,
    rule_context: str,
    scenario: str,
    pool_text: str,
    spell_text: str = "",
    books: int = config.BOOK_COUNT,
) -> str:
    """Build the first-pass prompt that produces the book loadouts.

    The requested count is interpolated rather than hard-coded, so raising ``BOOKS``
    cannot leave the prompt still demanding three - which would produce three books and
    a run that looks broken.
    """
    count = max(1, int(books))
    word = _ordinal_word(count)
    labels = ", ".join(f'"Book {n}"' for n in range(1, count + 1))
    return f"""{system_prompt()}

=== RULES CONTEXT ===
{rule_context or "(no rule files found under context/) "}

=== CHARACTER SHEET ===
{character_text}

=== TACTICAL SCENARIO ===
{scenario}

=== LEGAL SPELL POOL ===
{_format_spell_pool(pool_text, spell_text)}

=== OUTPUT REQUIREMENTS ===
Produce EXACTLY {count} distinct Book of Shadows loadouts, labelled {labels}.

For each book:
1. A short tactical theme name.
2. Its 3 cantrips and 2 level 1 rituals, taken only from the legal pool above.
3. A "How to use" breakdown tying the picks to this scenario, naming the specific
   spells involved.

After the {word} books, add:
4. Which of the character's existing prepared spells and class features pair with each
   book, and any invocation the character should be using (only those already
   available at their level).
"""


def refine_prompt(
    *,
    question: str,
    previous_response: str,
    scenario: str,
    rule_context: str = "",
    pool_text: str = "",
) -> str:
    """Build the follow-up prompt for /ask.

    The legality constraints are restated so a follow-up cannot quietly introduce a
    spell that was never in the pool.
    """
    return f"""You are continuing as the D&D 5.5e (2024) tactical optimizer.

{system_prompt()}

=== RULES CONTEXT ===
{rule_context or "(no rule files found under context/)"}

=== ORIGINAL SCENARIO ===
{scenario}

=== YOUR PREVIOUS RECOMMENDATION ===
{previous_response}

=== LEGAL SPELL POOL ===
{pool_text or "(not re-supplied)"}

=== USER REQUEST ===
{question}

Adjust the recommendation or answer the question. Stay inside the legal pool and the
Book of Shadows pick counts. If the request cannot be satisfied legally, say so and
offer the closest legal alternative.
"""


# --- character sheet ingest (D&D Beyond PDF -> data/characters/<name>.yaml) ---

# The sheet keys the recommender actually reads, in the order they should appear.
# ``main._format_character`` renders these verbatim into the prompt, so the names are
# part of the contract with the model, not cosmetic.
CHARACTER_SHEET_KEYS = (
    "Name",
    "Player",
    "Species",
    "Background",
    "Alignment",
    "Class",
    "Subclass",
    "Pact",
    "Current Level",
    "Proficiency Bonus",
    "Ability Scores",
    "Saving Throws",
    "Skill Proficiencies",
    "Passive Scores",
    "Armor Class",
    "Hit Points",
    "Hit Dice",
    "Speed",
    "Senses",
    "Damage Resistances",
    "Languages",
    "Spellcasting Ability",
    "Spell Save DC",
    "Spell Attack Bonus",
    "Pact Slots",
    "Eldritch Invocations",
    "Feats",
    "Known/Prepared Base Spells",
    "Book of Shadows Cantrips",
    "Book of Shadows Rituals",
    "Always Prepared Spells",
    "Free Casts Per Long Rest",
    "Cantrips From Other Sources",
    "Signature Attacks",
    "Resource Pools",
    "Magic Items",
    "Notable Gear",
    "Party",
)


def character_sheet_prompt(pdf_text: str, *, name: str = "") -> str:
    """Build the prompt that converts a D&D Beyond export into a character sheet.

    ``pdf_text`` is the output of ``pdftotext -layout``. The layout flag matters: the
    export is multi-column, and without it the ability scores, the spell table and the
    feature blocks interleave into unusable text.

    The prompt is deliberately extraction-only. Anything the sheet does not state is
    left out rather than inferred, because a hallucinated spell on the sheet silently
    corrupts every later recommendation.
    """
    keys = "\n".join(f"- {key}" for key in CHARACTER_SHEET_KEYS)
    target = f"data/characters/{name}.yaml" if name else "data/characters/<name>.yaml"
    return f"""You are converting a D&D Beyond character sheet export into YAML for a
spell-recommendation tool. The input below is the raw text of the PDF, extracted with
`pdftotext -layout`, so column order is preserved but labels and values are often on
different lines.

=== RAW PDF TEXT ===
{pdf_text}

=== OUTPUT FORMAT ===
Return ONLY a YAML mapping. No prose, no code fences, no commentary. The result is
written verbatim to `{target}`.

Use exactly these keys, in this order, and omit any key the sheet does not state:
{keys}

=== EXTRACTION RULES ===
- Quote every value that starts with a digit, contains a colon, or contains a comma,
  so YAML does not reinterpret it. Ability modifiers such as "+3" must be quoted.
- Join related values into one quoted string rather than nesting: write
  `Ability Scores: "STR 8 (-1), DEX 14 (+2), ..."`, not a nested mapping.
- List-valued keys are comma-separated plain scalars, e.g.
  `Skill Proficiencies: Deception, History, Insight, Investigation`.
- Read the spell table by its section headers (`=== CANTRIPS ===`, `=== 1st LEVEL ===`,
  ...). The `PREP SPELL NAME` column is the spell; the `SOURCE` column decides which
  key it belongs to:
  - `Warlock` -> Known/Prepared Base Spells
  - `Eldritch Invocations` -> Book of Shadows Cantrips (cantrips) or
    Book of Shadows Rituals (level 1 spells tagged `[R]`)
  - `Celestial Spells (Always Prepared)` and `Fey Touched (Always Prepared)` ->
    Always Prepared Spells
  - `Arcane Omens`, `Aasimar`, `Light ******` -> Cantrips From Other Sources
  - A `1/LR` note in the NOTES column -> Free Casts Per Long Rest
- `Pact Slots` is a count and a level, never a per-level spread: a level 5 Warlock has
  `Two 3rd-level slots`.
- `Signature Attacks` should carry the attack bonus, damage dice and damage type for
  the character's main attacks, derived from the spell table and the weapons list.
- `Resource Pools` collects the limited-use class and species features with their
  recharge, e.g. `Healing Light: 6d6 pool per Long Rest, Bonus Action, 60 ft., up to 4
  dice at once`. Include the action cost and range where the sheet states them.
- `Party` lists the other player characters' classes if the sheet names them.

=== HARD CONSTRAINTS ===
- Never invent a spell, item, feat or feature that is not in the raw text. If a value
  is unreadable, omit the key instead of guessing.
- Do not carry over anything from a previous version of the sheet. The output replaces
  the file wholesale.
- Do not add keys that are not in the list above.
"""
