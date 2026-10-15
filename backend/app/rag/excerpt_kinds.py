# What kind of statement an excerpt makes - a result the paper reports, a
# result it cites, a theory it describes, its methods - read once per chunk
# at ingestion and stored on the chunk in Qdrant (`kind`). It's a property
# of the excerpt, not of any question asked of it, so it isn't re-derived on
# every judge call. Value generation only retrieves excerpts that report a
# result; chat retrieves everything and shows the kind to the writer and the
# judge, since a question ABOUT a theory needs the excerpt describing it.
# See notes/design_choices/excerpt_kinds.txt.
#
# Changing the prompt or model? Re-run scripts/eval_excerpt_kinds.py, then
# re-label the corpus (scripts/label_excerpt_kinds.py --relabel).
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import pydantic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(max_retries=6)

ExcerptKind = Literal["own_finding", "cited_finding", "described_view", "methods", "bibliography", "other"]

# Kinds that report no result: never evidence for a generated value.
NON_FINDING_KINDS = ("described_view", "methods", "bibliography", "other")

# How a non-finding kind is introduced to the models that read excerpts
# (reranker, writers, judge) - never to users.
KIND_NOTES = {
    "described_view": "describes a theory or convention, reports no result",
    "methods": "describes methods, reports no result",
}

KIND_DEFINITIONS = """\
- own_finding: reports a result of this paper's own data or analysis - what \
it measured, found, compared or concluded (a review's or meta-analysis's \
conclusions and recommendations drawn from the evidence it analysed count).
- cited_finding: reports what a specific earlier study measured or found - \
a result, an effect, a comparison - not merely that it 'supported' or \
'proposed' a view.
- described_view: describes a theory, model, hypothesis, convention or \
common recommendation - what a view proposes or holds, what is typically \
prescribed or commonly accepted, or a rationale - without reporting a result \
that tests it. Papers often lay out such a view in order to re-examine it.
- methods: describes the study's design, participants, protocol, measures or \
aims, with no results.
- bibliography: a reference list - numbered citation entries (authors, \
title, journal, year, DOI).
- other: anything else with no result (title page, author details, \
acknowledgements, funding)."""

_SYSTEM_PROMPT = f"""You classify research excerpts for a system that cites \
them as evidence. Given one excerpt from a paper, first write `asserts`: what \
the excerpt itself claims, in one or two sentences, saying whose claim it is \
(this paper's result, an earlier study's result, or a view it describes). \
Then choose its `kind`:

{KIND_DEFINITIONS}

An excerpt that reports ANY result - even one sentence among introduction or \
methods text - is own_finding or cited_finding, never one of the others: \
hiding a real result costs more than keeping a weak one. When it reports both \
its own and cited results, choose own_finding."""


class ExcerptReading(pydantic.BaseModel):
    asserts: str
    kind: ExcerptKind


# (model, reasoning effort). Chosen with scripts/eval_excerpt_kinds.py.
LABEL_MODEL = ("gpt-5-mini", "low")
# A non-finding label hides the excerpt from value generation, so it needs a
# second opinion from a stronger model; a finding label never does (keeping
# a weak excerpt costs a judge call, hiding a real result costs evidence).
# gpt-5-mini alone labeled Plotkin 2022's 'hypertrophy across five to 30+
# repetitions (Schoenfeld et al., 2017)' as methods. About a fifth of
# excerpts get the second call (confirm_kind).
CONFIRM_MODEL = ("gpt-5", "low")


def read_excerpt(label: str, text: str, model: tuple[str, str | None] = LABEL_MODEL) -> ExcerptReading:
    name, effort = model
    completion = client.chat.completions.parse(
        model=name,
        **({"reasoning_effort": effort} if effort else {}),
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Paper: {label}\n\nExcerpt:\n{text}"},
        ],
        response_format=ExcerptReading,
    )
    message = completion.choices[0].message
    if message.refusal or message.parsed is None:
        raise ValueError(f"Excerpt not classified: {message.refusal}")
    return message.parsed


_CONFIRM_PROMPT = """You check research excerpts for results before they are \
hidden from a system that cites results as evidence. Given one excerpt from a \
paper, find a sentence in it that reports a RESULT: what this study or an \
earlier cited study measured, found, compared or concluded (e.g. 'similar \
hypertrophy was achieved across 5 to 30+ repetitions (Smith et al., 2017)'). \
Look through the whole excerpt - a result is often one sentence in an \
introduction, a methods section or a caption. Not results: statistical or \
measurement methods, sample descriptions, hypotheses, study aims, what a \
theory or convention proposes, and a sentence saying only that research \
'supported' or 'provided support for' a view without saying what it found. \
Nor is a reference list: entries naming authors, a paper's title, a journal \
and a year - a title like 'Greater gains with higher volume' names a paper, \
it doesn't report a result. Quote the sentence in `result_sentence` and say \
whose result it is in `whose`, or set both to null if the excerpt reports no \
result."""


class _ResultCheck(pydantic.BaseModel):
    result_sentence: str | None
    whose: Literal["own", "cited"] | None


def confirm_kind(label: str, text: str, kind: str) -> str | None:
    """A first-pass label, settled: a finding stands; a non-finding stands
    only if CONFIRM_MODEL finds no sentence reporting a result. A second
    classification pass missed what the first did (Plotkin 2022's cited
    result, inside an introduction, called methods by both models), so the
    second opinion is a different task: quote a result, if there is one.
    None if the second opinion couldn't be had."""
    if kind not in NON_FINDING_KINDS:
        return kind
    name, effort = CONFIRM_MODEL
    try:
        completion = client.chat.completions.parse(
            model=name,
            **({"reasoning_effort": effort} if effort else {}),
            messages=[
                {"role": "system", "content": _CONFIRM_PROMPT},
                {"role": "user", "content": f"Paper: {label}\n\nExcerpt:\n{text}"},
            ],
            response_format=_ResultCheck,
        )
        check = completion.choices[0].message.parsed
    except Exception:
        return None
    if check is None:
        return None
    if check.result_sentence:
        return "cited_finding" if check.whose == "cited" else "own_finding"
    return kind


def label_kinds(excerpts: list[tuple[str, str]]) -> list[str | None]:
    """Kinds for (label, text) pairs, in parallel. None where no label could
    be had: an unlabeled excerpt is treated as a finding (kept in retrieval,
    still judged), the safe direction."""
    def one(excerpt):
        try:
            return confirm_kind(*excerpt, read_excerpt(*excerpt).kind)
        except Exception:
            return None

    if not excerpts:
        return []
    with ThreadPoolExecutor(max_workers=min(len(excerpts), 16)) as pool:
        return list(pool.map(one, excerpts))


def add_kinds(citation: str, payloads: list[dict]) -> None:
    """Sets `kind` on a paper's excerpt payloads before they're stored.
    Reference-list sections are bibliography by construction (no call);
    an excerpt that couldn't be labeled is stored without a kind."""
    body = [p for p in payloads if p.get("section") != "references"]
    for payload, kind in zip(body, label_kinds([(citation, p["text"]) for p in body])):
        if kind is not None:
            payload["kind"] = kind
    for payload in payloads:
        if payload.get("section") == "references":
            payload["kind"] = "bibliography"
