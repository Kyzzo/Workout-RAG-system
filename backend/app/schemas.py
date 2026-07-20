# Pydantic request/response schemas
from pydantic import BaseModel


class ProgramCreate(BaseModel):
    goal: str


class ProgramOut(BaseModel):
    id: int
    user_id: int
    goal: str
    mesocycles: list["MesocycleOut"]

    model_config = {"from_attributes": True}

class MesocycleOut(BaseModel):
    id: int
    program_id: int
    name: str
    start_week: int
    end_week: int
    day_templates: list["DayTemplateOut"]

    model_config = {"from_attributes": True}

class DayTemplateOut(BaseModel):
    id: int
    mesocycle_id: int
    name: str
    order: int
    rest_days_before: int | None
    exercise_slots: list["ExerciseSlotOut"]

    model_config = {"from_attributes": True}

class ExerciseSlotOut(BaseModel):
    id: int
    day_template_id: int
    exercise_name: str
    order: int
    weekly_prescriptions: list["WeeklyPrescriptionOut"]

    model_config = {"from_attributes": True}

class WeeklyPrescriptionOut(BaseModel):
    id: int
    exercise_slot_id: int
    week_number: int
    sets: int
    reps: str
    load: str

    model_config = {"from_attributes": True}


