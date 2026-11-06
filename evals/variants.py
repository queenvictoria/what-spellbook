"""The prompt variants the eval compares.

A prompt is an argument, and this file is how it gets made: each variant changes *one* thing
about what the model is told, so a change in the score can be attributed. A variant that
changed three things would produce a number that moves and an explanation that does not.

The app's own prompts are the variant named ``required``, which is exactly what
`backend.libs.prompts` produces. Everything else exists only to be measured - nothing here is
imported by `backend/`.

`Blocks` is what makes this an eval of the *context* as much as of the wording. The question
this project actually had was "should the linked documents be in the prompt, and should the
book's paragraph be?" - and the only honest way to answer it is to score the combinations
rather than argue about them. Every block is therefore physically removed from the prompt
when it is switched off: a variant that *says* it omits a block but still emits it would
produce numbers that look like evidence and are not.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.libs import prompts


@dataclass(frozen=True)
class Blocks:
    """Which context blocks a variant is allowed to use."""

    retrieved: bool = True
    attachments: bool = True
    character: bool = True
    # The book's own paragraph, supplied as the selection's context.
    selection: bool = True


# Every variant carries this, so it is not a variable. A prompt that dropped it might score
# better on a case like "Rust Metal" - by answering from 2014 memory - while being worse for
# the project, which is precisely why it is held constant.
_EDITION_RULE = (
    "The 2014 rules differ in ways that matter (invocation counts, whether Pact of the Tome "
    "costs an invocation). Do not fill a gap from memory or from the earlier edition."
)


@dataclass(frozen=True)
class Variant:
    name: str
    # A callable matching `prompts.rules_inferred_prompt`'s keyword signature.
    build: object
    blocks: Blocks
    why: str = ""


def _assemble(
    *,
    heading: str,
    body: str,
    rules: tuple[str, ...],
    blocks: Blocks,
    question: str,
    rule_text: str,
    rule_context: str,
    selection_context: str,
    attachments,
) -> str:
    """Assemble a prompt from the blocks this variant allows.

    Each block is emitted only when its switch is on, which is what makes the switches mean
    something. The order is the app's own order - retrieved text, then the named documents,
    then the character, then the book's paragraph, then the question - because reordering
    would be a second variable hiding inside the first.
    """
    parts = [heading, body]

    if blocks.retrieved:
        parts.append(f"=== RETRIEVED 2024 SRD TEXT ===\n{rule_text}")
    elif block := prompts._attachments_block(attachments):
        # Retrieval off but documents on: the documents are still the evidence, so they keep
        # their heading and the rules below can refer to "the attached documents".
        parts.append(block.rstrip("\n"))
    if blocks.attachments:
        parts.append(prompts._attachments_block(attachments).rstrip("\n"))
    if blocks.character:
        parts.append(
            "=== CHARACTER CONTEXT ===\n"
            f"{rule_context or '(no character context loaded)'}"
        )
    if blocks.selection:
        parts.append(prompts._selection_block(selection_context).rstrip("\n"))

    parts.append(f"=== QUESTION ===\n{question}")
    parts.extend(f"- {rule}" for rule in rules)
    return "\n\n".join(part for part in parts if part) + "\n"


def _variant(*, heading: str, body: str, rules: tuple[str, ...], blocks: Blocks):
    """One variant, assembled from the blocks it allows."""

    def build(*, question, rule_text, rule_context, selection_context, attachments):
        return _assemble(
            heading=heading, body=body, rules=rules, blocks=blocks,
            question=question, rule_text=rule_text, rule_context=rule_context,
            selection_context=selection_context, attachments=attachments,
        )

    return build


_ANSWER_FROM = (
    "Attached documents are the named rules the question is about, and they take precedence "
    "over the retrieved excerpt. When a document covers something the excerpt does not, "
    "answer from the document and quote its own wording.",
    "Answer from the material above and from what it plainly implies. It is from the 2024 SRD "
    "or from this project's own spell corpus, and each block says which.",
    _EDITION_RULE,
    "Say plainly which part of the answer the material above does not cover.",
    "Do not present a guess as a rule. If the material does not support an answer, say so.",
    "Be brief and concrete. Two or three sentences is usually enough.",
)

_INTERPRET = (
    "The 2024 SRD does not define this under a heading of its own, so the text below is the "
    "most relevant material it does contain. It is related to the question, not necessarily "
    "the rule itself."
)

VARIANTS: tuple[Variant, ...] = (
    Variant(
        name="required",
        # Imported, not rebuilt: this variant *is* the app, so scoring anything else here
        # would be measuring a copy.
        build=prompts.rules_inferred_prompt,
        blocks=Blocks(),
        why="The app's own prompt. The baseline every other variant is measured against.",
    ),
    Variant(
        name="treat-as-quoted",
        blocks=Blocks(selection=False),
        build=_variant(
            heading="You are answering a D&D 5.5e (2024) rules question for a player.",
            body="Answer only from the material provided.",
            rules=(
                "Quote the rule's own wording where it settles the question.",
                "Do not go beyond the material above. If it does not answer the question, say so.",
                _EDITION_RULE,
                "Be brief and concrete.",
            ),
            blocks=Blocks(selection=False),
        ),
        why=(
            "Tells the model to quote rather than interpret, and hides the book's paragraph. "
            "If this scores as well, the interpretation framing is unnecessary; if it scores "
            "worse, the framing is load-bearing and should not be tidied away."
        ),
    ),
    Variant(
        name="no-character-context",
        blocks=Blocks(character=False),
        build=_variant(
            heading="You are answering a D&D 5.5e (2024) rules question for a player.",
            body=_INTERPRET,
            rules=_ANSWER_FROM,
            blocks=Blocks(character=False),
        ),
        why=(
            "Drops the class context from the prompt. Worth measuring because it is most of "
            "the prompt: if it does not change the answers, contextual lookups get much "
            "cheaper and much faster."
        ),
    ),
    Variant(
        name="no-selection-context",
        blocks=Blocks(selection=False),
        build=_variant(
            heading="You are answering a D&D 5.5e (2024) rules question for a player.",
            body=_INTERPRET,
            rules=_ANSWER_FROM,
            blocks=Blocks(selection=False),
        ),
        why=(
            "Measures whether the book's paragraph helps or merely distracts. It is 400 "
            "characters of model-authored prose that may itself be wrong - a real question, "
            "not a formality."
        ),
    ),
    Variant(
        name="no-attachments",
        blocks=Blocks(attachments=False),
        build=_variant(
            heading="You are answering a D&D 5.5e (2024) rules question for a player.",
            body=_INTERPRET,
            rules=tuple(
                rule for rule in _ANSWER_FROM if not rule.startswith("Attached documents")
            ),
            blocks=Blocks(attachments=False),
        ),
        why=(
            "The control: what the app did before documents were attached, and the shape that "
            "reproduced 'the retrieved SRD text does not cover Thorn Whip'. If this ever "
            "scores as well as `required`, the attachment machinery has stopped earning its "
            "place."
        ),
    ),
    Variant(
        name="attachments-only",
        blocks=Blocks(retrieved=False),
        build=_variant(
            heading="You are answering a D&D 5.5e (2024) rules question for a player.",
            body=(
                "The documents below are the rules for what was selected, retrieved by name. "
                "There is no other retrieved text."
            ),
            rules=(
                "Answer from the attached documents. They are the rules the question is about.",
                _EDITION_RULE,
                "Say plainly which part the documents do not cover, and do not supply it from "
                "memory.",
                "Be brief and concrete.",
            ),
            blocks=Blocks(retrieved=False),
        ),
        why=(
            "Drops retrieval entirely and answers from the attached spell texts alone. The "
            "cheapest possible prompt for a named selection, and the honest test of whether "
            "the selection-path retrieval buys anything when documents are present."
        ),
    ),
)

VARIANTS_BY_NAME = {variant.name: variant for variant in VARIANTS}
