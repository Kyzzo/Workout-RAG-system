// Mirrors backend/app/schemas.py's nested *Out models.

// Only supported citations are ever sent (contradicted/unresolved rows stay
// server-side for QA).
export type SupportingCitation = {
  verification_status: "primary_support" | "contextual_support";
  // Title only: the excerpt is fetched when a sources panel shows it
  // (GET /citations/{id}, Citations.tsx).
  citation: { id: number; title: string };
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
  // Set when reps, load and RIR don't fit together (strength %1RM loads).
  load_fit_note: string | null;
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
  name?: string | null;
};

// The program's name, or "Program #22" until it's renamed (like a new
// playlist's default name) - the same title the program view shows.
export function programTitle(p: ProgramSummary): string {
  return p.name || `Program #${p.id}`;
}

// "Summer cut (strength)" - the title and goal, for the program list.
export function programLabel(p: ProgramSummary): string {
  return `${programTitle(p)} (${p.goal})`;
}

export type VolumePreference = "minimal" | "moderate" | "high";

export const VOLUME_LABELS: Record<VolumePreference, string> = {
  minimal: "Minimalist",
  moderate: "Moderate (recommended)",
  high: "Higher volume",
};

// Weekly sets per muscle for each goal and preference (fractional sets,
// secondary work at half) - mirrors VOLUME_BANDS in the backend: Pelland et
// al. 2025's efficiency tiers for hypertrophy (5-10, 11-18) and strength
// (1-2, 3-4).
export const VOLUME_BANDS: Record<string, Record<VolumePreference, [number, number]>> = {
  hypertrophy: { minimal: [5, 10], moderate: [11, 14], high: [15, 18] },
  strength: { minimal: [1, 2], moderate: [3, 3], high: [4, 4] },
};

export function volumeLabel(preference: VolumePreference, goal: string): string {
  const label = VOLUME_LABELS[preference] ?? preference;
  const band = VOLUME_BANDS[goal]?.[preference];
  if (!band) return label;
  const [low, high] = band;
  return `${label} - ${low === high ? low : `${low}-${high}`} sets/week per muscle`;
}

export type Program = {
  id: number;
  user_id: number;
  goal: string;
  volume_preference: VolumePreference;
  name?: string | null;
  trained: boolean;
  include_deload: boolean;
  mesocycles: Mesocycle[];
};

// "Moderate · 11-14 sets/wk" - the program chip on phones, where the full
// label wraps onto its own line.
export function shortVolumeLabel(preference: VolumePreference, goal: string): string {
  const label = (VOLUME_LABELS[preference] ?? preference).replace(" (recommended)", "");
  const band = VOLUME_BANDS[goal]?.[preference];
  if (!band) return label;
  const [low, high] = band;
  return `${label} · ${low === high ? low : `${low}-${high}`} sets/wk`;
}
