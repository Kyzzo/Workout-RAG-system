import type { ExerciseSlot, WeeklyPrescription } from "../../types";
import { prescriptionFor, sortedSlots } from "../format";
import type { ISODate } from "./dates";
import type { Session } from "./schedule";
import type { ExerciseEntry, Prescribed, SessionLog, SessionStatus } from "./types";

// One row of a session's checklist. A logged session shows its snapshot;
// an unlogged one reads the live program.
export type ChecklistItem = {
  id: string;
  slot: ExerciseSlot | null; // live exercise, when it still exists
  prescription: WeeklyPrescription | null; // live, for this week
  name: string;
  muscle: string;
  secondary: string[];
  prescribed: Prescribed;
  placeholder: boolean;
  marker: "added" | "removed" | null;
  done: boolean;
  setsDone: number;
  achieved?: { weight?: string; reps?: string };
  entryIndex: number | null; // position in log.entries, if logged
};

function prescribedOf(p: WeeklyPrescription | null): Prescribed {
  return p ? { sets: p.sets, reps: p.reps, load: p.load, rir: p.rir } : { sets: 0, reps: "", load: "", rir: "" };
}

export function isPlaceholderPrescribed(p: Prescribed): boolean {
  return p.sets === 0 && !p.reps && !p.load && !p.rir;
}

function liveItem(slot: ExerciseSlot, week: number, marker: ChecklistItem["marker"]): ChecklistItem {
  const prescription = prescriptionFor(slot, week);
  const prescribed = prescribedOf(prescription);
  return {
    id: `slot:${slot.id}`,
    slot,
    prescription,
    name: slot.exercise_name,
    muscle: slot.muscle_group,
    secondary: slot.secondary_muscle_groups,
    prescribed,
    placeholder: isPlaceholderPrescribed(prescribed),
    marker,
    done: false,
    setsDone: 0,
    entryIndex: null,
  };
}

export function checklistItems(session: Session): ChecklistItem[] {
  const liveSlots = session.day ? sortedSlots(session.day.exercise_slots) : [];
  if (!session.log) return liveSlots.map((s) => liveItem(s, session.weekNumber, null));

  const items: ChecklistItem[] = session.log.entries.map((entry, i) => {
    const slot = liveSlots.find((s) => s.id === entry.exerciseSlotId) ?? null;
    return {
      id: slot ? `slot:${slot.id}` : `entry:${i}`,
      slot,
      prescription: slot ? prescriptionFor(slot, session.weekNumber) : null,
      name: entry.exerciseName,
      muscle: entry.muscleGroup,
      secondary: slot?.secondary_muscle_groups ?? [],
      prescribed: entry.prescribed,
      placeholder: isPlaceholderPrescribed(entry.prescribed),
      marker: slot ? null : "removed",
      done: entry.done,
      setsDone: entry.setsDone ?? (entry.done ? entry.prescribed.sets : 0),
      achieved: entry.achieved,
      entryIndex: i,
    };
  });
  const logged = new Set(session.log.entries.map((e) => e.exerciseSlotId));
  for (const slot of liveSlots) if (!logged.has(slot.id)) items.push(liveItem(slot, session.weekNumber, "added"));
  return items;
}

function entryOf(item: ChecklistItem): ExerciseEntry {
  return {
    exerciseSlotId: item.slot?.id ?? null,
    weeklyPrescriptionId: item.prescription?.id ?? null,
    exerciseName: item.name,
    muscleGroup: item.muscle,
    prescribed: item.prescribed,
    done: item.done,
    setsDone: item.setsDone,
    ...(item.achieved ? { achieved: item.achieved } : {}),
  };
}

export type ChecklistChange =
  | { kind: "sets"; itemId: string; setsDone: number }
  | { kind: "toggle"; itemId: string; done: boolean }
  | { kind: "all" }
  | { kind: "clear" }
  | { kind: "skip"; skipped: boolean }
  | { kind: "note"; notes: string }
  | { kind: "performed"; date: ISODate }
  | { kind: "achieved"; itemId: string; achieved: { weight?: string; reps?: string } };

function statusFor(entries: ExerciseEntry[]): SessionStatus | null {
  const done = entries.filter((e) => e.done).length;
  if (done === 0) return null;
  return done === entries.length ? "completed" : "partial";
}

// The log after a change, or null when the session ends up with nothing
// checked and isn't skipped (the log is deleted). Exercises "added since"
// join the log only once they're touched.
export function applyChange(session: Session, items: ChecklistItem[], change: ChecklistChange, now: string): SessionLog | null {
  const base = session.log;
  // First log of a session: snapshot every live exercise as prescribed now.
  let entries: ExerciseEntry[] = base ? base.entries.map((e) => ({ ...e })) : items.map(entryOf);

  const indexFor = (itemId: string): number => {
    const item = items.find((i) => i.id === itemId);
    if (!item) return -1;
    if (base && item.entryIndex !== null) return item.entryIndex;
    if (!base) return items.indexOf(item);
    entries.push(entryOf(item)); // touched "added since" exercise joins the log
    return entries.length - 1;
  };

  let status: SessionStatus | null = base?.status ?? null;
  let performedDate = base?.performedDate ?? null;
  let notes = base?.notes;

  switch (change.kind) {
    case "toggle": {
      const i = indexFor(change.itemId);
      if (i < 0) return base;
      entries[i] = { ...entries[i], done: change.done, setsDone: change.done ? entries[i].prescribed.sets : 0 };
      status = statusFor(entries);
      break;
    }
    case "sets": {
      const i = indexFor(change.itemId);
      if (i < 0) return base;
      const sets = entries[i].prescribed.sets;
      const setsDone = Math.max(0, Math.min(sets, change.setsDone));
      entries[i] = { ...entries[i], setsDone, done: sets > 0 && setsDone === sets };
      status = statusFor(entries);
      break;
    }
    case "all": {
      for (const item of items) if (item.marker === "added" && base) entries.push(entryOf(item));
      entries = entries.map((e) => ({ ...e, done: true, setsDone: e.prescribed.sets }));
      status = "completed";
      break;
    }
    case "clear":
      return null;
    case "skip":
      status = change.skipped ? "skipped" : statusFor(entries);
      break;
    case "note":
      notes = change.notes;
      break;
    case "performed":
      performedDate = change.date === session.scheduledDate ? null : change.date;
      break;
    case "achieved": {
      const i = indexFor(change.itemId);
      if (i < 0) return base;
      entries[i] = { ...entries[i], achieved: change.achieved };
      break;
    }
  }

  if (!status) return null;
  return {
    key: session.key,
    programId: session.programId,
    mesocycleId: session.block?.id ?? base?.mesocycleId ?? null,
    dayTemplateId: session.day?.id ?? base?.dayTemplateId ?? null,
    dayName: base?.dayName ?? session.dayName,
    weekNumber: session.weekNumber,
    scheduledDate: session.scheduledDate,
    performedDate,
    status,
    entries,
    ...(notes ? { notes } : {}),
    updatedAt: now,
  };
}

// The most recent earlier logged entry for the same exercise with something
// recorded - for "last time" alongside the weight/reps inputs.
export function previousAchieved(
  logs: SessionLog[],
  session: Session,
  item: ChecklistItem,
): { date: ISODate; weight?: string; reps?: string } | null {
  let best: { date: ISODate; weight?: string; reps?: string } | null = null;
  for (const log of logs) {
    if (log.key === session.key) continue;
    const date = log.performedDate ?? log.scheduledDate;
    if (date >= session.date) continue;
    const entry = log.entries.find((e) =>
      item.slot ? e.exerciseSlotId === item.slot.id : e.exerciseName === item.name,
    );
    if (!entry?.achieved || (!entry.achieved.weight && !entry.achieved.reps)) continue;
    if (!best || date > best.date) best = { date, ...entry.achieved };
  }
  return best;
}
