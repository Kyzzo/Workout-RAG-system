from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/programs", tags=["programs"])


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
