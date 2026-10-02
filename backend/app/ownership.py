from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from . import models


def get_owned_program(program_id: int, db: Session, current_user: models.User) -> models.Program:
    program = (
        db.query(models.Program)
        .options(joinedload(models.Program.mesocycles))
        .filter(models.Program.id == program_id, models.Program.user_id == current_user.id)
        .first()
    )
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


def get_owned_mesocycle(mesocycle_id: int, db: Session, current_user: models.User) -> models.Mesocycle:
    mesocycle = (
        db.query(models.Mesocycle)
        .options(joinedload(models.Mesocycle.program), joinedload(models.Mesocycle.day_templates))
        .filter(models.Mesocycle.id == mesocycle_id)
        .first()
    )
    if mesocycle is None or mesocycle.program.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Mesocycle not found")
    return mesocycle


def get_owned_day_template(day_template_id: int, db: Session, current_user: models.User) -> models.DayTemplate:
    day = (
        db.query(models.DayTemplate)
        .options(
            joinedload(models.DayTemplate.exercise_slots),
            joinedload(models.DayTemplate.mesocycle).joinedload(models.Mesocycle.program),
        )
        .filter(models.DayTemplate.id == day_template_id)
        .first()
    )
    if day is None or day.mesocycle.program.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Day not found")
    return day


def get_owned_exercise_slot(exercise_slot_id: int, db: Session, current_user: models.User) -> models.ExerciseSlot:
    slot = (
        db.query(models.ExerciseSlot)
        .options(
            joinedload(models.ExerciseSlot.day_template)
            .joinedload(models.DayTemplate.mesocycle)
            .joinedload(models.Mesocycle.program)
        )
        .filter(models.ExerciseSlot.id == exercise_slot_id)
        .first()
    )
    if slot is None or slot.day_template.mesocycle.program.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Exercise not found")
    return slot


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
