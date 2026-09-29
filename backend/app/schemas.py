# Pydantic request/response schemas
from typing import Literal

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
    muscle_group: str
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
    grounding_note: str | None = None

    model_config = {"from_attributes": True}


class GenerateFrequencyRequest(BaseModel):
    muscle_group: str


class MuscleGroupFrequencyOut(BaseModel):
    id: int
    mesocycle_id: int
    muscle_group: str
    frequency: int
    grounding_note: str | None = None

    model_config = {"from_attributes": True}


class GenerateFrequencyResponse(BaseModel):
    frequency: MuscleGroupFrequencyOut
    days_added: list["DayTemplateOut"]


class GenerateProgressionRequest(BaseModel):
    muscle_group: str


class ProgressionSchemeOut(BaseModel):
    id: int
    mesocycle_id: int
    muscle_group: str
    scheme: str
    grounding_note: str | None = None

    model_config = {"from_attributes": True}


class GenerateProgressionResponse(BaseModel):
    scheme: ProgressionSchemeOut
    updated_prescriptions: list["WeeklyPrescriptionOut"]


class ChatMessageRequest(BaseModel):
    message: str
    # Set when the chat was opened FROM a specific WeeklyPrescription (e.g.
    # a "why is this 5-8 reps" affordance in the UI) - structural context,
    # trusted over anything the router model would otherwise have to guess.
    # See notes/phase6/phase6_chat_routing_concepts.txt section 2.
    field_id: int | None = None


class ChatCitationOut(BaseModel):
    title: str
    snippet: str


class ChatResponse(BaseModel):
    mode: Literal["adjust_prescription", "discuss_prescription", "answer_general_question"]
    prescription: WeeklyPrescriptionOut | None = None
    answer: str | None = None
    citations: list[ChatCitationOut] = []
    grounding_note: str | None = None


