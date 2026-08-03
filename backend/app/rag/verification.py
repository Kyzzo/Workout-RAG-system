import re
from typing import Literal

import pydantic
from openai import OpenAI

client = OpenAI()

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
numeric answer, and one excerpt that was cited as a source for that answer. \
Classify the relationship as exactly one of:

- primary_support: the excerpt's own stated data (a range, a specific value) \
directly and substantially accounts for the generated answer.
- contextual_support: the excerpt does not directly state a range containing \
the answer, but it discusses related factors (population, training \
experience, fatigue/recovery considerations, progression logic, or similar) \
that could reasonably explain how the answer was adjusted using this \
excerpt alongside other sources - a legitimate contributing influence, not \
the literal numeric source.
- contradicted: the excerpt bears no real relationship to the answer at \
all - a different exercise, a different population, or an unrelated claim. \
This also includes excerpts that are merely bibliographic (author names, \
paper titles, journal citations, DOIs) with no actual discussion, finding, \
or reasoning in them - a topically-related paper TITLE in a reference list \
is not itself content that could have informed the answer, so classify \
these as contradicted even if the titles look relevant.

Give brief reasoning for your classification."""


def judge_citation(query: str, value: int, chunk_text: str) -> JudgeVerdict:
    completion = client.chat.completions.parse(
        model="gpt-4o-mini",
        temperature=0,
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


def verify_citation(query: str, value: int, chunk_text: str, grounding: str) -> str:
    # Mechanical fast-path-accept only fires on a full self-report - per
    # citation_verification.txt section 4 trigger (b), a "blended" or
    # "general_knowledge" self-report escalates to the judge even if the
    # raw numbers would otherwise pass, since the model's own admission
    # casts doubt on whether this citation is really the primary source.
    if grounding == "fully_grounded" and check_point_in_range(value, chunk_text):
        return "primary_support"
    try:
        return judge_citation(query, value, chunk_text).outcome
    except Exception:
        return "unresolved"
