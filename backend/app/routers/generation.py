from ..rag.generate import generate_volume_sets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/weekly-prescriptions", tags=["generation"])


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

    result = generate_volume_sets(prescription.exercise_slot.muscle_group, prescription.exercise_slot.day_template.mesocycle.program.goal)
    prescription.sets = result.sets
    db.commit()
    db.refresh(prescription)
    return prescription