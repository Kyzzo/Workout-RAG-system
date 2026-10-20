from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, load_only, selectinload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..ownership import get_owned_program
from ..rag.exercise_selection import ExerciseSelectionError, select_exercises
from ..rag.rule_justifications import RULES, justify_rule
from ..splits import SPLITS, plan_days

router = APIRouter(prefix="/programs", tags=["programs"])
splits_router = APIRouter(prefix="/splits", tags=["programs"])
rules_router = APIRouter(prefix="/rules", tags=["programs"])


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

    program = models.Program(
        user_id=current_user.id, goal=request.goal, volume_preference=request.volume_preference,
        trained=request.trained, include_deload=request.include_deload,
    )
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
        for slot_order, (exercise_name, muscle_group, secondaries, is_compound) in enumerate(picks, start=1):
            slot = models.ExerciseSlot(
                day_template_id=day_template.id, exercise_name=exercise_name,
                muscle_group=muscle_group, secondary_muscle_groups=secondaries, is_compound=is_compound,
                order=slot_order,
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
    db_program = models.Program(
        goal=program.goal, volume_preference=program.volume_preference, trained=program.trained,
        include_deload=program.include_deload, user_id=current_user.id,
    )
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
    # One SELECT ... IN per level, and citations without their excerpt text
    # (the response carries titles; GET /citations/{id} serves the text).
    # A single joined tree repeated every excerpt on each of its rows - weeks
    # x fields x citations - and shipped several MB from the database for a
    # 55-exercise program (Oct 20, 2026).
    mesocycles = selectinload(models.Program.mesocycles)
    citation_ref = load_only(models.Citation.id, models.Citation.title)
    program = (
        db.query(models.Program)
        .options(
            mesocycles
            .selectinload(models.Mesocycle.day_templates)
            .selectinload(models.DayTemplate.exercise_slots)
            .selectinload(models.ExerciseSlot.weekly_prescriptions)
            .selectinload(models.WeeklyPrescription.prescription_citations)
            .selectinload(models.PrescriptionCitation.citation).options(citation_ref),
            mesocycles
            .selectinload(models.Mesocycle.muscle_group_frequencies)
            .selectinload(models.MuscleGroupFrequency.frequency_citations)
            .selectinload(models.FrequencyCitation.citation).options(citation_ref),
            mesocycles
            .selectinload(models.Mesocycle.muscle_group_volumes)
            .selectinload(models.MuscleGroupVolume.volume_citations)
            .selectinload(models.VolumeCitation.citation).options(citation_ref),
            mesocycles
            .selectinload(models.Mesocycle.progression_schemes)
            .selectinload(models.ProgressionScheme.progression_scheme_citations)
            .selectinload(models.ProgressionSchemeCitation.citation).options(citation_ref),
        )
        .filter(models.Program.id == program_id, models.Program.user_id == current_user.id)
        .first()
    )
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return program


@router.patch("/{program_id}", response_model=schemas.ProgramSummaryOut)
def rename_program(
    program_id: int,
    request: schemas.Rename,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    program = get_owned_program(program_id, db, current_user)
    program.name = request.name.strip()
    db.commit()
    db.refresh(program)
    return program


@router.delete("/{program_id}", status_code=204)
def delete_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Cascades through the ORM: blocks -> days -> exercises -> weekly values
    # -> citation links, plus each block's frequency/progression records.
    # Shared Citation rows are kept (other programs may cite the same chunk).
    program = get_owned_program(program_id, db, current_user)
    db.delete(program)
    db.commit()
    return Response(status_code=204)


@rules_router.get("/{rule_key}", response_model=schemas.RuleJustificationOut)
def get_rule_justification(
    rule_key: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Verified once and cached; the first request after a fresh database
    # (or a refresh) runs the retrieval + judge pass.
    if rule_key not in RULES:
        raise HTTPException(status_code=404, detail="Unknown rule")
    return justify_rule(db, rule_key)
