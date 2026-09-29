from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from . import models


def get_owned_prescription(prescription_id: int, db: Session, current_user: models.User) -> models.WeeklyPrescription:
    # Shared across every entry point that can act on a WeeklyPrescription -
    # direct REST endpoints (routers/generation.py) and the chat router
    # (routers/chat.py) alike. Lives here specifically so it can't drift out
    # of sync the way a copy-pasted check per entry point could - see
    # notes/phase6/phase6_chat_routing_concepts.txt section 3: a model- or
    # context-supplied field_id from chat is a different code path than a
    # URL path parameter, and needs the exact same re-verification either way.
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
    return prescription
