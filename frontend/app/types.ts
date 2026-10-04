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
  load: string; // %1RM - strength programs only
  rir: string; // effort as reps in reserve, e.g. "1-2 RIR" or "0 RIR (to failure)"
  sets_grounding_note: string | null;
  reps_grounding_note: string | null;
  load_grounding_note: string | null;
  rir_grounding_note: string | null;
  sets_citations: SupportingCitation[];
  reps_citations: SupportingCitation[];
  load_citations: SupportingCitation[];
  rir_citations: SupportingCitation[];
};

// Verified citations for one of the app's mechanical rules, e.g. how
// weekly sets are spread evenly across sessions.
export type RuleJustification = {
  rule_key: string;
  claim: string;
  grounding_note: string | null;
  supporting_citations: SupportingCitation[];
};

// The cited weekly sets for a muscle; WeeklyPrescription.sets are its
// mechanical split across that muscle's exercises.
export type MuscleGroupVolume = {
  id: number;
  muscle_group: string;
  weekly_sets: number;
  grounding_note: string | null;
  supporting_citations: SupportingCitation[];
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
  // Each counts as half a set toward that muscle's weekly volume.
  secondary_muscle_groups: string[];
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
  muscle_group_volumes: MuscleGroupVolume[];
  progression_schemes: ProgressionScheme[];
};

export type ProgramSummary = {
  id: number;
  goal: string;
};

export type VolumePreference = "minimal" | "moderate" | "high";

export const VOLUME_LABELS: Record<VolumePreference, string> = {
  minimal: "Minimalist",
  moderate: "Moderate (recommended)",
  high: "Higher volume",
};

// Hypertrophy weekly sets per muscle for each preference (fractional sets,
// secondary work at half) - mirrors HYPERTROPHY_VOLUME_BANDS in the backend:
// Pelland et al. 2025's higher-efficiency (5-10) and intermediate (11-18)
// tiers.
export const HYPERTROPHY_VOLUME_BANDS: Record<VolumePreference, [number, number]> = {
  minimal: [5, 10],
  moderate: [11, 14],
  high: [15, 18],
};

export function volumeLabel(preference: VolumePreference, goal: string): string {
  const label = VOLUME_LABELS[preference] ?? preference;
  if (goal !== "hypertrophy") return label;
  const [low, high] = HYPERTROPHY_VOLUME_BANDS[preference];
  return `${label} - ${low}-${high} sets/week per muscle`;
}

export type Program = {
  id: number;
  user_id: number;
  goal: string;
  volume_preference: VolumePreference;
  mesocycles: Mesocycle[];
};
