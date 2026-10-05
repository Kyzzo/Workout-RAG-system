"""
Accuracy regression check for the citation judge and value generation.
Replays known cases - misrepresentations that must be rejected and sound
claims that must be accepted - with real model calls, so a prompt or model
change that quietly lets "18-31 sets is optimal" back in (or starts
rejecting a valid value) shows up before it ships.

Not part of the app and not a pytest test: pytest mocks every model call,
so it can't tell whether the real judge decides well. This costs real API
calls; run it before changing a judge or generation prompt, a model or a
reasoning effort, and after ingesting papers that could change what
generation sees. When a new misrepresentation turns up, add it as a case.

Judge cases use fixed excerpts (scripts/eval_fixtures/judge_excerpts.json,
copied verbatim from the corpus), so retrieval and re-ingests can't change
what's being tested. Generation cases run the real pipeline (retrieval +
writer + judge). Each case runs several times, since verdicts vary run to
run: PASS = every run correct, FLAKY = some, FAIL = none; ERROR = a run
couldn't get an answer (API down, rate limit, no credits), which says
nothing about accuracy. Exits non-zero unless everything passes.

Usage (from backend/):
    uv run python -m scripts.eval_judge                 # judge + generation
    uv run python -m scripts.eval_judge --judge-only    # cheaper: judge cases only
    uv run python -m scripts.eval_judge --chat          # also the chat answer case (~45s/run)
    uv run python -m scripts.eval_judge --repeats 5 --list
"""

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from app.rag import verification
from app.rag.generate import VOLUME_BANDS, build_reps_query, build_rir_query, build_volume_query
from app.rag.verification import STATEMENT_JUDGE, Judge, judge_citation

EXCERPTS = json.loads((Path(__file__).parent / "eval_fixtures" / "judge_excerpts.json").read_text(encoding="utf-8"))
SUPPORTED = {"primary_support", "contextual_support"}
CHAT_QUESTION = "What is the optimal number of weekly sets per muscle for hypertrophy?"


@dataclass(frozen=True)
class JudgeCase:
    name: str
    excerpt: str  # key in judge_excerpts.json
    question: str
    answer: str | int
    judge: str  # "statement" (chat prose, rule claims) or "generation" (bare values)
    # "supported", "rejected", or "not_direct": a deliberately borderline
    # case where related evidence or a rejection are both defensible, and
    # the only wrong verdict is claiming the excerpt states the value.
    expect: str
    why: str


def _volume_q(muscle: str, goal: str = "hypertrophy") -> str:
    return build_volume_query(muscle, goal)


JUDGE_CASES = [
    # --- chat statements: the reported misrepresentations and their faithful versions
    JudgeCase("merged 18-31 optimum", "remmert_intro", CHAT_QUESTION,
              "18 to 31 sets per week is optimal for hypertrophy.", "statement", "rejected",
              "the original bug: a no-superiority point merged with another figure into an 'optimal' range"),
    JudgeCase("hedged ceiling", "remmert_intro", CHAT_QUESTION,
              "Beyond about 31 sets per week, additional volume may be an upper limit for hypertrophy.",
              "statement", "rejected", "'no detectable superiority' read as a ceiling, even hedged"),
    JudgeCase("unit dropped + optimum", "remmert_intro", CHAT_QUESTION,
              "The optimal weekly volume for hypertrophy is about 31 sets.", "statement", "rejected",
              "fractional dropped and the finding upgraded to an optimum"),
    JudgeCase("faithful 31", "remmert_intro", CHAT_QUESTION,
              "A recent meta-analysis found a positive dose-response between weekly sets and hypertrophy, "
              "with no detectable superiority beyond about 31 fractional sets per week.",
              "statement", "supported", "states the finding with its qualifiers"),
    JudgeCase("strength finding as hypertrophy", "aube_conclusion", CHAT_QUESTION,
              "About 18 weekly sets is optimal for quadriceps hypertrophy.", "statement", "rejected",
              "Aube's ~18 is a squat 1RM (strength) finding"),
    JudgeCase("narrowed range", "aube_conclusion", CHAT_QUESTION,
              "The most optimal range for hypertrophy is approximately 18 to 24 weekly sets.",
              "statement", "rejected", "Aube found 12-24 similar; narrowing it to an optimum changes the finding"),
    JudgeCase("faithful 12-24", "aube_conclusion", CHAT_QUESTION,
              "In resistance-trained lifters who could squat more than twice their body mass, 12 to 24 weekly "
              "sets produced similar lower-body muscle growth.", "statement", "supported",
              "the hypertrophy finding with its population"),
    JudgeCase("faithful strength 18", "aube_conclusion", "How many weekly sets for squat strength?",
              "Around 18 weekly quadriceps sets may optimize back squat 1RM gains in resistance-trained "
              "individuals.", "statement", "supported", "the strength finding, labeled as strength"),
    JudgeCase("per-session ceiling", "remmert_puos", "How many sets per session for hypertrophy?",
              "11 fractional sets per session is the upper limit; more sets per session add nothing.",
              "statement", "rejected", "the excerpt says outright these values are not upper limits"),
    JudgeCase("faithful per-session", "remmert_puos", "How many sets per session for hypertrophy?",
              "Beyond about 11 fractional sets per session, no per-session volume showed a detectable "
              "advantage for hypertrophy.", "statement", "supported", "the per-session finding as stated"),
    # --- generated values: bare numbers judged as 'a weekly volume the research supports'
    JudgeCase("18 inside intermediate tier", "tier_table", _volume_q("chest"), 18, "generation", "supported",
              "inside the 11-18 tier"),
    JudgeCase("12 inside intermediate tier", "tier_table", _volume_q("chest"), 12, "generation", "supported",
              "inside the 11-18 tier"),
    JudgeCase("8 inside higher-efficiency tier", "tier_table", _volume_q("chest"), 8, "generation", "supported",
              "inside the 5-10 tier"),
    JudgeCase("31 as a dose", "remmert_intro", _volume_q("chest"), 31, "generation", "rejected",
              "a no-superiority point is not a recommended dose"),
    JudgeCase("18 inside Aube's similar range", "aube_conclusion", _volume_q("quadriceps"), 18, "generation",
              "supported", "quads hypertrophy, inside the 12-24 range that grew similarly"),
    JudgeCase("bibliography", "pelland_bibliography", _volume_q("chest"), 12, "generation", "rejected",
              "a reference list lists papers, not findings"),
    JudgeCase("1-2 RIR as studied", "refalo_key_points",
              build_rir_query("quadriceps", "hypertrophy", "Leg Extension"), "1-2 RIR", "generation", "supported",
              "1-2 RIR grew the quadriceps as much as training to failure"),
    JudgeCase("3-4 RIR beyond what was studied", "refalo_key_points",
              build_rir_query("quadriceps", "hypertrophy", "Leg Extension"), "3-4 RIR", "generation", "rejected",
              "the excerpt supports 1-2 RIR (and 0-2), not stopping 3-4 reps short"),
    # Deliberately borderline. The excerpt is about LOAD (%1RM) and says
    # there's "no ideal hypertrophy zone"; supporting "8-12 reps" needs the
    # inference that moderate loads ~ 8-12 reps. The judge splits between
    # related evidence and contradicted (both defensible), so this case
    # doesn't test which - it tests that the judge never OVERCLAIMS on
    # borderline evidence by calling it direct support. Don't "fix" it by
    # expecting either verdict.
    JudgeCase("8-12 reps vs a load-only excerpt (borderline)", "schoenfeld_loading",
              build_reps_query("chest", "hypertrophy", "Barbell Bench Press"), "8-12", "generation", "not_direct",
              "the excerpt discusses load, not reps - related or rejected are both fine, 'states this directly' isn't"),
]

# (muscle, goal, preference): the value must land in its goal and
# preference's band (VOLUME_BANDS) and verify.
GENERATION_CASES = [
    (muscle, "hypertrophy", preference)
    for muscle in ("chest", "quadriceps")
    for preference in ("minimal", "moderate", "high")
] + [("chest", "strength", preference) for preference in ("minimal", "moderate", "high")]


def _run_judge_case(case: JudgeCase) -> tuple[bool, str]:
    # Read at call time, so --generation-judge (which swaps it module-wide,
    # generation cases included) applies here too.
    judge = STATEMENT_JUDGE if case.judge == "statement" else verification.GENERATION_JUDGE
    try:
        verdict = judge_citation(case.question, case.answer, EXCERPTS[case.excerpt]["text"], judge=judge)
    except Exception as e:  # an error is a failed run, not a crash of the whole check
        return False, f"error: {type(e).__name__}"
    if case.expect == "not_direct":
        return verdict.outcome != "primary_support", verdict.outcome
    supported = verdict.outcome in SUPPORTED
    return supported == (case.expect == "supported"), verdict.outcome


def _run_generation_case(case) -> tuple[bool, str]:
    from app.routers.generation import _attempt_weekly_volume_generation

    muscle, goal, preference = case
    try:
        result, verified, any_supported = _attempt_weekly_volume_generation(muscle, goal, preference)
    except Exception as e:
        return False, f"error: {type(e).__name__}"
    band = VOLUME_BANDS.get(goal, {}).get(preference)
    in_band = band is None or band[0] <= result.weekly_sets <= band[1]
    papers = len({chunk["source"] for chunk, status in verified if status in SUPPORTED})
    return in_band and any_supported, f"{result.weekly_sets}/wk, {'verified' if any_supported else 'UNVERIFIED'} ({papers} papers)"


def _run_chat_case(_) -> tuple[bool, str]:
    from app.routers.chat import _handle_general_question

    try:
        answer = _handle_general_question(SimpleNamespace(topic=CHAT_QUESTION), CHAT_QUESTION).answer
    except Exception as e:
        return False, f"error: {type(e).__name__}"
    merged = re.search(r"\b18\s*(?:-|–|to)\s*31\b", answer)
    # every sentence that mentions 31 sets must keep 'fractional'
    bare_31 = [s for s in re.split(r"(?<=[.!?])\s+", answer) if re.search(r"\b31\b", s) and "fractional" not in s]
    ok = not merged and not bare_31
    return ok, "ok" if ok else ("merged 18-31 range" if merged else "31 without 'fractional'")


def _report(label: str, cases, runner, repeats: int, describe) -> bool:
    jobs = [(i, case) for i, case in enumerate(cases) for _ in range(repeats)]
    with ThreadPoolExecutor(max_workers=min(len(jobs), 16)) as pool:
        results = list(pool.map(lambda job: (job[0], runner(job[1])), jobs))
    print(f"\n{label}")
    all_pass, errored = True, False
    for i, case in enumerate(cases):
        runs = [r for j, r in results if j == i]
        errors = sum(detail.startswith("error:") for _, detail in runs)
        answered = len(runs) - errors
        passed = sum(ok for ok, _ in runs)
        if errors:
            status = "ERROR"
        else:
            status = "PASS " if passed == answered else ("FLAKY" if passed else "FAIL ")
        all_pass &= passed == len(runs)
        errored |= bool(errors)
        print(f"  {status} {passed}/{answered}  {describe(case)}  [{'; '.join(detail for _, detail in runs)}]")
    if errored:
        print("  (ERROR = no answer from the API - check credits/rate limits and re-run; not an accuracy result)")
    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Judge and generation accuracy regression check")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--judge-only", action="store_true", help="skip the generation cases")
    parser.add_argument("--chat", action="store_true", help="also run the chat answer case")
    parser.add_argument("--list", action="store_true", help="list the cases without running them")
    parser.add_argument(
        "--generation-judge", metavar="MODEL[:EFFORT]",
        help="try a different judge for generated values, e.g. gpt-5-mini:low (default: the app's)",
    )
    parser.add_argument(
        "--judge-cases", choices=("all", "statement", "generation"), default="all",
        help="which judge cases to run (generation = bare generated values only)",
    )
    args = parser.parse_args()
    if args.generation_judge:
        model, _, effort = args.generation_judge.partition(":")
        verification.GENERATION_JUDGE = Judge(model, effort or None)

    describe_judge = lambda c: f"{c.name} -> expect {c.expect} ({c.judge} judge): {c.why}"
    describe_gen = lambda c: f"weekly volume {c[0]} / {c[1]} / {c[2]}" + (
        f" -> in {VOLUME_BANDS[c[1]][c[2]]} and verified")
    if args.list:
        for case in JUDGE_CASES:
            print("judge      ", describe_judge(case))
        for case in GENERATION_CASES:
            print("generation ", describe_gen(case))
        print("chat        no merged 18-31 range; 31 always with 'fractional' (--chat)")
        return 0

    logging.disable(logging.INFO)
    print(f"judges: statement={STATEMENT_JUDGE}, generation={verification.GENERATION_JUDGE}; {args.repeats} runs per case")
    judge_cases = [c for c in JUDGE_CASES if args.judge_cases in ("all", c.judge)]
    ok = _report("JUDGE CASES", judge_cases, _run_judge_case, args.repeats, describe_judge)
    if not args.judge_only:
        ok &= _report("GENERATION CASES", GENERATION_CASES, _run_generation_case, args.repeats, describe_gen)
    if args.chat:
        ok &= _report("CHAT CASE", [CHAT_QUESTION], _run_chat_case, args.repeats, lambda q: f"chat: {q}")
    print("\nALL PASS" if ok else "\nSOME CASES DID NOT PASS - see FAIL/FLAKY above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
