from typing import Literal, NamedTuple

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

from .excerpt_kinds import KIND_DEFINITIONS, ExcerptKind

load_dotenv()

# Judge calls run in parallel (a chat answer's statements, a block's
# fields), so rate-limit errors are expected under load - retried with
# backoff rather than surfacing as 'unresolved' citations.
client = OpenAI(max_retries=6)

class JudgeVerdict(pydantic.BaseModel):
    # Fields are generated in order, so the judge says what the excerpt
    # claims and what kind of statement it is BEFORE deciding: matching
    # '8-12' in a passage that only describes a theory was the failure this
    # guards against. Not stored or shown - a working note for the verdict.
    asserts: str
    kind: ExcerptKind
    outcome: Literal["primary_support", "contextual_support", "contradicted"]


class DetailCheck(pydantic.BaseModel):
    detail: str
    excerpt_says: str
    matches: bool


class StatementVerdict(pydantic.BaseModel):
    # For prose (chat statements, rule claims, citation summaries): every
    # specific detail is set beside the excerpt before the verdict. A chat
    # statement put Aube 2022's 8-week study in 'highly trained males' 'over
    # 9 weeks' (the paper: 'resistance-trained individuals') and was accepted
    # as direct support - the gist matched, the details were never compared.
    asserts: str
    kind: ExcerptKind
    details: list[DetailCheck]
    outcome: Literal["primary_support", "contextual_support", "contradicted"]


# Bare values only. Production rejected '8-12' reps for hypertrophy in 4 of 4
# attempts (Oct 19, 2026), reading 'similar growth across loads, no ideal
# zone' as contradicting any recommended range. In the shared prompt, the
# same wording let a chat statement's 'upper limit' through (hedged ceiling
# 5/5 -> 2/5), so prose keeps the qualifier rules unchanged.
_SIMILAR_SPAN_INSTRUCTIONS = """

The answer here is a bare value. A finding of similar outcomes across \
options supports it like an effective range does: when the excerpt reports \
that a span of loads or repetition ranges produced similar results for the \
question's outcome, a value inside the span it compared is one of those \
effective options - primary_support if the excerpt names a range containing \
it (8-12 where '8-12RM and 20-25RM produced similar growth'), \
contextual_support if it states the span only in other terms (8-12 reps \
where 'heavy and light loads were equally effective'). A finding that no \
single option is best ('no ideal zone', 'similar across loads') never \
contradicts a bare value inside its span, since a bare value claims no \
optimum. A value outside the span the excerpt compared is not supported by \
it."""


_DETAILS_INSTRUCTIONS = """

The answer here is prose, so before the `outcome`, list in `details` every \
specific detail it states: each number or range with its unit, study length, \
who was studied (training status, sex, age), the outcome (hypertrophy or \
strength), the muscle or exercise, named studies, and how strong the claim is \
(its wording, e.g. 'optimal', 'an upper limit', 'may', 'similar', 'no \
detectable superiority'). For each, write what \
the excerpt or its Source label says about it (`excerpt_says`), or 'not \
stated', and whether they match (`matches`). A detail matches only if the \
excerpt states the same thing: a narrower or different group than the excerpt \
names ('men' where it says 'individuals', 'trained' where it says 'mixed'), \
a different number, or a stronger claim ('an upper limit' or 'optimal' where \
it says 'no detectable superiority beyond X'; 'better' where it says \
'similar') does not match. A detail that conflicts with the excerpt, \
or that neither the excerpt nor its Source label states, makes the answer \
contradicted - however well the rest matches."""


_JUDGE_SYSTEM_PROMPT = f"""You are verifying whether a specific research excerpt \
supports a specific generated answer. You will be given a question, a generated \
answer (a number, a range, or a specific category/recommendation), and one \
excerpt that was cited as a source for that answer.

First, write `asserts`: what the excerpt itself \
claims, in one or two sentences, saying whose claim it is (this paper's \
result, an earlier study's result, or a view it describes). Then choose its \
`kind`:

{KIND_DEFINITIONS}

Then classify the relationship as `outcome`, exactly one of:

- primary_support: the excerpt's own stated content directly and substantially \
accounts for the generated answer - it states the same value/range, or makes \
the same categorical recommendation.
- contextual_support: the excerpt does not itself state or recommend the \
answer, but it reports FINDINGS on related factors (population, training \
experience, fatigue/recovery, how volume is counted, or similar) that could \
reasonably explain how the answer was informed or adjusted using this \
excerpt alongside other sources - a legitimate contributing influence, not \
the literal source of the claim. Introductions, background, study aims, \
methods descriptions, titles and abstracts' author lists that report no \
results of their own are not support of any kind - classify them as \
contradicted, however closely their topic matches.
- contradicted: the excerpt bears no real relationship to the answer at \
all - a different exercise, a different population, an unrelated claim, or \
a different recommendation than the one given (e.g. the excerpt recommends \
the opposite category). This also includes reference-list excerpts: text \
made up of numbered citation entries (author names, a paper title, a \
journal name, a year, a DOI - repeated for multiple entries in a list, \
often looking like "42. Smith J, Lee K. Some Paper Title. J Something. \
(2020) 12:34-56. doi: 10.xxxx/..."). A block of citation entries is a \
bibliography, not a discussion, NO MATTER how many entries it has or how \
closely individual entry TITLES echo the topic - listing that other papers \
exist on a topic is not the same as discussing what they found. If the \
excerpt is structurally a reference list (look for the repeated \
author/title/journal/year/DOI pattern), classify it as contradicted even \
if it takes up the whole excerpt and even if several entry titles look \
highly relevant.

Tell a reported finding from a reported belief. An excerpt that describes a \
theory, model, hypothesis, convention or common recommendation - what a view \
'proposes', 'postulates' or holds, what is 'typically prescribed', \
'traditionally recommended' or 'commonly accepted', or what an author \
'proposed' - reports that the view exists, not evidence that it is true. It \
supports nothing but an answer that itself presents it as that view (e.g. \
'the traditional repetition continuum holds that 8-12 reps per set optimizes \
hypertrophy'). An answer stating the view's claim as a fact, a finding or a \
recommended value is contradicted, even when the excerpt states its exact \
value (e.g. 'the repetition continuum proposes that 8-12 repetitions \
optimizes hypertrophy' does not support 8-12 reps). Papers often lay out \
such a view only to re-examine or challenge it. A result the excerpt reports \
from a cited study - what that study measured, found or reported - is a \
finding, and is judged like any other.

The answer must also keep the excerpt's qualifiers. Classify as contradicted \
if the answer states something the excerpt doesn't because it changed any of: \
the unit of measure (e.g. 'fractional' sets presented as direct or total \
sets; sets per session presented as sets per week, or the reverse); the \
outcome (e.g. a strength finding presented as a hypertrophy finding); the \
population, training status or muscle studied, when the answer generalizes \
it as if it applied broadly; or the strength of the finding (e.g. 'no \
detectable superiority beyond X', 'a trend toward' or 'similar results' \
presented as an optimum, a proven benefit, or 'no benefit beyond X'). \
'No detectable superiority beyond X' means the data couldn't show an \
advantage past X - interpreting it as a limit, ceiling, maximum or point of \
no further benefit changes the finding, even when hedged with 'may be', \
'suggests' or 'indicating'. Likewise 'similar outcomes across A-B' means no \
option in that range was shown better - calling part of it optimal or best \
changes the finding. Also classify as contradicted if the answer merges a \
figure from this excerpt with figures the excerpt doesn't contain into a new \
range or number, or if a number or range in the answer differs from the one \
the excerpt reports for that same outcome (e.g. the answer says 18-24 sets \
where the excerpt says 12-24) - check every figure in the answer against the \
excerpt before deciding. A bare \
number or short value (e.g. '12', '8-12', '1-2 RIR') with no stated unit or \
outcome of its own hasn't changed a qualifier - judge it on whether the \
excerpt supports that value for the question asked.

A bare generated value is a point chosen from what the research supports, \
not a claim that it is the single best value - dosing research usually \
reports ranges, tiers or dose-response findings rather than one optimum. \
Classify it as primary_support when the excerpt reports, for the question's \
outcome, a range or tier the value falls inside as an effective dose (e.g. \
18 inside an excerpt's '11-18 weekly sets' tier, or 12 inside '12-20 sets', \
or inside '12-24 sets produced similar growth'). A 'no detectable \
superiority beyond X' point marks where the data stopped showing \
differences, not a recommended dose: a value equal to or near X is NOT \
supported by that finding - classify it contradicted unless the excerpt \
also reports X inside a range it presents as effective. A value that only \
sits below such a point, or near a single figure the excerpt doesn't present \
as an effective range, is at most contextual_support. A figure for a different outcome (a strength result for \
a hypertrophy question) or a different unit (sets per session for a weekly \
value) never supports it."""


class Judge(NamedTuple):
    model: str
    reasoning_effort: str | None = None  # None = the model's default


# Judges, chosen by comparing models on known misrepresentations (fractional
# sets read as total sets, 'no detectable superiority beyond X' read as a
# ceiling, 12-24 narrowed to 18-24): gpt-4o-mini accepted every one, gpt-5
# caught all of them. Chat statements and rule claims are prose with
# qualifiers to keep (see STATEMENT_JUDGE for why low effort is enough
# there). Generated values are bare numbers
# checked in bulk, so they get minimal reasoning (~2s per check); its one
# miss was a hedged prose overstatement, which a bare value can't contain.
# gpt-4.1 scored the same but this account's 30k tokens/min limit on it
# throttles a block's checks; gpt-5's limit is 500k.
# Low, not minimal, effort: on weekly volume, minimal gave inconsistent
# verdicts (the same value in the same reported tier accepted once and
# rejected once) and read a 'no detectable superiority' point as an optimum.
GENERATION_JUDGE = Judge("gpt-5", reasoning_effort="low")
# Changing a judge or its prompt? Run scripts/eval_judge.py first, and bump
# shared_answers.ANSWER_VERSION so stored answers are re-judged.
# Minimal effort, judging prose with StatementVerdict's details list (prose=
# True), since Oct 15, 2026. Measured on the 15 statement cases, 5 runs each
# (scripts/eval_judge.py --judge-cases statement):
#   low, no details list:     hedged ceiling 4/5, wrong study length 1/5,
#                             population not stated 0/5; 4.8s, $0.0048 a check
#   minimal + details list:   5/5, 4/5, 0/5; 4.5s, $0.0047 a check
#   low + details list:       5/5, 5/5, 5/5; 19.3s, $0.0090 a check
# All other cases passed 5/5 in each. Minimal + the list is at least as
# accurate as low without it on every case, at the same speed and cost; low
# + the list closes every case but is ~4x slower per check (~25s more per
# chat answer). Open: 'men' read as matching 'individuals' (the writer is
# told to use the excerpt's own words for who was studied). Before this:
# low, not default (medium), effort - 76/76 on the trap cases vs medium's
# 'hedged ceiling' 1-in-3 miss, median 4.0s vs 9.0s.
# Not measured: the citation-summary check (citation_summaries.py) - the
# eval has no case for it.
STATEMENT_JUDGE = Judge("gpt-5", reasoning_effort="minimal")
# Chat's lead summary, judged against all of its excerpts at once - at low
# effort the slowest check in an answer (11.4s of a 24.6s answer, Oct 15,
# 2026), which set how long judging took. Minimal effort since Oct 15, 2026,
# measured on the 14 summary cases (scripts/eval_judge.py --judge-cases
# summary, 5 runs each). With the old (outcome, reasoning) verdict, minimal
# and low both passed 13/14, failing the same case - fractional-set tiers
# relabeled as 'total' sets, which even default effort caught only 1 time
# in 5. With SummaryVerdict listing each figure's unit first: 14/14 at
# minimal (~1-4s per check) and at low (~2-20s - the figure list costs low
# effort far more reasoning time).
SUMMARY_JUDGE = Judge("gpt-5", reasoning_effort="minimal")


def judge_citation(
    query: str, value: int | str, chunk_text: str, judge: Judge | None = None, prose: bool = False,
) -> JudgeVerdict | StatementVerdict:
    """`prose`: the answer is a sentence (chat statement, rule claim,
    citation summary), so its details are checked one by one
    (StatementVerdict). Generated values are bare numbers and keep
    JudgeVerdict."""
    judge = judge or GENERATION_JUDGE  # looked up per call, so it can be swapped (scripts/eval_judge.py)
    # gpt-5 is a reasoning model, which rejects a temperature setting
    options = {"reasoning_effort": judge.reasoning_effort} if judge.reasoning_effort else {}
    # Each kind's instructions go after the shared prompt, so both kinds of
    # call keep the same cacheable prefix.
    system = _JUDGE_SYSTEM_PROMPT + (_DETAILS_INSTRUCTIONS if prose else _SIMILAR_SPAN_INSTRUCTIONS)
    completion = client.chat.completions.parse(
        model=judge.model,
        **options,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Question: {query}\nGenerated answer: {value}\n\n"
                f"Cited excerpt:\n{chunk_text}",
            },
        ],
        response_format=StatementVerdict if prose else JudgeVerdict,
    )
    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Judge refused to classify: {message.refusal}")
    return message.parsed


class FigureCheck(pydantic.BaseModel):
    figure: str
    unit_in_summary: str
    unit_in_excerpts: str
    # Named before same_unit: an open conversion ('5-18 fractional sets,
    # which is 5-18 total chest sets') was listed as a figure of its own,
    # 'not reported' in the excerpts, and failed - 5/10 on the conversion
    # cases (Oct 19, 2026), and a quads answer lost all three summaries.
    converted_from: str
    same_unit: bool


class SummaryVerdict(pydantic.BaseModel):
    # Each figure's unit is set beside the excerpts' before the verdict
    # (fields are generated in order): the judge noted Pelland's tiers were
    # 'fractional weekly sets' yet accepted them relabeled as 'total sets' -
    # it matched the numbers and never compared the units.
    figures: list[FigureCheck]
    # Set before the verdict for the same reason: every claim in a blood
    # flow restriction answer was true of its low-load-training excerpts,
    # and the summary was accepted without ever naming the technique asked
    # about.
    answers_the_question: bool
    outcome: Literal["supported", "contradicted"]


_SUMMARY_JUDGE_SYSTEM_PROMPT = """You are verifying a short summary answer that \
synthesizes several research excerpts into practical advice. You will be given \
the question, the summary, and every excerpt it cites. Judge the excerpts \
TOGETHER: the summary doesn't need any one excerpt to state it, but it must be \
a fair consensus of what they show.

- supported: everything the summary claims is covered by the excerpts taken \
together. Approximate or rounded figures and hedges ('roughly', 'most \
studies', 'for most lifters') are fine when the findings cover them - e.g. \
excerpts showing growth rising with weekly sets with diminishing returns, \
plus similar growth across a range of weekly sets, support a hedged rough \
range with 'smaller gains above it'.
- contradicted: the summary claims something no combination of the excerpts \
supports. That includes a range or number the findings don't cover; calling \
a sub-range optimal or best when the excerpts found similar outcomes across \
it; treating 'no detectable superiority beyond X' as a ceiling, a maximum or \
proof of no further benefit; mixing units (e.g. 'fractional' sets presented \
as direct or total sets, per-session as weekly - fractional, direct and total \
sets are three different counts, so a figure stated in one is not supported \
by an excerpt that reports it in another) or outcomes (a strength finding \
presented as hypertrophy); presenting a finding from one population as \
general without saying so; hiding a real disagreement between the excerpts; \
or sounding more certain than the evidence (e.g. 'proven', 'always').

The summary must also answer the question that was asked, from excerpts \
about what the question is about. Findings on a different intervention, \
technique or topic don't answer it, however accurately they are reported - \
e.g. light-load training to failure is not blood flow restriction training, \
and heavy-load strength findings say nothing about wearing a lifting belt. \
Set `answers_the_question` false if the summary answers a nearby question \
instead, or if no excerpt it cites is about what the question asks; then the \
summary is contradicted.

Before deciding, list in `figures` every number or range the summary states. \
For each, write its unit exactly as the summary words it (`unit_in_summary`, \
e.g. 'total sets per muscle per week'), the unit the excerpts report that \
figure in (`unit_in_excerpts`, e.g. 'fractional weekly sets', or 'not \
reported' if no excerpt gives it), the figure it is converted from \
(`converted_from`, see below; 'none' if it isn't a conversion), and whether \
the two are the same count (`same_unit`). A summary that leaves the unit unstated takes the excerpts' \
unit; a summary that names a different one ('total' or 'direct' for \
fractional, per session for per week) does not. Any figure with same_unit \
false makes the summary contradicted.

Conversions between set counts are allowed when done openly. Fixed facts you \
may rely on even if no excerpt states them: fractional sets = direct sets + \
half of indirect sets (sets where the muscle only assists), and total sets = \
direct + indirect sets, so total sets = fractional sets + half the indirect \
sets; total, fractional and direct counts are equal when all of a muscle's \
work is direct. In the research's classification, chest, quadriceps and \
hamstrings get almost only direct sets, while triceps get indirect sets from \
presses, biceps from rows and pulldowns, and front delts from presses. A \
converted figure is fine - list it with same_unit true - only if the summary \
also gives the source figure in its own unit and says how it converts (e.g. \
'5-18 fractional sets, which is 5-18 total sets for chest, since presses and \
flyes are direct'), and the conversion follows from these facts. For such a \
figure, set `converted_from` to the source figure and its unit as the \
summary states them (e.g. '5-18 fractional sets'; for a worked example such \
as '10 fractional sets could be 6 pushdowns plus 8 bench sets, which is 14 \
total sets', the 14 is converted from '10 fractional sets'): the excerpts won't report \
the converted figure, so judge it by its source and the conversion, not by \
'not reported'. For chest, quadriceps or hamstrings the three counts are \
the same number, so a total or direct set count for that muscle has \
same_unit true wherever the excerpts' fractional figures cover it, even if \
the summary never spells out the conversion (e.g. '10 total quad sets' \
within '5-18 fractional sets'); a different number for the same range \
(5-18 fractional as 11-18 total, or halved) is still wrong. A figure stated \
in another unit without its source figure and conversion, or converted \
wrongly (e.g. halving a fractional count), has same_unit false. \
Then set `answers_the_question`, then give the `outcome`."""


def judge_summary(question: str, summary: str, excerpts: list[str], judge: Judge | None = None) -> SummaryVerdict:
    judge = judge or SUMMARY_JUDGE  # looked up per call, so it can be swapped (scripts/eval_judge.py)
    options = {"reasoning_effort": judge.reasoning_effort} if judge.reasoning_effort else {}
    numbered = "\n\n".join(f"Excerpt {i}:\n{text}" for i, text in enumerate(excerpts, start=1))
    completion = client.chat.completions.parse(
        model=judge.model,
        **options,
        messages=[
            {"role": "system", "content": _SUMMARY_JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\nSummary: {summary}\n\n{numbered}"},
        ],
        response_format=SummaryVerdict,
    )
    verdict = completion.choices[0].message.parsed
    if verdict is None:
        raise ValueError(f"Summary judge refused to classify: {completion.choices[0].message.refusal}")
    return verdict


def check_summary(
    question: str, summary: str, excerpts: list[str], judge: Judge | None = None,
) -> SummaryVerdict | None:
    """The summary judge's verdict - with the figures it compared, so a
    rejected summary's rewrite can be told what to fix - or None if no
    verdict could be had (which counts as not verified)."""
    if not excerpts:
        return None
    try:
        return judge_summary(question, summary, excerpts, judge)
    except Exception:
        return None


def verify_summary(question: str, summary: str, excerpts: list[str], judge: Judge | None = None) -> bool:
    """Whether a cross-source summary is a fair consensus of its cited
    excerpts. Any failure to get a verdict counts as not verified."""
    verdict = check_summary(question, summary, excerpts, judge)
    return verdict is not None and verdict.outcome == "supported"


def verify_citation(
    query: str, value: int | str, chunk_text: str, judge: Judge | None = None, prose: bool = False,
) -> str:
    # Every citation goes to the judge. An accept-only range check used to
    # approve a value without it whenever the excerpt contained a sets range
    # covering the value - which skips every qualifier check: it approved 18
    # weekly quad sets for hypertrophy from Aube 2022's '12-24 sets similar'
    # while the judge rejected the citation, since Aube's 18 is a strength
    # (squat 1RM) finding. Removed Oct 4, 2026.
    try:
        return judge_citation(query, value, chunk_text, judge=judge, prose=prose).outcome
    except Exception:
        return "unresolved"
