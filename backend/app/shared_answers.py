# Verified research answers shared by every program that asks the same
# question. Reps, RIR and load are researched by movement type and goal,
# not per exercise; weekly volume, frequency and progression by goal, not
# per muscle or program (the meta-analyses pool muscles). So each distinct
# question is generated, judged and stored once, and later programs reuse
# the answer and its citations instead of paying for the same model calls
# again (~75% of a program's calls were reps/RIR asked per exercise, mostly
# returning the same value; per-muscle volume/frequency was most of the
# rest).
#
# Only VERIFIED answers are stored: an answer the judge couldn't support is
# regenerated on each request, so an unlucky draw never sticks for everyone.
#
# Invalidation: each key starts with its kind's version, and bumping one
# makes that kind's older answers unreachable:
# - FIELD_ANSWER_VERSION (field_key): generated values - reps, RIR,
#   frequency, weekly sets. Bump for a change to value generation, its
#   retrieval or the generation judge.
# - CHAT_ANSWER_VERSION (chat_key): chat's preset answers and the sources
#   panel's citation summaries. Bump for a change to the chat writer or
#   its statement or summary judges.
# One version used to cover both, so every chat-only change also discarded
# the 23 field answers (~$5 to regenerate) - three times on Oct 15-20.
# After ingesting papers, clear the table (scripts/clear_shared_answers.py,
# local and production) so answers are regenerated against the new corpus.
import threading
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .citations import get_or_create_citation

FIELD_ANSWER_VERSION = "2026-10-20b"  # b: generation judge accepts a bare value inside a similar-outcomes span
CHAT_ANSWER_VERSION = "2026-10-20d"  # d: advice check (c) reverted - it rejected half of first summaries, median answer 20s -> 35s


@dataclass
class GeneratedAnswer:
    """What a generation produced: its value, every judged chunk, and
    whether any of them supported it (after the usual one retry)."""

    value: int | str
    grounding: str
    supported: bool
    verified: list[tuple[dict, str]]  # (chunk, verification status)


@dataclass
class Answer:
    """An answer ready to apply: from the shared store or freshly generated.
    `citations` are (citation_id, verification_status) pairs."""

    value: str
    grounding: str
    supported: bool
    citations: list[tuple[int, str]]
    shared: bool


# One lock per key: a block's parallel requests for the same question wait
# for the first one instead of all generating it at once.
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks[key]


def _key(version: str, parts) -> str:
    return "|".join([version, *(str(p) for p in parts)])


def field_key(*parts) -> str:
    """A generated value's key (reps, RIR, frequency, weekly sets)."""
    return _key(FIELD_ANSWER_VERSION, parts)


def chat_key(*parts) -> str:
    """A chat preset answer's or citation summary's key."""
    return _key(CHAT_ANSWER_VERSION, parts)


def _find(db: Session, key: str) -> models.SharedAnswer | None:
    return db.query(models.SharedAnswer).filter(models.SharedAnswer.key == key).first()


def _from_record(record: models.SharedAnswer) -> Answer:
    return Answer(
        value=record.value,
        grounding="fully_grounded",
        supported=True,
        citations=[(c.citation_id, c.verification_status) for c in record.citations],
        shared=True,
    )


def get_or_generate(db: Session, key: str, field: str, generate) -> Answer:
    """The stored answer for `key`, or `generate()`'s (a GeneratedAnswer),
    storing it when verified. Commits the stored answer, the same as the
    field generators already commit per field."""
    record = _find(db, key)
    if record is not None:
        return _from_record(record)

    with _lock_for(key):
        record = _find(db, key)  # a parallel request may have just stored it
        if record is not None:
            return _from_record(record)

        generated = generate()
        citations = [(get_or_create_citation(db, chunk).id, status) for chunk, status in generated.verified]
        if generated.supported:
            db.add(models.SharedAnswer(
                key=key, field=field, value=str(generated.value),
                citations=[
                    models.SharedAnswerCitation(citation_id=cid, verification_status=status)
                    for cid, status in citations
                ],
            ))
            try:
                db.commit()
            except IntegrityError:
                # Another process stored the same key first - use theirs.
                db.rollback()
                record = _find(db, key)
                if record is not None:
                    return _from_record(record)
        return Answer(
            value=str(generated.value), grounding=generated.grounding,
            supported=generated.supported, citations=citations, shared=False,
        )
