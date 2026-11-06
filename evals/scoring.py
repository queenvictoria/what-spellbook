"""Turning an answer into a number, and the number into something actionable.

Every point is attached to a *reason*, because a score that moves without a reason cannot be
acted on. A run prints the failing checks, not just the total.

The checks are deliberately dumb - substring presence, mostly - and that is a design decision
rather than a shortcut. A model-graded rubric would be smoother and would also be a second
model's opinion, which means a prompt change could score better by pleasing the grader. These
checks can only be satisfied by producing the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.cases import Case

# A passing answer is one or two sentences. This is generous on purpose: the check is there to
# catch an answer that recites the whole spell, not to police style.
WORDS_MAX = 140


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Result:
    case: str
    variant: str
    answer: str
    checks: list[Check] = field(default_factory=list)
    latency: float = 0.0
    prompt_chars: int = 0
    error: str | None = None

    # A dry run measures whether the documents reached the prompt, not whether the answer is
    # right. Recorded so a summary can refuse to report a score it did not measure - otherwise
    # a dry run prints a confident 0.57 that means nothing at all.
    dry_run: bool = False

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        return sum(check.passed for check in self.checks) / len(self.checks)


def _contains(answer: str, needle: str) -> bool:
    return needle.lower() in answer.lower()


def score(case: Case, answer: str) -> list[Check]:
    """Grade one answer against one case. Returns every check, passed or not."""
    checks: list[Check] = []
    words = len(answer.split())

    if not answer.strip():
        return [Check("answered", False, "the model returned nothing")]

    for needle in case.must_mention:
        checks.append(Check(
            f"mentions {needle!r}",
            _contains(answer, needle),
            "" if _contains(answer, needle) else f"{needle!r} is absent from the answer",
        ))

    for needle in case.must_not_mention:
        checks.append(Check(
            f"avoids {needle!r}",
            not _contains(answer, needle),
            # The offending substring is quoted rather than described, because "it mentioned
            # Mending" and "it said the word Mending" want different fixes.
            "" if not _contains(answer, needle) else f"the answer contains {needle!r}",
        ))

    # Length is a check rather than a style note because the failure it catches is real: a
    # model given three spell descriptions tends to summarise all three, which buries the
    # answer to the question that was asked.
    checks.append(Check(
        f"under {WORDS_MAX} words",
        words <= WORDS_MAX,
        "" if words <= WORDS_MAX else f"{words} words",
    ))
    return checks


def attachments_reached(prompt: str, case: Case) -> list[Check]:
    """That each document the case expects was physically in the prompt.

    Separate from the answer checks and checked before the model runs, because it catches a
    different failure: an answer that is right about a spell it was never given. That looks
    exactly like a good answer, so nothing in the text can reveal it.
    """
    checks = []
    for name in case.must_attach:
        checks.append(Check(
            f"attached {name!r}",
            f"--- {name} (" in prompt,
            "" if f"--- {name} (" in prompt else f"{name!r} was not in the prompt",
        ))
    return checks


def summarise(results: list[Result]) -> dict:
    """Aggregate results by variant, which is the only interesting axis."""
    by_variant: dict[str, list[Result]] = {}
    for result in results:
        by_variant.setdefault(result.variant, []).append(result)

    summary = {}
    for variant, group in by_variant.items():
        dry = all(result.dry_run for result in group)
        passed = sum(result.passed for result in group)
        summary[variant] = {
            "passed": passed,
            "total": len(group),
            # None rather than a number when the answers were never produced. A zero would
            # read as "every answer was wrong", which is a different and false claim.
            "score": None if dry else (
                sum(result.score for result in group) / len(group) if group else 0.0
            ),
            "failed": [result.case for result in group if not result.passed],
            "prompt_chars": (sum(r.prompt_chars for r in group) // len(group)) if group else 0,
            "seconds": sum(result.latency for result in group),
            "dry_run": dry,
        }
    return summary
