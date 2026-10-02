# Manual program-structure builder: Program -> Mesocycle -> DayTemplate ->
# ExerciseSlot, plain CRUD, no AI. Exercise selection isn't a research-
# grounded claim in this app (citations attach to numbers, not to which
# exercises were picked - see datamodel.txt), so structure is user-built
# and the NUMBERS are filled in afterward by the generation endpoints.
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..ownership import (
    get_owned_day_template,
    get_owned_exercise_slot,
    get_owned_mesocycle,
    get_owned_program,
)

router = APIRouter(tags=["structure"])


@router.post("/programs/{program_id}/mesocycles", response_model=schemas.MesocycleOut)
def create_mesocycle(
    program_id: int,
    request: schemas.MesocycleCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    program = get_owned_program(program_id, db, current_user)

    # week_number on WeeklyPrescription is absolute across the whole program,
    # so two blocks covering the same week would give one exercise-week two
    # competing prescriptions with no way to tell which block is current.
    for existing in program.mesocycles:
        if request.start_week <= existing.end_week and existing.start_week <= request.end_week:
            raise HTTPException(
                status_code=400,
                detail=f"Weeks {request.start_week}-{request.end_week} overlap "
                f"'{existing.name}' (weeks {existing.start_week}-{existing.end_week}).",
            )

    mesocycle = models.Mesocycle(
        program_id=program.id,
        name=request.name,
        start_week=request.start_week,
        end_week=request.end_week,
    )
    db.add(mesocycle)
    db.commit()
    db.refresh(mesocycle)
    return mesocycle


@router.post("/mesocycles/{mesocycle_id}/days", response_model=schemas.DayTemplateOut)
def create_day_template(
    mesocycle_id: int,
    request: schemas.DayTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    mesocycle = get_owned_mesocycle(mesocycle_id, db, current_user)

    day = models.DayTemplate(
        mesocycle_id=mesocycle.id,
        name=request.name,
        order=max((d.order for d in mesocycle.day_templates), default=0) + 1,
        rest_days_before=request.rest_days_before,
    )
    db.add(day)
    db.commit()
    db.refresh(day)
    return day


@router.post("/day-templates/{day_template_id}/exercises", response_model=schemas.ExerciseSlotOut)
def create_exercise_slot(
    day_template_id: int,
    request: schemas.ExerciseSlotCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    day = get_owned_day_template(day_template_id, db, current_user)
    mesocycle = day.mesocycle

    slot = models.ExerciseSlot(
        day_template_id=day.id,
        exercise_name=request.exercise_name,
        muscle_group=request.muscle_group,
        order=max((s.order for s in day.exercise_slots), default=0) + 1,
    )
    db.add(slot)
    db.flush()

    # One placeholder row per week of the block, so every exercise-week has
    # a WeeklyPrescription for generation to write into. sets=0/empty load
    # is the same "not generated yet" state day-cloning uses, which
    # _sibling_volume_summary already knows to skip rather than report as a
    # real zero-set allocation.
    for week in range(mesocycle.start_week, mesocycle.end_week + 1):
        db.add(models.WeeklyPrescription(
            exercise_slot_id=slot.id,
            week_number=week,
            sets=0,
            reps="",
            load="",
        ))

    db.commit()
    db.refresh(slot)
    return slot


# Deletes cascade down through the ORM (DayTemplate -> ExerciseSlot ->
# WeeklyPrescription -> PrescriptionCitation, see models.py). Shared Citation
# rows are kept - other prescriptions may cite the same chunk. This removes
# generated values along with the structure; the UI confirms first when any
# exist. It deliberately doesn't try to preserve history the way an
# exercise SWAP would need to (datamodel.txt) - deleting is "this shouldn't
# have been in the program", not "replace it from week N onward".


@router.delete("/day-templates/{day_template_id}", status_code=204)
def delete_day_template(
    day_template_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    day = get_owned_day_template(day_template_id, db, current_user)
    db.delete(day)
    db.commit()
    return Response(status_code=204)


@router.delete("/exercise-slots/{exercise_slot_id}", status_code=204)
def delete_exercise_slot(
    exercise_slot_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    slot = get_owned_exercise_slot(exercise_slot_id, db, current_user)
    db.delete(slot)
    db.commit()
    return Response(status_code=204)
