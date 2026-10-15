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
    trained: bool = False
    include_deload: bool = False


class ProgramGenerateRequest(BaseModel):
    goal: Literal["hypertrophy", "strength"]
    split: str
    days_per_week: int
    volume_preference: VolumePreference = "moderate"
    weeks: int = Field(default=6, ge=2, le=12)
    trained: bool = False
    include_deload: bool = False

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
    name: str | None = None
    volume_preference: str = "moderate"
    trained: bool = False
    include_deload: bool = False

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
    name: str | None = None
    volume_preference: str = "moderate"
    trained: bool = False
    include_deload: bool = False
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
    load_fit_note: str | None = None
    # Supported citations only (primary/contextual) - see
    # models.SUPPORTED_VERIFICATION_STATUSES.
    sets_citations: list["SupportingCitationOut"] = []
    reps_citations: list["SupportingCitationOut"] = []
    load_citations: list["SupportingCitationOut"] = []
    rir_citations: list["SupportingCitationOut"] = []

    model_config = {"from_attributes": True}


class CitationOut(BaseModel):
    id: int  # for its plain-language summary (GET /citations/{id}/summary)
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
    # What the message was anchored to, as shown in the UI ("Bench Press,
    # week 2") - saved with the message so reloaded history reads the same.
    anchor_label: str | None = Field(default=None, max_length=200)


class SavedChatTurn(BaseModel):
    role: str  # "user" / "assistant"
    content: dict
    # For a turn that made (or previewed) a change: "pending" / "applied" /
    # "undone", or "cancelled" once a preview is gone - so a reload shows
    # the right Undo / Confirm buttons.
    change_status: str | None = None


class ChatCitationOut(BaseModel):
    title: str
    snippet: str
    field: Literal["sets", "reps", "load", "rir"] | None = None  # discuss mode only


RebalanceField = Literal["reps", "load", "rir"]


class RebalanceOption(BaseModel):
    field: RebalanceField
    value: str
    label: str


class RebalanceOut(BaseModel):
    # Offered after a chat change to reps, load or RIR leaves the three not
    # fitting: the two ways to fit the others to the change (or keep it).
    prescription_id: int
    changed_field: RebalanceField
    message: str
    options: list[RebalanceOption]


class RebalanceResult(BaseModel):
    prescription: WeeklyPrescriptionOut
    change_id: int  # undo with POST /changes/{id}/undo


class RebalanceRequest(BaseModel):
    changed_field: RebalanceField
    apply_field: RebalanceField


class ChangeOut(BaseModel):
    id: int
    kind: str
    description: str
    status: str

    model_config = {"from_attributes": True}


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MesocycleSummaryOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class DayTemplateSummaryOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


class SwapExerciseRequest(BaseModel):
    # None: have an exercise for the same muscle suggested.
    exercise_name: str | None = Field(default=None, max_length=80)


class SwapExerciseResponse(BaseModel):
    slot: ExerciseSlotOut
    old_name: str
    new_name: str
    # Every value the swap changes, here or elsewhere in the block (the
    # rotation on other days, other muscles' sets via secondary credit).
    changes: list[str]
    # A swap is previewed first (pending, nothing applied) and applied on
    # confirm; change_id confirms, cancels or (once applied) undoes it.
    change_id: int | None = None
    pending: bool = False


class ChatResponse(BaseModel):
    mode: Literal["adjust_prescription", "discuss_prescription", "answer_general_question"]
    prescription: WeeklyPrescriptionOut | None = None
    answer: str | None = None
    citations: list[ChatCitationOut] = []
    grounding_note: str | None = None
    rebalance: RebalanceOut | None = None
    swap: SwapExerciseResponse | None = None
    # Set when the message changed the program: undo with POST /changes/{id}/undo.
    change_id: int | None = None


