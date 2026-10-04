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
# Invalidation: the key includes ANSWER_VERSION - bump it whenever a
# generation or judge prompt, a model or a reasoning effort changes, and
# older answers stop being reachable. After ingesting papers, clear the
# table (scripts/clear_shared_answers.py, local and production) so answers
# are regenerated against the new corpus.
import threading
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .citations import get_or_create_citation

ANSWER_VERSION = "2026-10-04"


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


def shared_key(*parts) -> str:
    return "|".join([ANSWER_VERSION, *(str(p) for p in parts)])


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
