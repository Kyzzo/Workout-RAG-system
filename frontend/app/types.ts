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
  volume_preference?: VolumePreference;
  trained?: boolean;
  include_deload?: boolean;
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

export type Goal = "hypertrophy" | "strength";

export type SplitOut = {
  key: string;
  label: string;
  allowed_days: number[];
  day_types: string[];
};

export type GenerateProgramRequest = {
  goal: Goal;
  split: string;
  days_per_week: number;
  weeks: number;
  volume_preference: VolumePreference;
  trained: boolean;
  include_deload: boolean;
};

export type GenerateWeeklyVolumeResponse = {
  volume: MuscleGroupVolume;
  delivered_weekly_sets: number;
  exercises_added: string[];
};

export type GenerateFrequencyResponse = {
  frequency: MuscleGroupFrequency;
  days_added: DayTemplate[];
};

export type GenerateProgressionResponse = {
  scheme: ProgressionScheme;
  updated_prescriptions: WeeklyPrescription[];
};

export type SwapExerciseResponse = {
  slot: ExerciseSlot;
  old_name: string;
  new_name: string;
  // Every value the swap changes anywhere in the block. Entries containing
  // " - the new exercise:" describe the new exercise itself.
  changes: string[];
  change_id: number | null;
  pending: boolean;
};

export type ChangeOut = { id: number; kind: string; description: string; status: string };

export type CitationOut = { id: number; title: string; snippet: string };

export type RebalanceField = "reps" | "load" | "rir";

export type RebalanceOut = {
  prescription_id: number;
  changed_field: RebalanceField;
  message: string;
  options: { field: RebalanceField; value: string; label: string }[];
};

export type ChatCitation = {
  title: string;
  snippet: string;
  field: "sets" | "reps" | "load" | "rir" | null;
};

export type ChatResponse = {
  mode: "adjust_prescription" | "discuss_prescription" | "answer_general_question";
  prescription: WeeklyPrescription | null;
  answer: string | null;
  citations: ChatCitation[];
  grounding_note: string | null;
  rebalance: RebalanceOut | null;
  swap: SwapExerciseResponse | null;
  change_id: number | null;
};

export type ChangeStatus = "pending" | "applied" | "undone" | "cancelled";

export type SavedChatTurn = {
  role: "user" | "assistant";
  content: Record<string, unknown>;
  change_status: ChangeStatus | null;
};

export type ChatMessageRequest = {
  message: string;
  field_id: number | null;
  history: { role: "user" | "assistant"; content: string }[];
  anchor_label: string | null;
  this_week_only: boolean;
};
