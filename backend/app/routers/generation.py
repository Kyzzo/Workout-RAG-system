from ..rag.generate import build_volume_query, generate_volume_sets
from ..rag.verification import verify_citation

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/weekly-prescriptions", tags=["generation"])


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

    result, chunks = generate_volume_sets(muscle_group, goal)
    prescription.sets = result.sets

    query = build_volume_query(muscle_group, goal)
    chunks_by_id = {c["id"]: c for c in chunks}
    for chunk_id in result.chunk_ids:
        chunk = chunks_by_id[chunk_id]  # schema-constrained to this set, always present
        status = verify_citation(query, result.sets, chunk["text"], result.grounding)
        citation = _get_or_create_citation(db, chunk)
        db.add(models.PrescriptionCitation(
            prescription_id=prescription.id,
            citation_id=citation.id,
            verification_status=status,
        ))

    db.commit()
    db.refresh(prescription)
    return prescription