import logging

from ..rag.generate import build_volume_query, generate_volume_sets
from ..rag.verification import verify_citation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/weekly-prescriptions", tags=["generation"])
logger = logging.getLogger("uvicorn")

_GENERAL_KNOWLEDGE_NOTE = (
    "This is a general estimate based on established training principles, "
    "not a specific study."
)
_UNSUBSTANTIATED_NOTE = "This value could not be substantiated by the current research corpus."
_SUPPORTED_STATUSES = ("primary_support", "contextual_support")


def _get_or_create_citation(db: Session, chunk: dict) -> models.Citation:
    citation = (
        db.query(models.Citation)
        .filter(models.Citation.qdrant_point_id == chunk["id"])
        .first()
    )
    if citation is None:
        citation = models.Citation(
            title=chunk["source"],
            snippet=chunk["text"],
            qdrant_point_id=chunk["id"],
        )
        db.add(citation)
        db.flush()  # populate citation.id before it's used as a FK below
    return citation


def _attempt_volume_generation(muscle_group: str, goal: str):
    result, chunks = generate_volume_sets(muscle_group, goal)
    query = build_volume_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}

    verified = []
    any_supported = False
    for chunk_id in result.chunk_ids:
        chunk = chunks_by_id[chunk_id]  # schema-constrained to this set, always present
        status = verify_citation(query, result.sets, chunk["text"], result.grounding)
        if status in _SUPPORTED_STATUSES:
            any_supported = True
        verified.append((chunk, status))
    return result, verified, any_supported


@router.post("/{prescription_id}/generate-volume", response_model=schemas.WeeklyPrescriptionOut)
def generate_volume(
    prescription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    prescription = (
        db.query(models.WeeklyPrescription)
        .options(
            joinedload(models.WeeklyPrescription.exercise_slot)
            .joinedload(models.ExerciseSlot.day_template)
            .joinedload(models.DayTemplate.mesocycle)
            .joinedload(models.Mesocycle.program)
        )
        .filter(models.WeeklyPrescription.id == prescription_id)
        .first()
    )

    if (
        prescription is None
        or prescription.exercise_slot.day_template.mesocycle.program.user_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Weekly prescription not found")

    muscle_group = prescription.exercise_slot.muscle_group
    goal = prescription.exercise_slot.day_template.mesocycle.program.goal

    result, verified, any_supported = _attempt_volume_generation(muscle_group, goal)

    # A single bounded retry (never a loop) is worth attempting when the
    # model claimed real grounding but nothing verified it - consistent
    # with stochastic bad luck, not necessarily a structural gap. A
    # self-reported general_knowledge estimate is NOT retried: the model
    # was already honest that nothing supports it, so re-asking the same
    # question against the same corpus has no structural reason to change
    # that (citation_verification.txt section 7).
    if not any_supported and result.grounding != "general_knowledge":
        result, verified, any_supported = _attempt_volume_generation(muscle_group, goal)

    prescription.sets = result.sets

    if any_supported:
        prescription.grounding_note = None
    elif result.grounding == "general_knowledge":
        prescription.grounding_note = _GENERAL_KNOWLEDGE_NOTE
    else:
        prescription.grounding_note = _UNSUBSTANTIATED_NOTE
        logger.warning(
            "Citation verification could not substantiate a generated value "
            "even after retry - possible corpus gap: muscle_group=%s goal=%s",
            muscle_group, goal,
        )

    # Replace, don't accumulate: this call's citations fully supersede any
    # citations left over from a previous generation call on this same
    # prescription (otherwise re-generating would just pile up stale rows).
    db.query(models.PrescriptionCitation).filter(
        models.PrescriptionCitation.prescription_id == prescription.id
    ).delete()

    for chunk, status in verified:
        citation = _get_or_create_citation(db, chunk)
        db.add(models.PrescriptionCitation(
            prescription_id=prescription.id,
            citation_id=citation.id,
            verification_status=status,
        ))

    db.commit()
    db.refresh(prescription)
    return prescription