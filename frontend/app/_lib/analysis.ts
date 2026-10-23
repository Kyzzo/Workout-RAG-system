import type { Mesocycle, MuscleGroupFrequency, MuscleGroupVolume, ProgressionScheme } from "../types";
import { weeksOf } from "./format";

// Weekly sets by muscle for one block (delivered against the research
// target), and the de-duplicated details shown under it.

export type MuscleRow = {
  muscle: string;
  // Trained only as half sets from other lifts: no research target.
  indirect: boolean;
  delivered: number;
  target: number | null;
  volume: MuscleGroupVolume | null;
  frequency: MuscleGroupFrequency | null;
  scheme: ProgressionScheme | null;
  daysTraining: number;
  below: boolean;
  avgPerSession: number | null;
};

export type BlockAnalysis = {
  rows: MuscleRow[];
  belowCount: number;
  targetRange: [number, number] | null;
  daysRange: [number, number] | null;
  // Set when every primary muscle shares it (same value, same citation count).
  sharedVolume: MuscleGroupVolume | null;
  sharedFrequency: MuscleGroupFrequency | null;
  // The most common days-trained value, with at most two exceptions named.
  // null: too many exceptions, so days are shown per muscle.
  commonDays: { days: number; exceptions: { muscle: string; days: number }[] } | null;
  maxScale: number;
};

export function analyseBlock(block: Mesocycle, goal: string): BlockAnalysis {
  const slots = block.day_templates.flatMap((d) => d.exercise_slots);
  const primary = [...new Set(slots.map((s) => s.muscle_group))].sort();
  const indirect = [...new Set(slots.flatMap((s) => s.secondary_muscle_groups))]
    .filter((m) => !primary.includes(m))
    .sort();

  const delivered = (group: string) =>
    Math.round(
      slots.reduce((sum, s) => {
        const first = weeksOf(s)[0];
        const sets = first?.sets ?? 0;
        if (s.muscle_group === group) return sum + sets;
        if (s.secondary_muscle_groups.includes(group)) return sum + sets / 2;
        return sum;
      }, 0),
    );

  const daysTraining = (group: string) =>
    block.day_templates.filter((d) => d.exercise_slots.some((s) => s.muscle_group === group)).length;

  const rows: MuscleRow[] = [
    ...primary.map((muscle) => {
      const volume = block.muscle_group_volumes.find((v) => v.muscle_group === muscle) ?? null;
      const d = delivered(muscle);
      const days = daysTraining(muscle);
      const target = volume ? volume.weekly_sets : null;
      return {
        muscle,
        indirect: false,
        delivered: d,
        target,
        volume,
        frequency: block.muscle_group_frequencies.find((f) => f.muscle_group === muscle) ?? null,
        scheme: block.progression_schemes.find((s) => s.muscle_group === muscle) ?? null,
        daysTraining: days,
        below: target !== null && d < target,
        avgPerSession: goal === "strength" || days === 0 ? null : Math.round(d / days),
      };
    }),
    ...indirect.map((muscle) => ({
      muscle,
      indirect: true,
      delivered: delivered(muscle),
      target: null,
      volume: null,
      frequency: null,
      scheme: null,
      daysTraining: 0,
      below: false,
      avgPerSession: null,
    })),
  ];

  const primaryRows = rows.filter((r) => !r.indirect);
  const targets = primaryRows.flatMap((r) => (r.target === null ? [] : [r.target]));
  const days = primaryRows.map((r) => r.daysTraining);

  const sharedVolume = (() => {
    const vols = primaryRows.map((r) => r.volume);
    const first = vols[0];
    if (!first || vols.some((v) => !v)) return null;
    const same = vols.every(
      (v) => v!.weekly_sets === first.weekly_sets && v!.supporting_citations.length === first.supporting_citations.length,
    );
    return same && vols.length > 1 ? first : null;
  })();

  const sharedFrequency = (() => {
    const freqs = primaryRows.map((r) => r.frequency);
    const first = freqs[0];
    if (!first || freqs.some((f) => !f)) return null;
    const same = freqs.every(
      (f) => f!.frequency === first.frequency && f!.supporting_citations.length === first.supporting_citations.length,
    );
    return same && freqs.length > 1 ? first : null;
  })();

  const commonDays = (() => {
    if (!primaryRows.length) return null;
    const counts = new Map<number, number>();
    for (const d of days) counts.set(d, (counts.get(d) ?? 0) + 1);
    const [mode] = [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0];
    const exceptions = primaryRows.filter((r) => r.daysTraining !== mode).map((r) => ({ muscle: r.muscle, days: r.daysTraining }));
    return exceptions.length <= 2 ? { days: mode, exceptions } : null;
  })();

  const maxScale = Math.max(1, ...rows.map((r) => r.delivered), ...targets);

  return {
    rows,
    belowCount: primaryRows.filter((r) => r.below).length,
    targetRange: targets.length ? [Math.min(...targets), Math.max(...targets)] : null,
    daysRange: days.length ? [Math.min(...days), Math.max(...days)] : null,
    sharedVolume,
    sharedFrequency,
    commonDays,
    maxScale,
  };
}

export function rangeText([lo, hi]: [number, number]): string {
  return lo === hi ? `${lo}` : `${lo}–${hi}`;
}
