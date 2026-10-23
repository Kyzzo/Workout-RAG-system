// Development-only fixtures for `npm run preview`. Every paper, excerpt and
// summary here is invented for layout work and labelled as such; none of it
// is research and none of it ships in a production build.

import type { Mesocycle, Program, RuleJustification, SplitOut, SupportingCitation, WeeklyPrescription } from "../types";

export const SPLITS: SplitOut[] = [
  { key: "upper_lower", label: "Upper/Lower", allowed_days: [2, 4, 6], day_types: ["Upper", "Lower"] },
  { key: "ppl", label: "Push/Pull/Legs", allowed_days: [3, 6], day_types: ["Push", "Pull", "Legs"] },
  { key: "anterior_posterior", label: "Anterior/Posterior", allowed_days: [2, 4, 6], day_types: ["Anterior", "Posterior"] },
  { key: "torso_limbs", label: "Torso/Limbs", allowed_days: [2, 4, 6], day_types: ["Torso", "Limbs"] },
  { key: "arnold", label: "Arnold", allowed_days: [3, 6], day_types: ["Chest & Back", "Shoulders & Arms", "Legs"] },
  { key: "full_body", label: "Full Body (FBEOD)", allowed_days: [2, 3, 4], day_types: ["Full Body"] },
];

const PAPERS = [
  ["Ashdown et al. 2024", "meta-analysis · trained adults"],
  ["Brennan & Holt 2023", "randomised trial · 10 weeks"],
  ["Calloway et al. 2022", "meta-regression · mixed training status"],
  ["Draper et al. 2021", "randomised trial · untrained adults"],
  ["Ellery & Moss 2024", "systematic review"],
  ["Fairholme et al. 2020", "within-subject trial · trained men"],
  ["Greaves et al. 2023", "randomised trial · trained women"],
  ["Hollis & Varga 2022", "meta-analysis · strength outcomes"],
];

export const CITATIONS = new Map<number, { id: number; title: string; snippet: string }>();
PAPERS.forEach(([paper, tags], i) => {
  for (let k = 0; k < 2; k++) {
    const id = 500 + i * 2 + k;
    CITATIONS.set(id, {
      id,
      title: `${paper} · ${tags}`,
      snippet: `Preview fixture excerpt ${k + 1} from ${paper}. Stand-in text so the layout can be judged with a realistic length: participants trained each muscle on two or three days a week for the whole intervention, and outcomes were measured before and after.`,
    });
  }
});

export function cites(ids: number[], primary = 1): SupportingCitation[] {
  return ids.map((id, i) => ({
    verification_status: i < primary ? "primary_support" : "contextual_support",
    citation: { id, title: CITATIONS.get(id)?.title ?? `Unknown · ${id}` },
  }));
}

export const RULE_KEYS = [
  "even_session_split", "volume_efficiency_tiers", "strength_volume_efficiency_tiers", "frequency_matched_volume",
  "per_session_diminishing_returns", "hypertrophy_sets_per_exercise", "strength_sets_per_exercise",
  "periodization_by_training_status", "daily_undulating_protocol", "linear_periodization_protocol",
  "strength_accessory_reps", "dup_rep_scheme", "dup_session_order", "weekly_undulation_not_better", "deload_week",
  "hypertrophy_rep_progression", "strength_frequency", "reps_at_percent_1rm",
];

export function rule(key: string, i: number): RuleJustification {
  return {
    rule_key: key,
    claim: `Preview fixture claim for “${key.replace(/_/g, " ")}”, standing in for the checked statement the server returns.`,
    grounding_note: i % 3 === 0 ? "Preview fixture note: a caveat about the populations the studies covered." : null,
    supporting_citations: cites([500 + ((i * 2) % 16), 501 + ((i * 2 + 4) % 15)], 1),
  };
}

let nextId = 9000;
export const newId = () => ++nextId;
// Every backend instance numbers its fixtures the same way, so seeded
// tracking logs always match the program they were made from.
export const resetIds = () => {
  nextId = 9000;
};

type Rx = Partial<WeeklyPrescription>;

function prescription(slotId: number, week: number, rx: Rx): WeeklyPrescription {
  return {
    id: newId(),
    exercise_slot_id: slotId,
    week_number: week,
    sets: 0,
    reps: "",
    load: "",
    rir: "",
    sets_grounding_note: null,
    reps_grounding_note: null,
    load_grounding_note: null,
    rir_grounding_note: null,
    load_fit_note: null,
    sets_citations: [],
    reps_citations: [],
    load_citations: [],
    rir_citations: [],
    ...rx,
  };
}

type ExerciseSpec = { name: string; muscle: string; also?: string[]; rx?: (week: number) => Rx | null };

function block(programId: number, name: string, start: number, end: number, days: { name: string; rest: number | null; exercises: ExerciseSpec[] }[]): Mesocycle {
  const id = newId();
  return {
    id,
    program_id: programId,
    name,
    start_week: start,
    end_week: end,
    muscle_group_frequencies: [],
    muscle_group_volumes: [],
    progression_schemes: [],
    day_templates: days.map((d, di) => {
      const dayId = newId();
      return {
        id: dayId,
        mesocycle_id: id,
        name: d.name,
        order: di,
        rest_days_before: d.rest,
        exercise_slots: d.exercises.map((e, ei) => {
          const slotId = newId();
          return {
            id: slotId,
            day_template_id: dayId,
            exercise_name: e.name,
            muscle_group: e.muscle,
            secondary_muscle_groups: e.also ?? [],
            order: ei,
            weekly_prescriptions: Array.from({ length: end - start + 1 }, (_, w) => prescription(slotId, start + w, e.rx?.(start + w) ?? {})),
          };
        }),
      };
    }),
  };
}

const hyp = (sets: number, reps = "8-12", rir = "1-2 RIR"): ((w: number) => Rx) => () => ({
  sets,
  reps,
  rir,
  sets_grounding_note: "Share of this muscle's weekly sets, spread evenly across its sessions.",
  reps_citations: cites([502, 506, 512], 2),
  rir_citations: cites([504, 508], 1),
});

export function hypertrophyProgram(id: number): Program {
  const b = block(id, "Hypertrophy block", 1, 6, [
    {
      name: "Upper A",
      rest: null,
      exercises: [
        { name: "Barbell Bench Press", muscle: "chest", also: ["triceps", "front delts"], rx: hyp(3) },
        { name: "Chest-Supported Row", muscle: "upper back", also: ["lats", "rear delts", "biceps"], rx: hyp(3) },
        { name: "Cable Lateral Raise", muscle: "side delts", rx: hyp(3, "12-15") },
        { name: "Bayesian Cable Curl", muscle: "biceps", rx: hyp(2, "10-15", "0-1 RIR") },
        { name: "Overhead Triceps Extension", muscle: "triceps", rx: hyp(2, "10-15", "0-1 RIR") },
      ],
    },
    {
      name: "Lower A",
      rest: 0,
      exercises: [
        { name: "High-Bar Back Squat", muscle: "quadriceps", also: ["glutes"], rx: hyp(3, "6-10", "2-3 RIR") },
        { name: "Romanian Deadlift", muscle: "hamstrings", also: ["glutes", "lower back"], rx: hyp(3, "8-10", "2-3 RIR") },
        { name: "Leg Extension", muscle: "quadriceps", rx: hyp(3, "10-15", "0-1 RIR") },
        { name: "Standing Calf Raise", muscle: "calves", rx: hyp(3, "10-15") },
        { name: "Cable Crunch", muscle: "abs" },
      ],
    },
    {
      name: "Upper B",
      rest: 1,
      exercises: [
        { name: "Incline Dumbbell Press", muscle: "chest", also: ["front delts", "triceps"], rx: hyp(3) },
        { name: "Neutral-Grip Lat Pulldown", muscle: "lats", also: ["biceps", "upper back"], rx: hyp(3) },
        { name: "Seal Row", muscle: "upper back", also: ["rear delts"], rx: hyp(3) },
        { name: "Dumbbell Lateral Raise", muscle: "side delts", rx: hyp(3, "12-15") },
        { name: "Hammer Curl", muscle: "biceps", rx: hyp(2) },
        { name: "Triceps Pushdown", muscle: "triceps", rx: hyp(2, "10-15") },
      ],
    },
    {
      name: "Lower B",
      rest: 0,
      exercises: [
        { name: "Leg Press", muscle: "quadriceps", also: ["glutes"], rx: hyp(3, "8-12", "1-2 RIR") },
        { name: "Seated Leg Curl", muscle: "hamstrings", rx: hyp(3, "10-12") },
        { name: "Barbell Hip Thrust", muscle: "glutes", also: ["hamstrings"], rx: hyp(3) },
        { name: "Seated Calf Raise", muscle: "calves", rx: () => ({ sets: 0, reps: "", rir: "" }) },
      ],
    },
  ]);
  // Sets cite the muscle's volume; one value carries a note and no citation.
  for (const muscle of ["chest", "upper back", "lats", "quadriceps", "hamstrings", "glutes", "side delts", "biceps", "triceps", "calves"]) {
    b.muscle_group_volumes.push({
      id: newId(),
      muscle_group: muscle,
      weekly_sets: 12,
      grounding_note: "Preview fixture note: within the intermediate efficiency tier.",
      supporting_citations: cites([500, 502, 510, 514], 2),
    });
  }
  const calfRaise = b.day_templates[1].exercise_slots[3];
  calfRaise.weekly_prescriptions.forEach((p) => {
    p.rir_citations = [];
    p.rir_grounding_note = "Preview fixture note: no verified source states this effort for calves directly.";
  });
  return { id, user_id: 1, goal: "hypertrophy", name: "Upper/Lower · 4 days", volume_preference: "moderate", trained: false, include_deload: false, mesocycles: [b] };
}

const LOADS: Record<string, number> = { "8": 72.5, "6": 77.5, "4": 82.5 };

function dup(day: number): (w: number) => Rx {
  const reps = ["8", "6", "4"][day];
  return (w) => {
    const deload = w === 8;
    const base = LOADS[reps] + (w - 1) * 1;
    return {
      sets: deload ? 2 : 4,
      reps,
      rir: deload ? "~4 RIR" : "1-2 RIR",
      load: `${deload ? 49.5 : base}% 1RM`,
      sets_citations: cites([514, 515], 1),
      reps_citations: cites([510, 512], 1),
      load_citations: cites([500, 506, 514], 1),
      rir_citations: cites([508], 1),
      reps_grounding_note: deload ? "Deload week: lighter, same movements." : null,
      load_grounding_note: deload ? "60% of peak load, common practice for a deload week." : null,
      load_fit_note: w === 3 && day === 2 ? "Preview fixture: these reps, load and RIR sit at the edge of the reps-to-failure table." : null,
    };
  };
}

const accessory = (w: number): Rx => ({
  sets: w === 8 ? 2 : 3,
  reps: "8-12",
  rir: w === 8 ? "~4 RIR" : "1-2 RIR",
  load: "",
  reps_citations: cites([504], 1),
  rir_citations: cites([508, 510], 1),
});

export function strengthProgram(id: number): Program {
  const b = block(id, "Strength block", 1, 8, [
    {
      name: "Push",
      rest: null,
      exercises: [
        { name: "Barbell Bench Press", muscle: "chest", also: ["triceps", "front delts"], rx: dup(0) },
        { name: "Standing Overhead Press", muscle: "front delts", also: ["triceps"], rx: dup(1) },
        { name: "Dip", muscle: "triceps", also: ["chest"], rx: accessory },
      ],
    },
    {
      name: "Pull",
      rest: 1,
      exercises: [
        { name: "Conventional Deadlift", muscle: "hamstrings", also: ["glutes", "lower back"], rx: dup(0) },
        { name: "Pendlay Row", muscle: "upper back", also: ["lats", "biceps"], rx: dup(1) },
        { name: "Weighted Chin-up", muscle: "lats", also: ["biceps"], rx: dup(2) },
      ],
    },
    {
      name: "Legs",
      rest: 1,
      exercises: [
        { name: "Low-Bar Back Squat", muscle: "quadriceps", also: ["glutes"], rx: dup(2) },
        { name: "Bulgarian Split Squat", muscle: "glutes", also: ["quadriceps"], rx: accessory },
        { name: "Standing Calf Raise", muscle: "calves", rx: accessory },
      ],
    },
  ]);
  for (const muscle of ["chest", "front delts", "triceps", "hamstrings", "upper back", "lats", "quadriceps", "glutes", "calves"]) {
    const compound = !["triceps", "glutes", "calves"].includes(muscle);
    b.muscle_group_volumes.push({ id: newId(), muscle_group: muscle, weekly_sets: muscle === "calves" ? 3 : 4, grounding_note: null, supporting_citations: cites([514, 515, 500], 1) });
    b.muscle_group_frequencies.push({ id: newId(), muscle_group: muscle, frequency: 2, grounding_note: "Preview fixture note: frequency compared, no days added.", supporting_citations: cites([514, 502], 1) });
    b.progression_schemes.push({
      id: newId(),
      muscle_group: muscle,
      scheme: compound ? "undulating" : "constant",
      grounding_note: compound ? null : "Accessory lifts weren't periodized in the trials.",
      supporting_citations: compound ? cites([510, 512], 1) : [],
    });
  }
  return { id, user_id: 1, goal: "strength", name: "Push/Pull/Legs · 3 days", volume_preference: "moderate", trained: true, include_deload: true, mesocycles: [b] };
}

export function emptyProgram(id: number): Program {
  return { id, user_id: 1, goal: "hypertrophy", name: null, volume_preference: "moderate", trained: false, include_deload: false, mesocycles: [] };
}

export { block as buildBlock };
