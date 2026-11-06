# Contextual prompt evals

Scoring for the contextual menu's prompts, so a prompt change is measurable instead of a
matter of opinion.

```bash
# what the app does, every case, no model call - assemble, check attachments, print sizes
.venv/bin/python -m evals.run --dry-run

# one variant against every case, with the real model
.venv/bin/python -m evals.run --variant required --character lois

# does dropping the character block actually cost anything?
.venv/bin/python -m evals.run --variant required,no-character-context --character lois

# see the prompt that is being scored
.venv/bin/python -m evals.run --case named-spells-are-read --dry-run --show-prompt

# keep the raw answers for a diff between two branches
.venv/bin/python -m evals.run --variant all --json /tmp/before.json
```

## Why it is shaped like this

**The cases are real sessions, not inventions.** Several are cases the app used to get
wrong, which is the point: an eval whose cases all pass already measures nothing.

**The checks are substrings, and that is deliberate.** A model-graded rubric would be smoother
and would also be a second model's opinion, so a prompt change could score better by pleasing
the grader. These checks can only be satisfied by producing the fact - `1d6` for Thorn Whip's
base damage is in that spell's text and nowhere else in the SRD, so only actually reading the
attached document can produce it.

**Attachments are checked before the model runs.** An answer that is right about a spell it
was never given looks exactly like a good answer, so nothing in the answer text can reveal it.
`must_attach` is checked against the assembled prompt instead.

**A dry run prints no score.** The numbers it does produce are attachment checks; a "0.57"
beside a variant that was never asked anything would be a lie the reader cannot detect. It
prints `(dry)` and says so.

## Variants

| Variant | What it changes |
| --- | --- |
| `required` | Nothing - it *is* `backend.libs.prompts`. The baseline. |
| `treat-as-quoted` | Tells the model to quote, and hides the book's paragraph. |
| `no-character-context` | Drops the class context, which is most of the prompt. |
| `no-selection-context` | Drops the book's paragraph; measures whether it helps or distracts. |
| `no-attachments` | The control: the shape that produced *"the retrieved SRD text does not cover Thorn Whip"*. |
| `attachments-only` | Drops retrieval entirely; tests whether it buys anything once documents are attached. |

Every block a variant switches off is **physically absent** from the prompt it builds -
`evals/variants.py` assembles from `Blocks` rather than trusting a label. A variant that
claimed to omit a block while still emitting it would produce numbers that look like evidence
and are not.

## Adding a case

Record it from a session where the answer was wrong or thin, put the **fact only the attached
document carries** in `must_mention`, and write `why` so a failure report says what broke. A
case without a reason attached is not actionable when it starts failing.

## This is not `pytest`

`evals/` is a development tool: it calls a model and costs time or money, and `backend/` must
never import it. The deterministic half of this behaviour - mention resolution, prompt block
assembly, the retrieval cascade - belongs in `tests/`, and is tested there.
