import type { ISODate } from "./dates";

export type { ISODate };

export type Regimen = {
  programId: number;
  startDate: ISODate; // program week 1 begins here
  dayOffsets: Record<number, number>; // dayTemplateId -> 0..6 (overrides; absent = derived)
  updatedAt: string; // ISO timestamp
};

export type SessionStatus = "completed" | "partial" | "skipped";

export type Prescribed = { sets: number; reps: string; load: string; rir: string };

export type ExerciseEntry = {
  exerciseSlotId: number | null; // null once the exercise is deleted
  weeklyPrescriptionId: number | null;
  exerciseName: string; // snapshot
  muscleGroup: string; // snapshot
  prescribed: Prescribed; // snapshot
  done: boolean;
  setsDone?: number;
  achieved?: { weight?: string; reps?: string };
};

export type SessionLog = {
  key: string; // `${programId}:${weekNumber}:${dayTemplateId}`
  programId: number;
  mesocycleId: number | null;
  dayTemplateId: number | null;
  dayName: string; // snapshot
  weekNumber: number;
  scheduledDate: ISODate;
  performedDate: ISODate | null;
  status: SessionStatus;
  entries: ExerciseEntry[];
  notes?: string;
  updatedAt: string;
};

export interface TrackerStore {
  readonly kind: "local" | "api";
  getRegimen(): Promise<Regimen | null>;
  setRegimen(regimen: Regimen): Promise<Regimen>;
  clearRegimen(): Promise<void>;
  listLogs(programId: number, from: ISODate, to: ISODate): Promise<SessionLog[]>; // by scheduled or performed date
  saveLog(log: SessionLog): Promise<SessionLog>; // upsert by key
  deleteLog(key: string): Promise<void>; // "clear" with nothing checked deletes the log
  deleteProgramData(programId: number): Promise<void>;
}
