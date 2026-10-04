import re
from typing import Literal, NamedTuple

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Judge calls run in parallel (a chat answer's statements, a block's
# fields), so rate-limit errors are expected under load - retried with
# backoff rather than surfacing as 'unresolved' citations.
client = OpenAI(max_retries=6)

# Accept-only, per citation_verification.txt section 3: this check may only
# ever confirm a citation, never reject one. Anything not a single,
# unambiguous, confidently-extracted range containing the value falls
# through (returns False) to judge escalation, not "contradicted" -
# multiple candidate ranges in one chunk means the extractor can't tell
# which one actually applies, so it declines rather than guesses.
_RANGE_PATTERN = re.compile(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)")
_SETS_WINDOW = 30  # chars to look for "set"/"sets" around a candidate range


def _find_sets_ranges(text: str) -> list[tuple[int, int]]:
    ranges = []
    for m in _RANGE_PATTERN.finditer(text):
        low, high = int(m.group(1)), int(m.group(2))
        if low > high:
            continue  # e.g. citation page ranges like "578-82" aren't ascending, discard

        # A bare "(10-13)" is a common citation-reference-list pattern
        # (papers #10 through #13), not a dosing range - even though the
        # word "set" often appears nearby in the surrounding sentence
        # ("...RT set should be quantified... (10-13)."). If the match is
        # immediately wrapped in parentheses with nothing else inside,
        # require "set" to be INSIDE those same parens, not just nearby.
        if m.start() > 0 and text[m.start() - 1] == "(" and m.end() < len(text) and text[m.end()] == ")":
            continue

        after = text[m.end():m.end() + _SETS_WINDOW].lower()
        before = text[max(0, m.start() - _SETS_WINDOW):m.start()].lower()
        if "set" in after or "set" in before:
            ranges.append((low, high))
    return ranges


def check_point_in_range(value: int, chunk_text: str) -> bool:
    ranges = _find_sets_ranges(chunk_text)
    if len(ranges) != 1:
        return False
    low, high = ranges[0]
    return low <= value <= high


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
answer, but it discusses related factors (population, training experience, \
fatigue/recovery considerations, methodology, or similar) that could \
reasonably explain how the answer was informed or adjusted using this \
excerpt alongside other sources - a legitimate contributing influence, not \
the literal source of the claim.
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
GENERATION_JUDGE = Judge("gpt-5", reasoning_effort="minimal")
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


def verify_citation(
    query: str,
    value: int | str,
    chunk_text: str,
    grounding: str,
    use_mechanical_check: bool = True,
    judge: Judge = GENERATION_JUDGE,
) -> str:
    # Mechanical fast-path-accept only fires on a full self-report - per
    # citation_verification.txt section 4 trigger (b), a "blended" or
    # "general_knowledge" self-report escalates to the judge even if the
    # raw numbers would otherwise pass, since the model's own admission
    # casts doubt on whether this citation is really the primary source.
    #
    # use_mechanical_check=False for load specifically: it's stored as a
    # string ("70% 1RM" or an RPE value), and range-containment has no
    # reliable way to compare across those two unit systems - rather than
    # guess, load always escalates straight to the judge
    # (citation_verification.txt section 3).
    if (
        use_mechanical_check
        and grounding == "fully_grounded"
        and check_point_in_range(value, chunk_text)
    ):
        return "primary_support"
    try:
        return judge_citation(query, value, chunk_text, judge=judge).outcome
    except Exception:
        return "unresolved"
