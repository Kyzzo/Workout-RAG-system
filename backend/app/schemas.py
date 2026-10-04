# Pydantic request/response schemas
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator

from .splits import SPLITS


def _normalize_muscle_group(value: str) -> str:
    # Sibling-volume lookup, frequency day-counting, and progression all
    # match muscle_group by exact string equality - "Chest" and "chest "
    # would silently count as two different muscle groups otherwise.
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("muscle_group must not be empty")
    return normalized


MuscleGroup = Annotated[str, AfterValidator(_normalize_muscle_group)]


VolumePreference = Literal["minimal", "moderate", "high"]


class ProgramCreate(BaseModel):
    goal: str
    volume_preference: VolumePreference = "moderate"


class ProgramGenerateRequest(BaseModel):
    goal: Literal["hypertrophy", "strength"]
    split: str
    days_per_week: int
    volume_preference: VolumePreference = "moderate"
    weeks: int = Field(default=6, ge=2, le=12)

    @model_validator(mode="after")
    def _check_split(self):
        split = SPLITS.get(self.split)
        if split is None:
            raise ValueError(f"Unknown split '{self.split}'")
        if self.days_per_week not in split.allowed_days:
            allowed = ", ".join(str(d) for d in split.allowed_days)
            raise ValueError(f"{split.label} fits {allowed} days per week, not {self.days_per_week}")
        return self


class SplitOut(BaseModel):
    key: str
    label: str
    allowed_days: list[int]
    day_types: list[str]


class ProgramSummaryOut(BaseModel):
    id: int
    goal: str
    volume_preference: str = "moderate"

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
    secondary_muscle_groups: list[MuscleGroup] = Field(default=[], max_length=3)


class ProgramOut(BaseModel):
    id: int
    user_id: int
    goal: str
    volume_preference: str = "moderate"
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
    muscle_group_volumes: list["MuscleGroupVolumeOut"] = []
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
    secondary_muscle_groups: list[str] = []
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
    rir: str = ""
    sets_grounding_note: str | None = None
    reps_grounding_note: str | None = None
    load_grounding_note: str | None = None
    rir_grounding_note: str | None = None
    # Supported citations only (primary/contextual) - see
    # models.SUPPORTED_VERIFICATION_STATUSES.
    sets_citations: list["SupportingCitationOut"] = []
    reps_citations: list["SupportingCitationOut"] = []
    load_citations: list["SupportingCitationOut"] = []
    rir_citations: list["SupportingCitationOut"] = []

    model_config = {"from_attributes": True}


class CitationOut(BaseModel):
    title: str
    snippet: str

    model_config = {"from_attributes": True}


class SupportingCitationOut(BaseModel):
    verification_status: Literal["primary_support", "contextual_support"]
    citation: CitationOut

    model_config = {"from_attributes": True}


class RuleJustificationOut(BaseModel):
    rule_key: str
    claim: str
    grounding_note: str | None = None
    supporting_citations: list[SupportingCitationOut] = []

    model_config = {"from_attributes": True}


class GenerateWeeklyVolumeRequest(BaseModel):
    muscle_group: MuscleGroup


class MuscleGroupVolumeOut(BaseModel):
    id: int
    mesocycle_id: int
    muscle_group: str
    weekly_sets: int
    grounding_note: str | None = None
    supporting_citations: list[SupportingCitationOut] = []

    model_config = {"from_attributes": True}


class GenerateWeeklyVolumeResponse(BaseModel):
    volume: MuscleGroupVolumeOut
    # What the block's exercises add up to after the per-exercise cap
    # (secondary work at half) - can fall short of the research target.
    delivered_weekly_sets: int
    # Hypertrophy: exercises added so the muscle's sets could be spread
    # across exercises within the per-exercise cap.
    exercises_added: list[str] = []


class GenerateFrequencyRequest(BaseModel):
    muscle_group: MuscleGroup
    # False = research comparison only: the frequency is generated and cited
    # but no days are added, because the user already committed to their
    # own days per week (wizard-built programs, whole-block generation).
    add_days: bool = True


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


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatMessageRequest(BaseModel):
    message: str
    # Set when the chat was opened FROM a specific WeeklyPrescription (e.g.
    # a "why is this 5-8 reps" affordance in the UI) - structural context,
    # trusted over anything the router model would otherwise have to guess.
    # See notes/phase6/phase6_chat_routing_concepts.txt section 2.
    field_id: int | None = None
    # Recent turns of this browser session's conversation, oldest first.
    # Client-supplied, so it's only ever used as context for resolving
    # references ("ok lower it"), never as a source of ids or authority -
    # field_id above and the ownership check still decide what gets touched.
    history: list[ChatTurn] = Field(default=[], max_length=20)


class ChatCitationOut(BaseModel):
    title: str
    snippet: str
    field: Literal["sets", "reps", "load", "rir"] | None = None  # discuss mode only


class ChatResponse(BaseModel):
    mode: Literal["adjust_prescription", "discuss_prescription", "answer_general_question"]
    prescription: WeeklyPrescriptionOut | None = None
    answer: str | None = None
    citations: list[ChatCitationOut] = []
    grounding_note: str | None = None


