from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

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


@router.get("/{program_id}", response_model=schemas.ProgramOut)
def get_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    program = (
        db.query(models.Program)
        .options(
            joinedload(models.Program.mesocycles)
            .joinedload(models.Mesocycle.day_templates)
            .joinedload(models.DayTemplate.exercise_slots)
            .joinedload(models.ExerciseSlot.weekly_prescriptions)
        )
        .filter(models.Program.id == program_id, models.Program.user_id == current_user.id)
        .first()
    )
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return program
