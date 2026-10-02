from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..rag.exercise_selection import ExerciseSelectionError, select_exercises
from ..splits import SPLITS, plan_days

router = APIRouter(prefix="/programs", tags=["programs"])
splits_router = APIRouter(prefix="/splits", tags=["programs"])


@splits_router.get("/", response_model=list[schemas.SplitOut])
def list_splits():
    return [
        schemas.SplitOut(
            key=key, label=split.label, allowed_days=list(split.allowed_days),
            day_types=[d.name for d in split.day_types],
        )
        for key, split in SPLITS.items()
    ]


@router.post("/generate", response_model=schemas.ProgramOut)
def generate_program(
    request: schemas.ProgramGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Builds the STRUCTURE only - one block, the split's days, AI-picked
    # exercises with placeholder weeks. The numbers come afterwards from the
    # same per-exercise generation + verification as everything else
    # (driven by the browser, so progress is visible and nothing times out).
    split = SPLITS[request.split]
    days = plan_days(split, request.days_per_week)
    # Before any write: if selection fails, no half-built program is left.
    try:
        selection = select_exercises(days, request.goal, split.label)
    except ExerciseSelectionError as err:
        raise HTTPException(status_code=502, detail=str(err))

    program = models.Program(user_id=current_user.id, goal=request.goal)
    db.add(program)
    db.flush()
    mesocycle = models.Mesocycle(
        program_id=program.id,
        name=f"{split.label}, {request.days_per_week} days/week",
        start_week=1,
        end_week=request.weeks,
    )
    db.add(mesocycle)
    db.flush()

    for order, (day, picks) in enumerate(zip(days, selection), start=1):
        day_template = models.DayTemplate(
            mesocycle_id=mesocycle.id, name=day.name, order=order, rest_days_before=day.rest_days_before,
        )
        db.add(day_template)
        db.flush()
        for slot_order, (exercise_name, muscle_group) in enumerate(picks, start=1):
            slot = models.ExerciseSlot(
                day_template_id=day_template.id, exercise_name=exercise_name,
                muscle_group=muscle_group, order=slot_order,
            )
            slot.weekly_prescriptions = [
                models.WeeklyPrescription(week_number=week, sets=0, reps="", load="")
                for week in range(1, request.weeks + 1)
            ]
            db.add(slot)

    db.commit()
    return get_program(program_id=program.id, db=db, current_user=current_user)


@router.post("/", response_model=schemas.ProgramOut)
def create_program(
    program: schemas.ProgramCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_program = models.Program(goal=program.goal, user_id=current_user.id)
    db.add(db_program)
    db.commit()
    db.refresh(db_program)
    return db_program


@router.get("/", response_model=list[schemas.ProgramSummaryOut])
def list_programs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Program)
        .filter(models.Program.user_id == current_user.id)
        .order_by(models.Program.id.desc())
        .all()
    )


@router.get("/{program_id}", response_model=schemas.ProgramOut)
def get_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    mesocycles = joinedload(models.Program.mesocycles)
    program = (
        db.query(models.Program)
        .options(
            mesocycles
            .joinedload(models.Mesocycle.day_templates)
            .joinedload(models.DayTemplate.exercise_slots)
            .joinedload(models.ExerciseSlot.weekly_prescriptions)
            .joinedload(models.WeeklyPrescription.prescription_citations)
            .joinedload(models.PrescriptionCitation.citation),
            # Separate SELECT ... IN queries for the block-level results, so
            # they don't multiply the rows of the big joined tree above.
            mesocycles
            .selectinload(models.Mesocycle.muscle_group_frequencies)
            .selectinload(models.MuscleGroupFrequency.frequency_citations)
            .joinedload(models.FrequencyCitation.citation),
            mesocycles
            .selectinload(models.Mesocycle.progression_schemes)
            .selectinload(models.ProgressionScheme.progression_scheme_citations)
            .joinedload(models.ProgressionSchemeCitation.citation),
        )
        .filter(models.Program.id == program_id, models.Program.user_id == current_user.id)
        .first()
    )
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return program
