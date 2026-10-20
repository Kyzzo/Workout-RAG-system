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
    uv run python -m scripts.eval_judge --chat          # also the chat answer cases (~45s/run each)
    uv run python -m scripts.eval_judge --repeats 5 --list
"""

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from app.rag import verification
from app.rag.corpus import evidence_text, paper
from app.rag.generate import VOLUME_BANDS, build_movement_query, build_reps_query, build_rir_query, build_volume_query
from app.rag.verification import Judge, judge_citation

EXCERPTS = json.loads((Path(__file__).parent / "eval_fixtures" / "judge_excerpts.json").read_text(encoding="utf-8"))
SUPPORTED = {"primary_support", "contextual_support"}
CHAT_QUESTION = "What is the optimal number of weekly sets per muscle for hypertrophy?"
# A question ABOUT a theory: the excerpt describing it is the right source,
# so value generation's findings-only retrieval must never reach chat.
THEORY_QUESTION = "What is the repetition continuum?"


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
    JudgeCase("8-12 reps from a theory the paper re-examines", "schoenfeld_continuum_intro",
              build_reps_query("chest", "hypertrophy", "Barbell Bench Press"), "8-12", "generation", "rejected",
              "the intro describes what the repetition continuum proposes - a belief the paper goes on to "
              "challenge, not a finding - though it states 8-12 word for word"),
    # Similar-outcome findings support a bare value inside the compared span:
    # production rejected 8-12 for compound hypertrophy (Oct 19, 4 of 4
    # attempts), reading 'similar growth across loads, no ideal zone' as
    # contradicting any recommended range. A bare value claims no optimum.
    JudgeCase("8-12 inside cited 8-12RM-vs-light findings", "schoenfeld_cited_moderate",
              build_movement_query("reps", "hypertrophy", "compound"), "8-12", "generation", "supported",
              "cited trials found 8-12RM grew muscle like 20-25RM and ~30RM - 8-12 is one of the effective ranges"),
    JudgeCase("8-12 vs 'heavy and light loads equally effective'", "schoenfeld2017_equal_loads",
              build_movement_query("reps", "hypertrophy", "compound"), "8-12", "generation", "supported",
              "moderate reps sit between the heavy and light loads found equally effective (related evidence at least)"),
    JudgeCase("8-12 inside similar rep ranges (Klemp)", "klemp_similar_reps",
              build_movement_query("reps", "hypertrophy", "compound"), "8-12", "generation", "supported",
              "volume-equated 12-10-8 and 6-4-2 reps grew muscle similarly; 8-12 is inside what was compared"),
    JudgeCase("40-50 beyond the loads compared", "schoenfeld_cited_moderate",
              build_movement_query("reps", "hypertrophy", "compound"), "40-50", "generation", "rejected",
              "the cited trials span 2-6RM to ~30RM; 'similar across loads' doesn't reach a range nobody trained"),
    JudgeCase("theory presented as the theory", "schoenfeld_continuum_intro", THEORY_QUESTION,
              "The traditional repetition continuum holds that a moderate repetition scheme of 8 to 12 "
              "repetitions per set at 60% to 80% of 1RM optimizes muscle hypertrophy.", "statement", "supported",
              "describing the view as a view is exactly what the excerpt supports - chat needs this"),
    JudgeCase("theory presented as fact", "schoenfeld_continuum_intro", "What rep range is best for hypertrophy?",
              "8 to 12 repetitions per set at 60% to 80% of 1RM is optimal for muscle hypertrophy.",
              "statement", "rejected", "the view's claim stated as a finding"),
    # Study details: a live chat answer put Aube 2022 'over 9 weeks' in
    # 'highly trained males' and was accepted as direct support. The
    # excerpt says an 8-week block in subjects who squat over twice their
    # body mass, sex not stated.
    JudgeCase("faithful study details", "aube_conclusion", CHAT_QUESTION,
              "Over an 8-week block, 12 to 24 weekly sets produced similar lower-body muscle growth in "
              "resistance-trained individuals who could squat more than twice their body mass.",
              "statement", "supported", "length and population as the excerpt states them"),
    JudgeCase("wrong study length", "aube_conclusion", CHAT_QUESTION,
              "Over 9 weeks, 12 to 24 weekly sets produced similar lower-body muscle growth in "
              "resistance-trained individuals who could squat more than twice their body mass.",
              "statement", "rejected", "the excerpt says an 8-week block"),
    JudgeCase("population not stated", "aube_conclusion", CHAT_QUESTION,
              "In highly trained men, 12 to 24 weekly sets produced similar lower-body muscle growth over "
              "an 8-week block.", "statement", "rejected", "the excerpt never says the subjects were men"),
]

@dataclass(frozen=True)
class SummaryCase:
    name: str
    excerpts: tuple[str, ...]  # keys in judge_excerpts.json, judged together as in chat
    question: str
    summary: str
    expect: str  # "supported" or "rejected"
    why: str


_VOLUME = ("pelland_results", "tier_table", "aube_conclusion", "remmert_intro")
_LOAD = ("schoenfeld_loading", "plotkin_cited_loading", "schoenfeld_continuum_intro")
_LOAD_QUESTION = "Can light weights build as much muscle as heavy weights?"
_FAILURE_QUESTION = "Do I need to train to failure to build muscle?"

# Chat's lead summary may synthesize across its excerpts, so it's judged
# against all of them at once (verification.judge_summary). Faithful
# summaries must pass; each trap is a way a synthesis misrepresents.
SUMMARY_CASES = [
    SummaryCase("faithful dose-response", _VOLUME, CHAT_QUESTION,
                "More weekly sets generally bring more muscle growth, but with diminishing returns: gains per added "
                "set are largest at lower volumes (around 5-10 fractional sets per muscle per week) and get smaller as "
                "volume rises. In very strong lifters, 12 to 24 weekly sets produced similar growth over 8 weeks.",
                "supported", "the dose-response with its units and Aube's population"),
    SummaryCase("faithful hedged range", _VOLUME, CHAT_QUESTION,
                "For most lifters, roughly 5 to 18 fractional sets per muscle per week is an efficient range for "
                "growth; more sets can still add muscle, but each extra set adds less.",
                "supported", "a rough range the efficiency tiers cover, hedged, with diminishing returns"),
    SummaryCase("sub-range called optimal", _VOLUME, CHAT_QUESTION,
                "The optimal volume for muscle growth is 18 to 24 weekly sets; doing fewer sets leaves growth on the "
                "table.", "rejected", "Aube found 12-24 similar; nothing makes 18-24 optimal"),
    SummaryCase("ceiling", _VOLUME, CHAT_QUESTION,
                "Muscle growth stops at about 31 sets per week, so there is no benefit to doing more than that.",
                "rejected", "'no detectable superiority beyond ~31 fractional sets' read as a ceiling, unit dropped"),
    SummaryCase("unit changed", _VOLUME, CHAT_QUESTION,
                "About 5 to 10 total sets per muscle per week is the most efficient range for growth, and 11 to 18 "
                "total sets is intermediate.", "rejected", "the tiers are fractional sets, presented as total sets"),
    # Answering in the user's unit (total sets, as lifters count): an open,
    # correct conversion from fractional passes; a wrong one doesn't.
    SummaryCase("faithful conversion to total sets (chest)", _VOLUME, "How many sets per week should I do for chest?",
                "Research counts fractional sets: a direct set counts as 1 and a set where the muscle only assists as "
                "half. Roughly 5 to 18 fractional sets per week is an efficient range, with smaller gains above it. "
                "Chest work - presses and flyes - is direct, so that is also 5 to 18 total chest sets per week.",
                "supported", "the source figure, its unit and an open, correct conversion"),
    SummaryCase("faithful conversion to total sets (triceps)", _VOLUME,
                "How many sets per week should I do for triceps?",
                "Research counts fractional sets: a direct set counts as 1 and a set where the muscle only assists as "
                "half. Roughly 5 to 18 fractional sets per week is an efficient range. Presses train the triceps "
                "indirectly, so total sets run higher: for example 10 fractional sets could be 6 pushdowns plus 8 "
                "bench sets, which is 14 total sets.", "supported", "total = fractional + half the indirect sets"),
    SummaryCase("halved conversion", _VOLUME, "How many sets per week should I do for chest?",
                "Roughly 5 to 18 fractional sets per week is an efficient range; since a fractional set is half a "
                "normal set, that works out to about 2.5 to 9 total chest sets per week.", "rejected",
                "fractional counts aren't halved - for chest they equal total sets"),
    SummaryCase("wrong conversion", _VOLUME, "How many sets per week should I do for chest?",
                "Roughly 5 to 18 fractional sets per muscle per week is an efficient range, which works out to about "
                "10 to 36 direct sets per week.", "rejected",
                "direct sets can't exceed fractional sets - the conversion is wrong"),
    # From a quads answer that lost all three summaries (Oct 19, 2026): quad
    # work is direct, so a total count needs no spelled-out conversion - but
    # a different number for the same tiers is still wrong.
    SummaryCase("faithful total sets for a direct muscle (quads)", _VOLUME, "Is 10 sets a week enough to grow my quads?",
                "Yes: 10 sets a week can grow your quads. Count every quad set as 1 set. Research places higher- and "
                "intermediate-efficiency growth at 5 to 18 fractional sets per week, with each extra set adding less, "
                "and in very strong lifters 12 to 24 weekly sets produced similar quad growth.",
                "supported", "quad sets are all direct, so 10 total sets is 10 fractional sets, inside 5-18"),
    SummaryCase("shifted range for a direct muscle (quads)", _VOLUME, "Is 10 sets a week enough to grow my quads?",
                "For most lifters: about 11 to 18 sets per week for quads. Quad work is direct; the research's 5 to "
                "18 fractional sets per week aligns with roughly 11 to 18 total sets.", "rejected",
                "for quads 5-18 fractional sets is 5-18 total sets, not 11-18"),
    SummaryCase("strength result as hypertrophy", _VOLUME, CHAT_QUESTION,
                "About 18 weekly sets is the sweet spot for building quad size in trained lifters.",
                "rejected", "Aube's ~18 sets is a squat 1RM finding"),
    SummaryCase("overcertain", _VOLUME, CHAT_QUESTION,
                "Research has proven that every additional weekly set always produces more muscle growth.",
                "rejected", "'proven' and 'always' - the findings show diminishing returns"),
    SummaryCase("one population generalized", _VOLUME, CHAT_QUESTION,
                "Doing more than 12 weekly sets per muscle does not add muscle growth.",
                "rejected", "Aube's highly trained squatters generalized, hiding the meta-analyses' dose-response"),
    SummaryCase("faithful load spectrum", _LOAD, _LOAD_QUESTION,
                "Yes - from roughly 30% of your max up to heavy weights, muscle growth is similar when sets are taken "
                "with a high level of effort. Heavier loads are better for maximal strength, and light loads mean "
                "many more reps and more discomfort.", "supported", "the review's findings with their qualifiers"),
    SummaryCase("theory stated as fact", _LOAD, _LOAD_QUESTION,
                "Moderate loads of 8 to 12 reps per set are the best range for building muscle; lighter and heavier "
                "loads build less.", "rejected", "the repetition continuum's claim, which the review's findings contradict"),
    SummaryCase("load overreach", _LOAD, _LOAD_QUESTION,
                "Any load builds the same muscle, even very light weights well below 30% of your max.",
                "rejected", "the similar-growth finding holds at >= ~30% 1RM"),
    SummaryCase("faithful theory answer", ("schoenfeld_continuum_intro", "schoenfeld_loading"), THEORY_QUESTION,
                "The repetition continuum is the traditional idea that heavy, low-rep training builds strength, "
                "moderate reps build muscle and light, high-rep training builds endurance. A 2021 review found the "
                "strength part holds up, but muscle growth is similar across a wide range of loads.",
                "supported", "the view presented as a view, then the review's findings"),
    SummaryCase("faithful proximity to failure", ("refalo_key_points",), _FAILURE_QUESTION,
                "Not necessarily: in trained lifters, stopping sets 1-2 reps short of failure grew the quadriceps "
                "about as much as training to failure over 8 weeks.", "supported", "Refalo 2024 as reported"),
    SummaryCase("failure overclaimed", ("refalo_key_points",), _FAILURE_QUESTION,
                "Training to failure produces clearly more muscle growth than stopping short, so every set should "
                "go to failure.", "rejected", "Refalo found similar growth"),
    # From the Oct 15 end-to-end chat audit: every unfaithful claim was a
    # lead summary adding advice no excerpt gives. The four summaries are
    # verbatim; each has a faithful counterpart from the same excerpts.
    # KNOWN GAP: the current summary judge passes the three advice traps
    # (Oct 16: 1/5, 0/5, 0/5 correct). A separate advice judge at low effort
    # catches them 5/5 but adds ~15s per answer - see
    # notes/design_choices/chat_speed_cost_accuracy.txt section 8.
    SummaryCase("advice moved to beginners", ("lopez_conclusions", "aube_conclusion"),
                "Do trained lifters need more volume than beginners?",
                "For most lifters: more weekly sets help, but trained lifters don't clearly need more than beginners.\n"
                "Count every set that trains the muscle; size and strength both rise with volume, but each extra set "
                "helps less. In trained people, several studies report no extra hypertrophy from very high weekly "
                "sets versus moderate work, while beginners tend to grow more and may benefit from simply training "
                "more often. Use moderate volumes first, then add sets only if progress stalls.",
                "rejected", "Lopez found more sessions helped those WITH training experience, not beginners"),
    SummaryCase("faithful training status", ("lopez_conclusions", "aube_conclusion"),
                "Do trained lifters need more volume than beginners?",
                "Not clearly: in very strong lifters, 12 to 24 weekly sets produced similar muscle growth.\n"
                "Across studies, untrained participants grew more, while those with training experience gained more "
                "from doing more sessions. Evidence on how much more volume trained lifters need is limited.",
                "supported", "each finding with its own population"),
    SummaryCase("study intake as a target", ("refalo_nutrition",), "How much protein do I need per day to build muscle?",
                "For most lifters aiming to gain: about 2.3 to 2.5 grams of protein per kilogram of body weight each "
                "day.\nCount grams per kilogram over the whole day; in trained lifters here, average protein intakes "
                "were 2.5 g/kg for men and 2.3 g/kg for women during successful hypertrophy training. These intakes "
                "supported muscle gain in the included trials; adjust up or down if you're smaller, larger, or "
                "struggling to hit calories. Evidence here reports what was used, not a single best target.",
                "rejected", "what one trial's participants ate, turned into a recommendation"),
    SummaryCase("faithful study intake", ("refalo_nutrition",), "How much protein do I need per day to build muscle?",
                "This research doesn't set a protein target.\nIn one trial, resistance-trained men averaged about 2.5 "
                "and women about 2.3 grams of protein per kilogram of body weight a day while training; that is what "
                "they ate, not a tested requirement.",
                "supported", "the intake reported as a study condition"),
    SummaryCase("advice on an uncovered topic", ("schoenfeld_strength_zone",), "Should I stretch before lifting?",
                "Yes, but keep it short and specific to your lifts.\nA brief warm-up and light dynamic stretching that "
                "matches the movement helps, and heavy loading is what drives strength, especially for 1RM. If long "
                "static stretching makes you feel sluggish, skip it before heavy sets. Evidence here focuses on "
                "loading and specificity, not stretching per se, so treat this as practical guidance.",
                "rejected", "the excerpt never mentions stretching or warm-ups"),
    # The order case was first written as an unsupported-advice trap; the
    # Refalo excerpt does tie exercise order to which muscle grows, so
    # order advice drawn from it is supported when labeled as that finding.
    SummaryCase("faithful order from a related finding", ("kassiano_variation", "refalo_fatigue"),
                "should I do this before or after my bench press?",
                "Do first the exercise for the muscle you most want to grow.\nIn one trial, an exercise done after "
                "another taken to failure grew its target muscle less, so order within a session can shift which "
                "muscle benefits. That was shown for the quadriceps, not these exercises, so treat it as a guide.",
                "supported", "Refalo ties order to muscle-specific growth; population and exercises labeled"),
    SummaryCase("faithful range with a general hedge", _VOLUME, CHAT_QUESTION,
                "For most lifters: roughly 5 to 18 fractional sets per muscle per week.\nFractional sets count each "
                "set where the muscle is the main mover as 1 and each set where it only assists as a half. Growth "
                "rises with weekly sets but each extra set adds less. Start in that range and adjust based on your "
                "recovery and progress; the research shows a range, not one best number.",
                "supported", "a general 'adjust by recovery' hedge needs no excerpt"),
    # How a study was run (session length, per-meal dose, rest, frequency)
    # turned into advice: the first two are from live answers (Oct 20, 2026)
    # that told users how long a workout should take and how much protein
    # to eat per meal. Each trap has a faithful twin from the same excerpts.
    SummaryCase("study session length as a target", ("hermann_conclusion", "hermann_methods"),
                "How long should a workout take?",
                "For most lifters: keep each workout to about 30 minutes. Research on trained lifters shows "
                "30-minute total-body sessions twice a week produce appreciable gains, so longer sessions aren't "
                "needed.", "rejected", "30 minutes was the trial's session length, not a finding about duration"),
    SummaryCase("faithful study session length", ("hermann_conclusion", "hermann_methods"),
                "How long should a workout take?",
                "The research here doesn't set an ideal workout length. In one trial, trained lifters made "
                "appreciable gains with just two 30-minute total-body sessions a week, so long sessions aren't "
                "required to make progress.", "supported", "the session length reported as what one trial did"),
    SummaryCase("per-meal dose as a finding", ("morton_limitations_conclusion",),
                "How much protein should I eat per meal?",
                "Eat about 0.25 g of protein per kg of body weight at each meal: the meta-analysis found that "
                "the dose per meal, more than the daily total, drives muscle gains.", "rejected",
                "Morton found the post-exercise dose didn't matter and the daily total did; 0.25 g/kg is a cited "
                "suggestion"),
    SummaryCase("faithful per-meal dose", ("morton_limitations_conclusion",),
                "How much protein should I eat per meal?",
                "The daily total matters more than the per-meal amount: about 1.6 g per kg of body weight a day. "
                "The meta-analysis authors suggest splitting it into roughly 0.25 g/kg doses, but the protein dose "
                "after training didn't change gains in their analysis.", "supported",
                "the dose kept as the authors' suggestion, with the finding that dose details mattered little"),
    SummaryCase("study rest period as a target", ("schoenfeld2019_methods",),
                "How long should I rest between sets?",
                "Rest about 90 seconds between sets for the best muscle growth.", "rejected",
                "90 s was the rest every group used; the trial compared set volumes, not rest periods"),
    SummaryCase("faithful study rest period", ("schoenfeld2019_methods",),
                "How long should I rest between sets?",
                "This trial doesn't show what rest is best: every group rested 90 seconds between sets, because it "
                "compared numbers of sets, not rest periods.", "supported", "the rest period reported as a condition"),
    SummaryCase("study frequency as a target", ("bazvalle_conclusions",),
                "How many times a week should I train each muscle?",
                "Train each muscle twice a week: a review of trained men found 12 to 20 weekly sets works best when "
                "each muscle is trained twice per week.", "rejected",
                "twice a week was the condition of the studies reviewed; the review didn't compare frequencies"),
    SummaryCase("faithful study frequency", ("bazvalle_conclusions",),
                "How many times a week should I train each muscle?",
                "This review doesn't compare training frequencies. It recommends 12 to 20 weekly sets for quadriceps "
                "and biceps in young trained men, based on programs that trained each muscle twice a week, and "
                "notes that training more often could allow more volume.", "supported",
                "the frequency kept as the condition, with the review's own suggestion"),
]


def _evidence(key: str) -> str:
    # As chat passes excerpts to the judge: labeled with the paper's tags.
    excerpt = EXCERPTS[key]
    try:
        tags = paper(excerpt["source"]).payload()
    except KeyError:
        tags = {"source": excerpt["source"]}
    return evidence_text({**tags, "text": excerpt["text"]})


# (muscle, goal, preference): the value must land in its goal and
# preference's band (VOLUME_BANDS) and verify.
GENERATION_CASES = [
    (muscle, "hypertrophy", preference)
    for muscle in ("chest", "quadriceps")
    for preference in ("minimal", "moderate", "high")
] + [("chest", "strength", preference) for preference in ("minimal", "moderate", "high")]


def _run_judge_case(case: JudgeCase) -> tuple[bool, str]:
    # Read at call time, so --generation-judge and --statement-judge (which
    # swap them module-wide) apply here too. Statements are prose, judged
    # detail by detail as the app judges them.
    statement = case.judge == "statement"
    judge = verification.STATEMENT_JUDGE if statement else verification.GENERATION_JUDGE
    start = time.perf_counter()
    try:
        verdict = judge_citation(case.question, case.answer, EXCERPTS[case.excerpt]["text"], judge=judge,
                                 prose=statement)
    except Exception as e:  # an error is a failed run, not a crash of the whole check
        return False, f"error: {type(e).__name__}"
    detail = f"{verdict.outcome} {time.perf_counter() - start:.1f}s"
    if case.expect == "not_direct":
        return verdict.outcome != "primary_support", detail
    supported = verdict.outcome in SUPPORTED
    return supported == (case.expect == "supported"), detail


def _run_summary_case(case: SummaryCase) -> tuple[bool, str]:
    start = time.perf_counter()
    try:
        verdict = verification.judge_summary(case.question, case.summary, [_evidence(k) for k in case.excerpts])
    except Exception as e:
        return False, f"error: {type(e).__name__}"
    supported = verdict.outcome == "supported"
    return supported == (case.expect == "supported"), f"{verdict.outcome} {time.perf_counter() - start:.1f}s"


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


def _check_volume_answer(response) -> tuple[bool, str]:
    answer = response.answer
    merged = re.search(r"\b18\s*(?:-|–|to)\s*31\b", answer)
    # every sentence that mentions 31 sets must keep 'fractional'
    bare_31 = [s for s in re.split(r"(?<=[.!?])\s+", answer) if re.search(r"\b31\b", s) and "fractional" not in s]
    ok = not merged and not bare_31
    return ok, "ok" if ok else ("merged 18-31 range" if merged else "31 without 'fractional'")


def _check_theory_answer(response) -> tuple[bool, str]:
    cited = any("Schoenfeld et al. 2021" in c.title for c in response.citations)
    return cited, "cites Schoenfeld 2021" if cited else "Schoenfeld 2021 not cited"


# (question, check of the response)
CHAT_CASES = [(CHAT_QUESTION, _check_volume_answer), (THEORY_QUESTION, _check_theory_answer)]


def _run_chat_case(case) -> tuple[bool, str]:
    from app.routers.chat import _handle_general_question

    question, check = case
    try:
        response = _handle_general_question(SimpleNamespace(topic=question), question)
    except Exception as e:
        return False, f"error: {type(e).__name__}"
    return check(response)


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
        "--statement-judge", metavar="MODEL[:EFFORT]",
        help="try a different judge for prose statements, e.g. gpt-5:minimal (default: the app's)",
    )
    parser.add_argument(
        "--summary-judge", metavar="MODEL[:EFFORT]",
        help="try a different judge for chat's lead summary, e.g. gpt-5:minimal (default: the app's)",
    )
    parser.add_argument(
        "--judge-cases", choices=("all", "statement", "generation", "summary"), default="all",
        help="which judge cases to run (generation = bare generated values; summary = chat's lead summary)",
    )
    parser.add_argument(
        "--only", metavar="TEXT[,TEXT...]",
        help="run only judge and summary cases whose name contains one of these, e.g. 'study,per-meal'",
    )
    args = parser.parse_args()
    picked = lambda cases: [c for c in cases if not args.only or any(t in c.name for t in args.only.split(","))]
    if args.generation_judge:
        model, _, effort = args.generation_judge.partition(":")
        verification.GENERATION_JUDGE = Judge(model, effort or None)
    if args.statement_judge:
        model, _, effort = args.statement_judge.partition(":")
        verification.STATEMENT_JUDGE = Judge(model, effort or None)
    if args.summary_judge:
        model, _, effort = args.summary_judge.partition(":")
        verification.SUMMARY_JUDGE = Judge(model, effort or None)

    describe_judge = lambda c: f"{c.name} -> expect {c.expect} ({c.judge} judge): {c.why}"
    describe_summary = lambda c: f"{c.name} -> expect {c.expect}: {c.why}"
    describe_gen = lambda c: f"weekly volume {c[0]} / {c[1]} / {c[2]}" + (
        f" -> in {VOLUME_BANDS[c[1]][c[2]]} and verified")
    if args.list:
        for case in JUDGE_CASES:
            print("judge      ", describe_judge(case))
        for case in SUMMARY_CASES:
            print("summary    ", describe_summary(case))
        for case in GENERATION_CASES:
            print("generation ", describe_gen(case))
        print("chat        no merged 18-31 range; 31 always with 'fractional' (--chat)")
        print(f"chat        {THEORY_QUESTION!r} cites Schoenfeld 2021 (--chat)")
        return 0

    logging.disable(logging.INFO)
    print(f"judges: statement={verification.STATEMENT_JUDGE}, generation={verification.GENERATION_JUDGE}, "
          f"summary={verification.SUMMARY_JUDGE}; {args.repeats} runs per case")
    ok = True
    judge_cases = picked([c for c in JUDGE_CASES if args.judge_cases in ("all", c.judge)])
    if judge_cases:
        ok &= _report("JUDGE CASES", judge_cases, _run_judge_case, args.repeats, describe_judge)
    summary_cases = picked(SUMMARY_CASES)
    if args.judge_cases in ("all", "summary") and summary_cases:
        ok &= _report("SUMMARY CASES", summary_cases, _run_summary_case, args.repeats, describe_summary)
    if not args.judge_only:
        ok &= _report("GENERATION CASES", GENERATION_CASES, _run_generation_case, args.repeats, describe_gen)
    if args.chat:
        ok &= _report("CHAT CASES", CHAT_CASES, _run_chat_case, args.repeats, lambda c: f"chat: {c[0]}")
    print("\nALL PASS" if ok else "\nSOME CASES DID NOT PASS - see FAIL/FLAKY above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
