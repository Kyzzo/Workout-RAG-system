"""
Accuracy check for excerpt labeling (app/rag/excerpt_kinds.py). Value
generation stops retrieving excerpts labeled as reporting no result, so the
costly mistake is labeling a real finding as a non-finding - it would vanish
from generation for good. Every finding case must stay a finding; the
theory-describing introduction must be caught. Runs the same two passes as
ingestion: LABEL_MODEL, then CONFIRM_MODEL on any non-finding label.

Uses eval_judge's fixed excerpts (copied verbatim from the corpus) and
reporting: PASS = every run correct, FLAKY = some, FAIL = none. Costs real
API calls; run it before changing the labeling prompt or model, then re-label
the corpus (scripts/label_excerpt_kinds.py --relabel).

Usage (from backend/):
    uv run python -m scripts.eval_excerpt_kinds
    uv run python -m scripts.eval_excerpt_kinds --model gpt-5:low --repeats 5
"""

import argparse
import logging
import sys
from dataclasses import dataclass

from app.rag.corpus import paper
from app.rag.excerpt_kinds import LABEL_MODEL, NON_FINDING_KINDS, confirm_kind, read_excerpt
from scripts.eval_judge import EXCERPTS, _report

FINDING, NO_RESULT = "finding", "no_result"


@dataclass(frozen=True)
class KindCase:
    excerpt: str  # key in eval_fixtures/judge_excerpts.json
    expect: str  # FINDING (own or cited), NO_RESULT (any other kind), or an exact kind
    why: str


KIND_CASES = [
    KindCase("remmert_intro", FINDING,
             "an introduction, but it reports Pelland's results - dropping it loses real evidence"),
    KindCase("remmert_puos", FINDING, "the paper's own per-session result"),
    KindCase("aube_conclusion", FINDING, "the trial's conclusions"),
    KindCase("pelland_results", FINDING, "meta-regression results"),
    KindCase("tier_table", FINDING, "a table of volume tiers drawn from the evidence"),
    KindCase("refalo_key_points", FINDING, "the trial's key points"),
    KindCase("plotkin_cited_loading", FINDING,
             "an introduction citing Schoenfeld 2017's 5-30+ rep hypertrophy result - gpt-5-mini called it methods"),
    KindCase("schoenfeld_loading", FINDING,
             "the review's own conclusions on loading zones"),
    KindCase("schoenfeld_continuum_intro", "described_view",
             "lays out the repetition continuum, which the paper goes on to challenge - states 8-12 verbatim"),
    KindCase("pelland_bibliography", NO_RESULT, "a reference list"),
]


def _citation(case: KindCase) -> str:
    source = EXCERPTS[case.excerpt]["source"]
    try:
        return paper(source).citation
    except KeyError:
        return source


def _correct(case: KindCase, kind: str) -> bool:
    if case.expect == FINDING:
        return kind not in NON_FINDING_KINDS
    if case.expect == NO_RESULT:
        return kind in NON_FINDING_KINDS
    return kind == case.expect


def main():
    parser = argparse.ArgumentParser(description="Excerpt labeling accuracy check")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--model", metavar="MODEL[:EFFORT]", help=f"default: {LABEL_MODEL[0]}:{LABEL_MODEL[1]}")
    parser.add_argument("--first-pass-only", action="store_true",
                        help="skip CONFIRM_MODEL's second opinion on non-finding labels")
    args = parser.parse_args()
    model = LABEL_MODEL
    if args.model:
        name, _, effort = args.model.partition(":")
        model = (name, effort or None)

    def run(case: KindCase) -> tuple[bool, str]:
        try:
            label, text = _citation(case), EXCERPTS[case.excerpt]["text"]
            first = read_excerpt(label, text, model=model).kind
            kind = first if args.first_pass_only else confirm_kind(label, text, first)
        except Exception as e:
            return False, f"error: {type(e).__name__}"
        if kind is None:
            return False, "error: no second opinion"
        return _correct(case, kind), kind if kind == first else f"{first}->{kind}"

    logging.disable(logging.INFO)
    print(f"label model: {model}; {args.repeats} runs per case")
    ok = _report("KIND CASES", KIND_CASES, run, args.repeats,
                 lambda c: f"{c.excerpt} -> expect {c.expect}: {c.why}")
    print("\nALL PASS" if ok else "\nSOME CASES DID NOT PASS - see FAIL/FLAKY above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
