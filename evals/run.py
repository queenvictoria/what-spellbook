"""Run the contextual-menu cases against one or more prompt variants.

    python -m evals.run                       # the app's own prompt, every case
    python -m evals.run --variant required,no-attachments
    python -m evals.run --case named-spells-are-read --show-prompt

Live mode calls the configured model and costs real time or money. `--dry-run` assembles the
prompts, checks the attachments reached them, and prints the sizes without calling anything -
which is the mode to use while editing a variant, since a prompt that omits a block it claims
to include is a bug the score cannot show you.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Run from the repo root, as `python -m evals.run`, so this is a package import.
from evals.cases import CASES, CASES_BY_NAME, Case
from evals.scoring import Check, Result, attachments_reached, score, summarise
from evals.variants import VARIANTS, VARIANTS_BY_NAME, Variant


def build_context(case: Case, character: str) -> tuple[str, str, list[dict]]:
    """Retrieval, the character block and the resolved documents for one case.

    Retrieval runs the app's own cascade, so a case measures the real grounding rather than a
    fixture - the same reasoning as the API tests: stubbing retrieval would decide the
    outcome in the stub.
    """
    from backend.libs import characters, prompts, rules, service

    documents = (rules.resolve_attachments(case.attachments) if case.attachments
                 else rules.mentioned_documents(case.selection))
    try:
        retrieved = rules.gather(case.selection)
    except rules.RulesUnavailable:
        try:
            retrieved = rules.gather_inferred(case.selection)
        except rules.RulesUnavailable:
            try:
                retrieved = rules.gather_from_selection(case.selection)
            except rules.RulesUnavailable:
                retrieved = {"text": "", "passages": [], "url": rules.RULES_INDEX}

    sheet = {}
    if character:
        try:
            sheet = characters.load_character_data(character)
        except characters.CharacterNotFound:
            print(f"warning: no character sheet {character!r}; running without context",
                  file=sys.stderr)
    rule_context = prompts.load_rule_context(sheet) if sheet else ""
    return retrieved["text"], rule_context, documents


def run_case(case: Case, variant: Variant, *, character: str, dry_run: bool,
             show_prompt: bool, llm=None) -> Result:
    from backend.libs import llm as llm_module

    rule_text, rule_context, documents = build_context(case, character)
    prompt = variant.build(
        question=case.selection, rule_text=rule_text, rule_context=rule_context,
        selection_context=case.context, attachments=documents,
    )

    result = Result(case=case.name, variant=variant.name, answer="",
                    prompt_chars=len(prompt), dry_run=dry_run)

    if show_prompt:
        print(f"\n{'=' * 72}\n{case.name} / {variant.name}\n{'=' * 72}\n{prompt}\n")

    # Checked before the model runs, and recorded even in a dry run: whether the documents
    # reached the prompt is independent of what the model did with them.
    result.checks.extend(attachments_reached(prompt, case))

    if dry_run:
        result.answer = "(dry run)"
        return result

    if llm is None:
        llm = llm_module.build_llm()

    started = time.perf_counter()
    try:
        result.answer = llm_module.extract_text(llm_module.invoke(llm, prompt))
    except Exception as exc:                     # noqa: BLE001 - reported, not swallowed
        # A failed call is recorded as a failed *answer* rather than propagated, so a run of
        # twenty cases reports the one that broke instead of stopping at it. The exception is
        # reported by type and message, which is what distinguishes a rate limit from a
        # prompt the model refused.
        result.error = f"{type(exc).__name__}: {exc}"
    result.latency = time.perf_counter() - started

    if result.error:
        result.checks.append(Check("answered", False, result.error))
    elif result.answer:
        result.checks.extend(score(case, result.answer))
    else:
        result.checks.append(Check("answered", False, "the model returned nothing"))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", default="required",
                        help="comma-separated variant names, or 'all'")
    parser.add_argument("--case", default="all",
                        help="comma-separated case names, or 'all'")
    parser.add_argument("--character", default="", help="sheet to load as character context")
    parser.add_argument("--dry-run", action="store_true",
                        help="assemble prompts and check attachments without calling the model")
    parser.add_argument("--show-prompt", action="store_true", help="print each prompt")
    parser.add_argument("--json", type=Path, default=None, help="write raw results here")
    parser.add_argument("--failures", action=argparse.BooleanOptionalAction, default=True,
                        help="print each failing check and the answer that failed it")
    args = parser.parse_args(argv)

    variants = (list(VARIANTS) if args.variant == "all"
                else [VARIANTS_BY_NAME[name] for name in args.variant.split(",")])
    cases = (list(CASES) if args.case == "all"
             else [CASES_BY_NAME[name] for name in args.case.split(",")])

    llm = None
    if not args.dry_run:
        from backend.libs import llm as llm_module
        llm = llm_module.build_llm()
        print(f"model: {llm_module.model_name(llm)}")

    results = []
    for variant in variants:
        for case in cases:
            print(f"· {variant.name:24} {case.name}", end="", flush=True)
            result = run_case(case, variant, character=args.character,
                              dry_run=args.dry_run, show_prompt=args.show_prompt, llm=llm)
            results.append(result)
            mark = "ok  " if result.passed else "FAIL"
            print(f"  {mark} {result.latency:5.1f}s  {len(result.answer.split()):4}w")

    summary = summarise(results)
    header = f"\n{'variant':26} {'cases':>8} {'score':>7} {'prompt':>8} {'seconds':>8}"
    print(header)
    for name, stats in summary.items():
        # A dry run has no score and must not print one: the numbers under it are attachment
        # checks, and a "0.57" beside a variant that was never asked anything is a lie the
        # reader has no way to detect.
        score_text = "  (dry)" if stats["score"] is None else f"{stats['score']:7.2f}"
        print(f"{name:26} {stats['passed']}/{stats['total']:<6} "
              f"{score_text} {stats['prompt_chars']:8} {stats['seconds']:8.1f}")
    if all(stats["dry_run"] for stats in summary.values()):
        print("\nDry run: prompts were assembled and attachments checked, no model was called.")

    if args.failures:
        for result in results:
            if not result.passed:
                print(f"\n✗ {result.variant} / {result.case}")
                for check in result.failures:
                    print(f"    {check.name}: {check.detail}")
                if result.error:
                    print(f"    error: {result.error}")
                if result.answer:
                    print(f"    answer: {result.answer[:300]}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "summary": summary,
            "results": [
                {"case": r.case, "variant": r.variant, "answer": r.answer,
                 "latency": r.latency, "prompt_chars": r.prompt_chars, "error": r.error,
                 "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                            for c in r.checks]}
                for r in results
            ],
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
