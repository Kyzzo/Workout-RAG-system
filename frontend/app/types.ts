// Mirrors backend/app/schemas.py's nested *Out models.

export type WeeklyPrescription = {
  id: number;
  exercise_slot_id: number;
  week_number: number;
  sets: number;
  reps: string;
  load: string;
  grounding_note: string | null;
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
};

export type Program = {
  id: number;
  user_id: number;
  goal: string;
  mesocycles: Mesocycle[];
};
