# Pydantic request/response schemas
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator


def _normalize_muscle_group(value: str) -> str:
    # Sibling-volume lookup, frequency day-counting, and progression all
    # match muscle_group by exact string equality - "Chest" and "chest "
    # would silently count as two different muscle groups otherwise.
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("muscle_group must not be empty")
    return normalized


MuscleGroup = Annotated[str, AfterValidator(_normalize_muscle_group)]


class ProgramCreate(BaseModel):
    goal: str


class ProgramSummaryOut(BaseModel):
    id: int
    goal: str

    model_config = {"from_attributes": True}


class MesocycleCreate(BaseModel):
    name: str = Field(min_length=1)
    start_week: int = Field(ge=1)
    end_week: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_week_range(self):
        if self.end_week < self.start_week:
            raise ValueError("end_week must be on or after start_week")
        return self


class DayTemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    rest_days_before: int | None = Field(default=None, ge=0)


class ExerciseSlotCreate(BaseModel):
    exercise_name: str = Field(min_length=1)
    muscle_group: MuscleGroup


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
    muscle_group_frequencies: list["MuscleGroupFrequencyOut"] = []
    progression_schemes: list["ProgressionSchemeOut"] = []

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
    sets_grounding_note: str | None = None
    load_grounding_note: str | None = None
    # Supported citations only (primary/contextual) - see
    # models.SUPPORTED_VERIFICATION_STATUSES.
    sets_citations: list["SupportingCitationOut"] = []
    load_citations: list["SupportingCitationOut"] = []

    model_config = {"from_attributes": True}


class CitationOut(BaseModel):
    title: str
    snippet: str

    model_config = {"from_attributes": True}


class SupportingCitationOut(BaseModel):
    verification_status: Literal["primary_support", "contextual_support"]
    citation: CitationOut

    model_config = {"from_attributes": True}


class GenerateFrequencyRequest(BaseModel):
    muscle_group: MuscleGroup


class MuscleGroupFrequencyOut(BaseModel):
    id: int
    mesocycle_id: int
    muscle_group: str
    frequency: int
    grounding_note: str | None = None
    supporting_citations: list[SupportingCitationOut] = []

    model_config = {"from_attributes": True}


class GenerateFrequencyResponse(BaseModel):
    frequency: MuscleGroupFrequencyOut
    days_added: list["DayTemplateOut"]


class GenerateProgressionRequest(BaseModel):
    muscle_group: MuscleGroup


class ProgressionSchemeOut(BaseModel):
    id: int
    mesocycle_id: int
    muscle_group: str
    scheme: str
    grounding_note: str | None = None
    supporting_citations: list[SupportingCitationOut] = []

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
    field: Literal["sets", "load"] | None = None  # discuss mode only


class ChatResponse(BaseModel):
    mode: Literal["adjust_prescription", "discuss_prescription", "answer_general_question"]
    prescription: WeeklyPrescriptionOut | None = None
    answer: str | None = None
    citations: list[ChatCitationOut] = []
    grounding_note: str | None = None


