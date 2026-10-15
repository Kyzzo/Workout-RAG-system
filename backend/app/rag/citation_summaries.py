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
from .verification import STATEMENT_JUDGE, verify_citation

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
