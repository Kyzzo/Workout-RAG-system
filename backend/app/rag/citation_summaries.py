# A sources panel leads with ONE plain-language answer covering all of its
# citations (checked_panel_summary), then lists the studies with their exact
# excerpts. A summary per excerpt (below) read as too much summary and came
# out full of statistics; the panel prompt forbids those.
#
# Plain-language summaries of cited excerpts, so the sources panel leads
# with what a study found rather than a raw chunk of PDF text (which read
# like a direct quote and was hard to follow). The excerpt itself is still
# one click away under the summary.
#
# A summary is a rephrasing, and rephrasing can misrepresent (dropping 'no
# significant', 'in trained men', or presenting the studies an introduction
# cites as this paper's finding), so each one is checked against its excerpt
# by the same judge as chat statements and kept only if the excerpt states
# it directly. Stored per citation in shared_answers (routers/citations.py):
# written and checked once, then reused by everyone.
#
# Changing the prompt, model or judge? Bump shared_answers.ANSWER_VERSION so
# stored summaries are rewritten.
import pydantic

from .generate import STATEMENT_ANSWER_MODEL, client
from .verification import STATEMENT_JUDGE, verify_citation, verify_summary

_SYSTEM_PROMPT = """You explain research excerpts to lifters with no science \
background. Given one excerpt from a paper, write what it reports in plain \
language: one or two short sentences, at most 45 words.

- Say what was found, not how the paper is written. Lead with the finding \
(e.g. 'More weekly sets led to more muscle growth, with smaller gains at \
higher volumes').
- Keep every qualifier the excerpt has: who was studied (e.g. trained men, \
older adults), which outcome (muscle growth vs strength), the units (sets per \
week vs per session, 'fractional' sets), and how strong the finding is \
('no significant difference', 'a trend', 'similar results'). Never upgrade a \
'no significant difference' to 'no difference' or a trend to a finding.
- Copy numbers and ranges exactly as the excerpt gives them. If a number is \
unreadable in the text, leave it out rather than guess.
- If the excerpt describes OTHER studies (an introduction or discussion \
citing earlier work), say so: 'Earlier studies cited here found...'. If it \
only describes methods or what was measured, say what was done, without \
inventing results.
- Plain words: 'muscle growth' not 'hypertrophy', 'strength (1-rep max)' not \
'1RM' alone, 'weekly sets' not 'volume' where that's what it means. No \
advice, no conclusions beyond the excerpt, and don't mention 'the excerpt'."""


class _Summary(pydantic.BaseModel):
    summary: str


def write_summary(label: str, excerpt: str) -> str:
    model, effort = STATEMENT_ANSWER_MODEL
    completion = client.chat.completions.parse(
        model=model,
        **({"reasoning_effort": effort} if effort else {}),
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Paper: {label}\n\nExcerpt:\n{excerpt}"},
        ],
        response_format=_Summary,
    )
    message = completion.choices[0].message
    if message.refusal or message.parsed is None:
        raise ValueError(f"Summary not written: {message.refusal}")
    return message.parsed.summary.strip()


_PANEL_PROMPT = """You explain to lifters with no science background why the \
research behind a value in their program supports it. Given the question and \
the excerpts behind the value (each labeled with its paper), write ONE answer \
to the question that draws on them together: one to three short sentences, \
under 60 words - shorter is better.

- Use only what the excerpts report. Lead with the finding that answers the \
question. Leave out an excerpt that doesn't bear on the question rather than \
stretching it to fit.
- Only call it a disagreement when the excerpts report conflicting findings \
on the same thing; different focus or emphasis is not a disagreement. When \
they do conflict, say so rather than hide it.
- No statistics: no effect sizes, confidence or credible intervals, p-values, \
percentages of change, or model terms (ES, SMD, CrI, SDES, PUOS). Say what was \
found in words ('similar growth', 'more strength', 'no clear difference'). \
Training numbers the lifter uses - sets, reps, loads like '70% of 1RM' - are \
fine.
- Keep every qualifier the excerpts have: who was studied, which outcome \
(muscle growth vs strength), units ('fractional' sets, per week vs per \
session), and how strong the finding is ('similar', 'no significant \
difference', 'a trend'). Never call something optimal or a limit unless an \
excerpt does.
- This app counts sets fractionally (a set where the muscle only assists \
counts as half), so whenever you state a number of sets - the program's or a \
study's - write 'fractional sets' if the excerpts count them that way, or the \
unit they do use. Never leave a set count's unit unstated.
- Plain words: 'muscle growth' not 'hypertrophy', 'strength (1-rep max)' not \
'1RM' alone. Don't name 'the excerpts' or number them, and don't give advice \
beyond what they support."""


class _PanelSummary(pydantic.BaseModel):
    summary: str


def write_panel_summary(question: str, excerpts: list[tuple[str, str]]) -> str:
    """One answer to `question` from (paper label, excerpt text) pairs."""
    model, effort = STATEMENT_ANSWER_MODEL
    numbered = "\n\n".join(f"Paper: {label}\n{text}" for label, text in excerpts)
    completion = client.chat.completions.parse(
        model=model,
        **({"reasoning_effort": effort} if effort else {}),
        messages=[
            {"role": "system", "content": _PANEL_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\n{numbered}"},
        ],
        response_format=_PanelSummary,
    )
    message = completion.choices[0].message
    if message.refusal or message.parsed is None:
        raise ValueError(f"Summary not written: {message.refusal}")
    return message.parsed.summary.strip()


def checked_panel_summary(question: str, excerpts: list[tuple[str, str]], attempts: int = 2) -> str | None:
    """A sources panel's one summary, kept only if the cross-source summary
    judge (SUMMARY_JUDGE, which checks every figure's unit) finds it a fair
    consensus of the excerpts taken together. Retried once; None if neither
    attempt passes."""
    evidence = [f"Source: {label}\n\n{text}" for label, text in excerpts]
    for _ in range(attempts):
        try:
            summary = write_panel_summary(question, excerpts)
        except Exception:
            continue
        if verify_summary(question, summary, evidence):
            return summary
    return None


_QUESTION = "In plain language, what does this excerpt report?"


def checked_summary(label: str, excerpt: str, attempts: int = 2) -> str | None:
    """A summary the judge found the excerpt states directly, or None.
    Retried once - the same bounded retry as every generation path."""
    evidence = f"Source: {label}\n\n{excerpt}"
    for _ in range(attempts):
        try:
            summary = write_summary(label, excerpt)
        except Exception:
            continue
        if verify_citation(_QUESTION, summary, evidence, judge=STATEMENT_JUDGE, prose=True) == "primary_support":
            return summary
    return None
