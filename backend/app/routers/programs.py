from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/programs", tags=["programs"])

HARDCODED_USER_ID = 1  # placeholder until Clerk auth is wired in


@router.post("/", response_model=schemas.ProgramOut)
def create_program(program: schemas.ProgramCreate, db: Session = Depends(get_db)):
    db_program = models.Program(goal=program.goal, user_id=HARDCODED_USER_ID)
    db.add(db_program)
    db.commit()
    db.refresh(db_program)
    return db_program


@router.get("/{program_id}", response_model=schemas.ProgramOut)
def get_program(program_id: int, db: Session = Depends(get_db)):
    program = (
        db.query(models.Program)
        .options(
            joinedload(models.Program.mesocycles)
            .joinedload(models.Mesocycle.day_templates)
            .joinedload(models.DayTemplate.exercise_slots)
            .joinedload(models.ExerciseSlot.weekly_prescriptions)
        )
        .filter(models.Program.id == program_id)
        .first()
    )
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return program
