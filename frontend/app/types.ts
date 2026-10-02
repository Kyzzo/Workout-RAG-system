// Mirrors backend/app/schemas.py's nested *Out models.

// Only supported citations are ever sent (contradicted/unresolved rows stay
// server-side for QA).
export type SupportingCitation = {
  verification_status: "primary_support" | "contextual_support";
  citation: { title: string; snippet: string };
};

export type WeeklyPrescription = {
  id: number;
  exercise_slot_id: number;
  week_number: number;
  sets: number;
  reps: string;
  load: string;
  sets_grounding_note: string | null;
  load_grounding_note: string | null;
  sets_citations: SupportingCitation[];
  load_citations: SupportingCitation[];
};

export type MuscleGroupFrequency = {
  id: number;
  muscle_group: string;
  frequency: number;
  grounding_note: string | null;
  supporting_citations: SupportingCitation[];
};

export type ProgressionScheme = {
  id: number;
  muscle_group: string;
  scheme: string;
  grounding_note: string | null;
  supporting_citations: SupportingCitation[];
};

export type ExerciseSlot = {
  id: number;
  day_template_id: number;
  exercise_name: string;
  muscle_group: string;
  order: number;
  weekly_prescriptions: WeeklyPrescription[];
};

export type DayTemplate = {
  id: number;
  mesocycle_id: number;
  name: string;
  order: number;
  rest_days_before: number | null;
  exercise_slots: ExerciseSlot[];
};

export type Mesocycle = {
  id: number;
  program_id: number;
  name: string;
  start_week: number;
  end_week: number;
  day_templates: DayTemplate[];
  muscle_group_frequencies: MuscleGroupFrequency[];
  progression_schemes: ProgressionScheme[];
};

export type ProgramSummary = {
  id: number;
  goal: string;
};

export type Program = {
  id: number;
  user_id: number;
  goal: string;
  mesocycles: Mesocycle[];
};
