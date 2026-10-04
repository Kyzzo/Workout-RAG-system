from typing import Literal, NamedTuple

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Judge calls run in parallel (a chat answer's statements, a block's
# fields), so rate-limit errors are expected under load - retried with
# backoff rather than surfacing as 'unresolved' citations.
client = OpenAI(max_retries=6)

class JudgeVerdict(pydantic.BaseModel):
    outcome: Literal["primary_support", "contextual_support", "contradicted"]
    reasoning: str


_JUDGE_SYSTEM_PROMPT = """You are verifying whether a specific research excerpt \
supports a specific generated answer. You will be given a question, a generated \
answer (a number, a range, or a specific category/recommendation), and one \
excerpt that was cited as a source for that answer. Classify the relationship \
as exactly one of:

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
value) never supports it.

Give brief reasoning for your classification."""


class Judge(NamedTuple):
    model: str
    reasoning_effort: str | None = None  # None = the model's default


# Judges, chosen by comparing models on known misrepresentations (fractional
# sets read as total sets, 'no detectable superiority beyond X' read as a
# ceiling, 12-24 narrowed to 18-24): gpt-4o-mini accepted every one, gpt-5
# caught all of them. Chat statements and rule claims are prose with
# qualifiers to keep and are few per answer, so they get full reasoning
# (slower per check, run in parallel). Generated values are bare numbers
# checked in bulk, so they get minimal reasoning (~2s per check); its one
# miss was a hedged prose overstatement, which a bare value can't contain.
# gpt-4.1 scored the same but this account's 30k tokens/min limit on it
# throttles a block's checks; gpt-5's limit is 500k.
# Low, not minimal, effort: on weekly volume, minimal gave inconsistent
# verdicts (the same value in the same reported tier accepted once and
# rejected once) and read a 'no detectable superiority' point as an optimum.
GENERATION_JUDGE = Judge("gpt-5", reasoning_effort="low")
STATEMENT_JUDGE = Judge("gpt-5")


def judge_citation(query: str, value: int | str, chunk_text: str, judge: Judge = GENERATION_JUDGE) -> JudgeVerdict:
    # gpt-5 is a reasoning model, which rejects a temperature setting
    options = {"reasoning_effort": judge.reasoning_effort} if judge.reasoning_effort else {}
    completion = client.chat.completions.parse(
        model=judge.model,
        **options,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Question: {query}\nGenerated answer: {value}\n\n"
                f"Cited excerpt:\n{chunk_text}",
            },
        ],
        response_format=JudgeVerdict,
    )
    message = completion.choices[0].message
    if message.refusal:
        raise ValueError(f"Judge refused to classify: {message.refusal}")
    return message.parsed


class SummaryVerdict(pydantic.BaseModel):
    outcome: Literal["supported", "contradicted"]
    reasoning: str


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
as direct sets, per-session as weekly) or outcomes (a strength finding \
presented as hypertrophy); presenting a finding from one population as \
general without saying so; hiding a real disagreement between the excerpts; \
or sounding more certain than the evidence (e.g. 'proven', 'always').

Give brief reasoning for your classification."""


def verify_summary(question: str, summary: str, excerpts: list[str], judge: Judge = STATEMENT_JUDGE) -> bool:
    """Whether a cross-source summary is a fair consensus of its cited
    excerpts. Any failure to get a verdict counts as not verified."""
    if not excerpts:
        return False
    options = {"reasoning_effort": judge.reasoning_effort} if judge.reasoning_effort else {}
    numbered = "\n\n".join(f"Excerpt {i}:\n{text}" for i, text in enumerate(excerpts, start=1))
    try:
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
        return verdict is not None and verdict.outcome == "supported"
    except Exception:
        return False


def verify_citation(query: str, value: int | str, chunk_text: str, judge: Judge = GENERATION_JUDGE) -> str:
    # Every citation goes to the judge. An accept-only range check used to
    # approve a value without it whenever the excerpt contained a sets range
    # covering the value - which skips every qualifier check: it approved 18
    # weekly quad sets for hypertrophy from Aube 2022's '12-24 sets similar'
    # while the judge rejected the citation, since Aube's 18 is a strength
    # (squat 1RM) finding. Removed Oct 4, 2026.
    try:
        return judge_citation(query, value, chunk_text, judge=judge).outcome
    except Exception:
        return "unresolved"
