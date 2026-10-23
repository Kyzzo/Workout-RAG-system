import type { DayTemplate, Mesocycle, Program } from "../../types";
import { isDeloadWeek, sortedBlocks, sortedDays } from "../format";
import { addDays, daysBetween, type ISODate } from "./dates";
import type { Regimen, SessionLog, SessionStatus } from "./types";

// The schedule is computed here, on the client, from the program tree, the
// regimen and the logs. Pure functions only: no React, no storage.

export type DisplayStatus = SessionStatus | "missed" | "scheduled";

export type Session = {
  key: string;
  programId: number;
  weekNumber: number;
  block: Mesocycle | null;
  day: DayTemplate | null;
  dayName: string;
  scheduledDate: ISODate;
  // Where the calendar shows it: the performed date when it was done on
  // another day, else the scheduled date.
  date: ISODate;
  moved: boolean;
  log: SessionLog | null;
  status: DisplayStatus;
  deload: boolean;
  // Logged, but its week or day no longer exists in the program.
  orphan: boolean;
};

export function sessionKey(programId: number, week: number, dayTemplateId: number | null): string {
  return `${programId}:${week}:${dayTemplateId}`;
}

export function programEndWeek(program: Program): number {
  return program.mesocycles.reduce((max, b) => Math.max(max, b.end_week), 0);
}

export function activeBlock(program: Program, week: number): Mesocycle | null {
  return program.mesocycles.find((b) => b.start_week <= week && week <= b.end_week) ?? null;
}

export function schedulable(program: Program | null | undefined): boolean {
  return !!program && program.mesocycles.some((b) => b.day_templates.length > 0);
}

export function hasExercises(program: Program | null | undefined): boolean {
  return !!program && program.mesocycles.some((b) => b.day_templates.some((d) => d.exercise_slots.length > 0));
}

// ---- Day offsets (0-6) within a program week ----

// From the program's own rest spacing: each day lands its rest days plus
// one after the previous session.
export function deriveOffsets(days: DayTemplate[]): { offsets: number[]; derivable: boolean } {
  const sorted = [...days].sort((a, b) => a.order - b.order);
  const offsets: number[] = [];
  sorted.forEach((day, i) => {
    offsets.push(i === 0 ? 0 : offsets[i - 1] + (day.rest_days_before ?? NaN) + 1);
  });
  const n = sorted.length;
  const derivable =
    n > 0 &&
    n <= 7 &&
    sorted.every((d, i) => i === 0 || d.rest_days_before !== null) &&
    offsets.every((o) => Number.isFinite(o)) &&
    offsets[n - 1] <= 6;
  return { offsets, derivable };
}

// An even spread like the backend's: base, extra = divmod(7 - n, n); the gap
// before day i (i >= 1) is base + (i < extra ? 1 : 0), and gap 0 is the wrap
// from the last session back to the first. Past 7 days, dates repeat.
export function evenOffsets(n: number): number[] {
  if (n <= 0) return [];
  const base = Math.floor((7 - n) / n);
  const extra = 7 - n - base * n;
  const offsets = [0];
  for (let i = 1; i < n; i++) offsets.push(offsets[i - 1] + base + (i < extra ? 1 : 0) + 1);
  return offsets.map((o) => Math.max(0, Math.min(6, o)));
}

export function defaultOffsets(block: Mesocycle): { offsets: Map<number, number>; derivable: boolean } {
  const days = sortedDays(block);
  const derived = deriveOffsets(days);
  const chosen = derived.derivable ? derived.offsets : evenOffsets(days.length);
  return { offsets: new Map(days.map((d, i) => [d.id, chosen[i]])), derivable: derived.derivable };
}

export function blockOffsets(block: Mesocycle, overrides: Record<number, number>): Map<number, number> {
  const { offsets } = defaultOffsets(block);
  for (const day of block.day_templates) {
    const o = overrides[day.id];
    if (typeof o === "number" && o >= 0 && o <= 6) offsets.set(day.id, o);
  }
  return offsets;
}

// Blocks whose days can't be placed from rest spacing and have no confirmed
// placement yet: the user confirms or adjusts an even spread first.
export function blocksNeedingPlacement(program: Program, overrides: Record<number, number>): Mesocycle[] {
  return sortedBlocks(program).filter(
    (b) => b.day_templates.length > 0 && !defaultOffsets(b).derivable && b.day_templates.some((d) => overrides[d.id] === undefined),
  );
}

// ---- The schedule ----

export function programEndDate(program: Program, startDate: ISODate): ISODate | null {
  const end = programEndWeek(program);
  return end ? addDays(startDate, 7 * end - 1) : null;
}

export function weekOfDate(startDate: ISODate, date: ISODate): number {
  return Math.floor(daysBetween(startDate, date) / 7) + 1;
}

export function buildSessions(
  program: Program,
  regimen: Regimen,
  logs: Record<string, SessionLog>,
  today: ISODate,
): Session[] {
  const sessions: Session[] = [];
  const seen = new Set<string>();
  const end = programEndWeek(program);
  const offsetCache = new Map<number, Map<number, number>>();

  for (let week = 1; week <= end; week++) {
    const block = activeBlock(program, week);
    if (!block) continue; // a gap between blocks: nothing scheduled
    let offsets = offsetCache.get(block.id);
    if (!offsets) {
      offsets = blockOffsets(block, regimen.dayOffsets);
      offsetCache.set(block.id, offsets);
    }
    for (const day of sortedDays(block)) {
      const key = sessionKey(program.id, week, day.id);
      seen.add(key);
      const log = logs[key] ?? null;
      const computed = addDays(regimen.startDate, 7 * (week - 1) + (offsets.get(day.id) ?? 0));
      // A logged session keeps the date it was logged against, even if the
      // start date or offsets changed afterwards.
      const scheduledDate = log ? log.scheduledDate : computed;
      const date = log?.performedDate ?? scheduledDate;
      sessions.push({
        key,
        programId: program.id,
        weekNumber: week,
        block,
        day,
        dayName: day.name,
        scheduledDate,
        date,
        moved: !!log?.performedDate && log.performedDate !== log.scheduledDate,
        log,
        status: log ? log.status : scheduledDate < today ? "missed" : "scheduled",
        deload: isDeloadWeek(program, block, week),
        orphan: false,
      });
    }
  }

  // Logs whose week or day is gone stay visible as history.
  for (const log of Object.values(logs)) {
    if (log.programId !== program.id || seen.has(log.key)) continue;
    const date = log.performedDate ?? log.scheduledDate;
    sessions.push({
      key: log.key,
      programId: program.id,
      weekNumber: log.weekNumber,
      block: program.mesocycles.find((b) => b.id === log.mesocycleId) ?? null,
      day: null,
      dayName: log.dayName,
      scheduledDate: log.scheduledDate,
      date,
      moved: !!log.performedDate && log.performedDate !== log.scheduledDate,
      log,
      status: log.status,
      deload: false,
      orphan: true,
    });
  }

  return sessions.sort((a, b) => (a.date === b.date ? (a.day?.order ?? 99) - (b.day?.order ?? 99) : a.date < b.date ? -1 : 1));
}

export function sessionsByDate(sessions: Session[]): Map<ISODate, Session[]> {
  const map = new Map<ISODate, Session[]>();
  for (const s of sessions) {
    const list = map.get(s.date);
    if (list) list.push(s);
    else map.set(s.date, [s]);
  }
  return map;
}

// Today's session, or else the next one coming up.
export function focusSession(sessions: Session[], today: ISODate): Session | null {
  return sessions.find((s) => s.date === today) ?? sessions.find((s) => s.date > today && !s.orphan) ?? null;
}

export function nextAfter(sessions: Session[], date: ISODate): Session | null {
  return sessions.find((s) => s.date > date && !s.orphan) ?? null;
}

export type TrackerSummary = {
  totalWeeks: number;
  phase: "before" | "during" | "after";
  currentWeek: number; // clamped to 1..totalWeeks
  daysUntilStart: number;
  week: { done: number; total: number };
  adherence: { done: number; due: number };
  missed: number;
  streak: number;
};

export function summarize(sessions: Session[], program: Program, regimen: Regimen, today: ISODate): TrackerSummary {
  const totalWeeks = programEndWeek(program);
  const raw = weekOfDate(regimen.startDate, today);
  const phase = today < regimen.startDate ? "before" : raw > totalWeeks ? "after" : "during";
  const currentWeek = Math.min(Math.max(raw, 1), Math.max(totalWeeks, 1));
  const live = sessions.filter((s) => !s.orphan);
  const thisWeek = live.filter((s) => s.weekNumber === currentWeek);
  // Due: everything dated before today, plus today's once it's logged (an
  // untouched session today isn't missed yet).
  const due = sessions.filter((s) => s.date < today || (s.date === today && s.log));
  const done = due.filter((s) => s.status === "completed" || s.status === "partial");
  let streak = 0;
  for (let i = due.length - 1; i >= 0; i--) {
    const st = due[i].status;
    if (st === "completed" || st === "partial") streak++;
    else break;
  }
  return {
    totalWeeks,
    phase,
    currentWeek,
    daysUntilStart: Math.max(0, daysBetween(today, regimen.startDate)),
    week: { done: thisWeek.filter((s) => s.status === "completed").length, total: thisWeek.length },
    adherence: { done: done.length, due: due.length },
    missed: sessions.filter((s) => s.status === "missed").length,
    streak,
  };
}
