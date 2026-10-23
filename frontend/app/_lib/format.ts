import type { ExerciseSlot, Mesocycle, Program, WeeklyPrescription } from "../types";

export const CANONICAL_MUSCLES = [
  "chest", "lats", "upper back", "lower back", "front delts", "side delts", "rear delts",
  "biceps", "triceps", "quadriceps", "hamstrings", "glutes", "calves", "abs",
];

export const SCHEME_LABELS: Record<string, string> = {
  linear: "linear",
  undulating: "daily undulating",
  constant: "none scheduled (accessories only)",
};

export function schemeLabel(scheme: string): string {
  return SCHEME_LABELS[scheme] ?? scheme;
}

export function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

// Display only: "8-12" reads as "8–12". Never used for anything sent to the
// server (questions and chat suggestions are cache keys).
export function prettyRange(text: string): string {
  return text.replace(/(\d)\s*-\s*(\d)/g, "$1–$2");
}

export function isPlaceholder(p: WeeklyPrescription | null | undefined): boolean {
  return !p || (p.sets === 0 && !p.reps && !p.load && !p.rir);
}

export function setsText(sets: number): string {
  return sets === 0 ? "—" : plural(sets, "set");
}

export function samePrescription(a: WeeklyPrescription, b: WeeklyPrescription): boolean {
  return a.sets === b.sets && a.reps === b.reps && a.load === b.load && a.rir === b.rir;
}

export function weeksOf(slot: ExerciseSlot): WeeklyPrescription[] {
  return [...slot.weekly_prescriptions].sort((a, b) => a.week_number - b.week_number);
}

export function prescriptionFor(slot: ExerciseSlot, week: number): WeeklyPrescription | null {
  return slot.weekly_prescriptions.find((p) => p.week_number === week) ?? null;
}

// True when one "every week" row can stand for the whole exercise.
export function sameEveryWeek(slot: ExerciseSlot, goal: string): boolean {
  if (goal === "strength") return false;
  const weeks = weeksOf(slot);
  return weeks.length > 0 && weeks.every((p) => samePrescription(p, weeks[0]));
}

export type Row = { kind: "every"; p: WeeklyPrescription } | { kind: "week"; p: WeeklyPrescription };

// One "every week" row when nothing differs (hypertrophy), else a row per
// week - a difference between weeks is never hidden.
export function rowsToShow(slot: ExerciseSlot, goal: string): Row[] {
  const weeks = weeksOf(slot);
  if (sameEveryWeek(slot, goal)) return [{ kind: "every", p: slot.weekly_prescriptions[0] ?? weeks[0] }];
  return weeks.map((p) => ({ kind: "week", p }));
}

export function blockSlots(block: Mesocycle): ExerciseSlot[] {
  return sortedDays(block).flatMap((d) => sortedSlots(d.exercise_slots));
}

export function sortedDays(block: Mesocycle) {
  return [...block.day_templates].sort((a, b) => a.order - b.order);
}

export function sortedSlots(slots: ExerciseSlot[]) {
  return [...slots].sort((a, b) => a.order - b.order);
}

export function sortedBlocks(program: Program) {
  return [...program.mesocycles].sort((a, b) => a.start_week - b.start_week);
}

export function blockWeekNumbers(block: Mesocycle): number[] {
  return Array.from({ length: block.end_week - block.start_week + 1 }, (_, i) => block.start_week + i);
}

// Any exercise whose weeks differ (always the case for strength).
export function blockVaries(block: Mesocycle, goal: string): boolean {
  if (goal === "strength") return true;
  return blockSlots(block).some((s) => !sameEveryWeek(s, goal));
}

export function blockHasPlaceholder(block: Mesocycle): boolean {
  return blockSlots(block).some((s) => s.weekly_prescriptions.some((p) => isPlaceholder(p)));
}

export function weekRange(block: Mesocycle): string {
  return block.start_week === block.end_week
    ? `Week ${block.start_week}`
    : `Weeks ${block.start_week}–${block.end_week}`;
}

export function leadingNumber(text: string | number): number {
  return typeof text === "number" ? text : parseFloat(text);
}

export function direction(prev: string | number, cur: string | number): "up" | "down" | null {
  const a = leadingNumber(prev);
  const b = leadingNumber(cur);
  if (Number.isNaN(a) || Number.isNaN(b) || a === b) return null;
  return b > a ? "up" : "down";
}

export function isDeloadWeek(program: Pick<Program, "goal" | "include_deload">, block: Mesocycle, week: number): boolean {
  return (
    program.goal === "strength" &&
    program.include_deload &&
    block.end_week - block.start_week + 1 >= 3 &&
    week === block.end_week
  );
}

// "<sets> sets, <reps|n/a> reps[, <load>], <rir|effort n/a>" - the values
// as the chat history summarises them.
export function valuesSentence(p: WeeklyPrescription): string {
  const parts = [`${p.sets} sets`, `${p.reps || "n/a"} reps`];
  if (p.load) parts.push(p.load);
  parts.push(p.rir || "effort n/a");
  return parts.join(", ");
}

// "Pelland et al. 2025 · meta-analysis · ..." -> the paper, then its tags.
export function paperOf(title: string): string {
  const i = title.indexOf(" · ");
  return i === -1 ? title : title.slice(0, i);
}

export function titleDetails(title: string): string {
  const i = title.indexOf(" · ");
  return i === -1 ? "" : title.slice(i + 3);
}

export function findPrescription(program: Program | null | undefined, id: number): WeeklyPrescription | null {
  if (!program) return null;
  for (const block of program.mesocycles)
    for (const day of block.day_templates)
      for (const slot of day.exercise_slots)
        for (const p of slot.weekly_prescriptions) if (p.id === id) return p;
  return null;
}

export function locatePrescription(program: Program | null | undefined, id: number) {
  if (!program) return null;
  for (const block of program.mesocycles)
    for (const day of block.day_templates)
      for (const slot of day.exercise_slots)
        for (const p of slot.weekly_prescriptions) if (p.id === id) return { block, day, slot, p };
  return null;
}

export function countValueWeeks(slots: ExerciseSlot[]): number {
  return slots.reduce((n, s) => n + s.weekly_prescriptions.filter((p) => !isPlaceholder(p)).length, 0);
}
