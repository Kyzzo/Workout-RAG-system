import type { Api } from "../../useApi";
import type { ISODate } from "./dates";
import type { ExerciseEntry, Regimen, SessionLog, TrackerStore } from "./types";

// ---- Local adapter: this device only, one key per Clerk user so accounts
// sharing a browser never see each other's tracking. ----

const VERSION = 1;

type Stored = { version: number; regimen: Regimen | null; logs: Record<string, SessionLog> };

export function localKey(userId: string) {
  return `citeset:tracker:v1:${userId}`;
}

function empty(): Stored {
  return { version: VERSION, regimen: null, logs: {} };
}

export class LocalTrackerStore implements TrackerStore {
  readonly kind = "local" as const;
  constructor(private readonly userId: string) {}

  private read(): Stored {
    try {
      const raw = window.localStorage.getItem(localKey(this.userId));
      if (!raw) return empty();
      const data = JSON.parse(raw) as Partial<Stored>;
      // Future versions migrate here; anything unreadable starts empty
      // rather than breaking the app.
      if (data.version !== VERSION || typeof data.logs !== "object" || data.logs === null) return empty();
      return { version: VERSION, regimen: data.regimen ?? null, logs: data.logs };
    } catch {
      return empty();
    }
  }

  private write(data: Stored) {
    try {
      window.localStorage.setItem(localKey(this.userId), JSON.stringify(data));
    } catch {
      throw new Error("Couldn't save on this device - browser storage is full or blocked (private browsing can do this).");
    }
  }

  async getRegimen() {
    return this.read().regimen;
  }

  async setRegimen(regimen: Regimen) {
    const data = this.read();
    data.regimen = regimen;
    this.write(data);
    return regimen;
  }

  async clearRegimen() {
    const data = this.read();
    data.regimen = null;
    this.write(data);
  }

  async listLogs(programId: number, from: ISODate, to: ISODate) {
    const inRange = (d: ISODate | null) => !!d && d >= from && d <= to;
    return Object.values(this.read().logs).filter(
      (l) => l.programId === programId && (inRange(l.scheduledDate) || inRange(l.performedDate)),
    );
  }

  async saveLog(log: SessionLog) {
    const data = this.read();
    data.logs[log.key] = log;
    this.write(data);
    return log;
  }

  async deleteLog(key: string) {
    const data = this.read();
    delete data.logs[key];
    this.write(data);
  }

  async deleteProgramData(programId: number) {
    const data = this.read();
    for (const [key, log] of Object.entries(data.logs)) if (log.programId === programId) delete data.logs[key];
    if (data.regimen?.programId === programId) data.regimen = null;
    this.write(data);
  }

  // For the one-time import once tracking moves to the server.
  snapshot(): { regimen: Regimen | null; logs: SessionLog[] } {
    const data = this.read();
    return { regimen: data.regimen, logs: Object.values(data.logs) };
  }
}

// ---- Server adapter, for the proposed /tracker endpoints (spec Appendix
// C). Selected with NEXT_PUBLIC_TRACKER_BACKEND=api once they exist. ----

type ApiRegimen = { program_id: number; start_date: string; day_offsets: Record<string, number>; updated_at: string };
type ApiEntry = {
  exercise_slot_id: number | null;
  weekly_prescription_id: number | null;
  exercise_name: string;
  muscle_group: string;
  prescribed: { sets: number; reps: string; load: string; rir: string };
  done: boolean;
  sets_done?: number | null;
  achieved?: { weight?: string; reps?: string } | null;
};
type ApiLog = {
  key?: string;
  program_id: number;
  mesocycle_id: number | null;
  day_template_id: number | null;
  day_name: string;
  week_number: number;
  scheduled_date: string;
  performed_date: string | null;
  status: SessionLog["status"];
  entries: ApiEntry[];
  notes?: string | null;
  updated_at: string;
};

function regimenFromApi(r: ApiRegimen): Regimen {
  const dayOffsets: Record<number, number> = {};
  for (const [id, o] of Object.entries(r.day_offsets ?? {})) dayOffsets[Number(id)] = o;
  return { programId: r.program_id, startDate: r.start_date, dayOffsets, updatedAt: r.updated_at };
}

function entryToApi(e: ExerciseEntry): ApiEntry {
  return {
    exercise_slot_id: e.exerciseSlotId,
    weekly_prescription_id: e.weeklyPrescriptionId,
    exercise_name: e.exerciseName,
    muscle_group: e.muscleGroup,
    prescribed: e.prescribed,
    done: e.done,
    sets_done: e.setsDone ?? null,
    achieved: e.achieved ?? null,
  };
}

function entryFromApi(e: ApiEntry): ExerciseEntry {
  return {
    exerciseSlotId: e.exercise_slot_id,
    weeklyPrescriptionId: e.weekly_prescription_id,
    exerciseName: e.exercise_name,
    muscleGroup: e.muscle_group,
    prescribed: e.prescribed,
    done: e.done,
    ...(e.sets_done != null ? { setsDone: e.sets_done } : {}),
    ...(e.achieved ? { achieved: e.achieved } : {}),
  };
}

function logToApi(l: SessionLog): ApiLog {
  return {
    key: l.key,
    program_id: l.programId,
    mesocycle_id: l.mesocycleId,
    day_template_id: l.dayTemplateId,
    day_name: l.dayName,
    week_number: l.weekNumber,
    scheduled_date: l.scheduledDate,
    performed_date: l.performedDate,
    status: l.status,
    entries: l.entries.map(entryToApi),
    notes: l.notes ?? null,
    updated_at: l.updatedAt,
  };
}

function logFromApi(l: ApiLog): SessionLog {
  return {
    key: l.key ?? `${l.program_id}:${l.week_number}:${l.day_template_id}`,
    programId: l.program_id,
    mesocycleId: l.mesocycle_id,
    dayTemplateId: l.day_template_id,
    dayName: l.day_name,
    weekNumber: l.week_number,
    scheduledDate: l.scheduled_date,
    performedDate: l.performed_date,
    status: l.status,
    entries: l.entries.map(entryFromApi),
    ...(l.notes ? { notes: l.notes } : {}),
    updatedAt: l.updated_at,
  };
}

function keyPath(key: string) {
  const [programId, week, dayId] = key.split(":");
  return `/tracker/sessions/${programId}/${week}/${dayId}`;
}

export class ApiTrackerStore implements TrackerStore {
  readonly kind = "api" as const;
  constructor(private readonly api: Api) {}

  async getRegimen() {
    const r = await this.api<ApiRegimen | null>("/tracker/regimen");
    return r ? regimenFromApi(r) : null;
  }

  async setRegimen(regimen: Regimen) {
    const r = await this.api<ApiRegimen>("/tracker/regimen", {
      method: "PUT",
      body: { program_id: regimen.programId, start_date: regimen.startDate, day_offsets: regimen.dayOffsets },
    });
    return regimenFromApi(r);
  }

  async clearRegimen() {
    await this.api<void>("/tracker/regimen", { method: "DELETE" });
  }

  async listLogs(programId: number, from: ISODate, to: ISODate) {
    const q = new URLSearchParams({ program_id: String(programId), from, to });
    const logs = await this.api<ApiLog[]>(`/tracker/sessions?${q}`);
    return logs.map(logFromApi);
  }

  async saveLog(log: SessionLog) {
    return logFromApi(await this.api<ApiLog>(keyPath(log.key), { method: "PUT", body: logToApi(log) }));
  }

  async deleteLog(key: string) {
    await this.api<void>(keyPath(key), { method: "DELETE" });
  }

  async deleteProgramData(programId: number) {
    // The server deletes a program's regimen and logs with the program.
    const regimen = await this.getRegimen();
    if (regimen?.programId === programId) await this.clearRegimen();
  }
}

export const TRACKER_BACKEND: "local" | "api" = process.env.NEXT_PUBLIC_TRACKER_BACKEND === "api" ? "api" : "local";

export function createTrackerStore(userId: string, api: Api): TrackerStore {
  return TRACKER_BACKEND === "api" ? new ApiTrackerStore(api) : new LocalTrackerStore(userId);
}

// Copies this device's tracking to the server once. The server's regimen is
// kept if it has one; each local session log is upserted.
export async function importLocalData(userId: string, store: TrackerStore): Promise<number> {
  const local = new LocalTrackerStore(userId).snapshot();
  if (local.regimen && !(await store.getRegimen())) await store.setRegimen(local.regimen);
  let imported = 0;
  for (const log of local.logs) {
    await store.saveLog(log);
    imported++;
  }
  return imported;
}
