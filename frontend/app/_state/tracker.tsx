"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createTrackerStore } from "../_lib/tracker/store";
import type { Regimen, SessionLog, TrackerStore } from "../_lib/tracker/types";
import type { Program } from "../types";
import { errorMessage } from "../useApi";
import { useApp } from "./app";
import { useSession } from "./session";

const ALL_FROM = "0001-01-01";
const ALL_TO = "9999-12-31";

type TrackerValue = {
  store: TrackerStore | null;
  ready: boolean;
  loadError: string | null;
  regimen: Regimen | null;
  logs: Record<string, SessionLog>;
  program: Program | null;
  programError: string | null;
  // The tracked program is gone (deleted elsewhere).
  programMissing: boolean;
  startRegimen: (regimen: Omit<Regimen, "updatedAt">, options?: { deleteLogsOf?: number | null }) => Promise<boolean>;
  updateRegimen: (patch: Partial<Pick<Regimen, "startDate" | "dayOffsets">>) => Promise<boolean>;
  stopRegimen: (deleteLogs: boolean) => Promise<boolean>;
  commitLog: (key: string, next: SessionLog | null) => Promise<boolean>;
  deleteProgramData: (programId: number) => Promise<void>;
  countLogs: (programId: number) => Promise<number>;
  intent: number | null;
  setIntent: (programId: number | null) => void;
};

const TrackerContext = createContext<TrackerValue | null>(null);

function keyed(list: SessionLog[]): Record<string, SessionLog> {
  return Object.fromEntries(list.map((l) => [l.key, l]));
}

export function TrackerProvider({ children }: { children: ReactNode }) {
  const { status, userId, api } = useSession();
  const { trees, treeErrors, loadTree, notify, programs } = useApp();
  const [store] = useState<TrackerStore | null>(() => (status === "user" && userId ? createTrackerStore(userId, api) : null));
  const [regimen, setRegimenState] = useState<Regimen | null>(null);
  const [logs, setLogs] = useState<Record<string, SessionLog>>({});
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [intent, setIntent] = useState<number | null>(null);

  // The logs live in a ref as well, so a rollback knows exactly what it is
  // undoing even when several saves are in flight.
  const logsRef = useRef<Record<string, SessionLog>>({});
  const putLogs = useCallback((next: Record<string, SessionLog>) => {
    logsRef.current = next;
    setLogs(next);
  }, []);

  // The regimen, then its program's logs.
  useEffect(() => {
    if (!store) return;
    let alive = true;
    (async () => {
      try {
        const r = await store.getRegimen();
        const list = r ? await store.listLogs(r.programId, ALL_FROM, ALL_TO) : [];
        if (!alive) return;
        setRegimenState(r);
        putLogs(keyed(list));
        setReady(true);
      } catch (err) {
        if (!alive) return;
        setLoadError(errorMessage(err));
        setReady(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [store, putLogs]);

  const programId = regimen?.programId ?? null;
  useEffect(() => {
    if (programId === null || trees[programId] || treeErrors[programId]) return;
    void loadTree(programId);
  }, [programId, trees, treeErrors, loadTree]);

  const reloadLogs = useCallback(
    async (id: number) => {
      if (!store) return;
      putLogs(keyed(await store.listLogs(id, ALL_FROM, ALL_TO)));
    },
    [store, putLogs],
  );

  const startRegimen = useCallback(
    async (next: Omit<Regimen, "updatedAt">, options?: { deleteLogsOf?: number | null }) => {
      if (!store) return false;
      try {
        if (options?.deleteLogsOf != null) await store.deleteProgramData(options.deleteLogsOf);
        const saved = await store.setRegimen({ ...next, updatedAt: new Date().toISOString() });
        setRegimenState(saved);
        await reloadLogs(saved.programId);
        return true;
      } catch (err) {
        notify({ tone: "error", text: `Couldn't start tracking: ${errorMessage(err)}` });
        return false;
      }
    },
    [store, reloadLogs, notify],
  );

  const updateRegimen = useCallback(
    async (patch: Partial<Pick<Regimen, "startDate" | "dayOffsets">>) => {
      if (!store || !regimen) return false;
      const previous = regimen;
      const next = { ...regimen, ...patch, updatedAt: new Date().toISOString() };
      setRegimenState(next);
      try {
        await store.setRegimen(next);
        return true;
      } catch (err) {
        setRegimenState(previous);
        notify({ tone: "error", text: `Couldn't save the schedule: ${errorMessage(err)}` });
        return false;
      }
    },
    [store, regimen, notify],
  );

  const stopRegimen = useCallback(
    async (deleteLogs: boolean) => {
      if (!store || !regimen) return false;
      try {
        if (deleteLogs) await store.deleteProgramData(regimen.programId);
        await store.clearRegimen();
        setRegimenState(null);
        putLogs({});
        return true;
      } catch (err) {
        notify({ tone: "error", text: `Couldn't stop tracking: ${errorMessage(err)}` });
        return false;
      }
    },
    [store, regimen, notify, putLogs],
  );

  // Saved on every change: optimistic, rolled back with a message on failure.
  const commitLog = useCallback(
    async (key: string, next: SessionLog | null) => {
      if (!store) return false;
      const previous = logsRef.current[key] ?? null;
      const put = (log: SessionLog | null) => {
        const copy = { ...logsRef.current };
        if (log) copy[key] = log;
        else delete copy[key];
        putLogs(copy);
      };
      put(next);
      try {
        if (next) await store.saveLog(next);
        else await store.deleteLog(key);
        return true;
      } catch (err) {
        // Roll back unless a later change already replaced this one.
        if ((logsRef.current[key] ?? null) === next) put(previous);
        notify({ tone: "error", text: `Couldn't save that change, so it was undone. ${errorMessage(err)}` });
        return false;
      }
    },
    [store, notify, putLogs],
  );

  const deleteProgramData = useCallback(
    async (id: number) => {
      if (!store) return;
      try {
        await store.deleteProgramData(id);
        if (regimen?.programId === id) {
          setRegimenState(null);
          putLogs({});
        }
      } catch (err) {
        notify({ tone: "error", text: `Couldn't delete the program's tracking history: ${errorMessage(err)}` });
      }
    },
    [store, regimen, notify, putLogs],
  );

  const countLogs = useCallback(
    async (id: number) => {
      if (!store) return 0;
      try {
        return (await store.listLogs(id, ALL_FROM, ALL_TO)).length;
      } catch {
        return 0;
      }
    },
    [store],
  );

  const program = programId !== null ? (trees[programId] ?? null) : null;
  const programError = programId !== null ? (treeErrors[programId] ?? null) : null;
  const programMissing = programId !== null && programs !== null && !programs.some((p) => p.id === programId);

  const value = useMemo<TrackerValue>(
    () => ({
      store,
      ready,
      loadError,
      regimen,
      logs,
      program,
      programError,
      programMissing,
      startRegimen,
      updateRegimen,
      stopRegimen,
      commitLog,
      deleteProgramData,
      countLogs,
      intent,
      setIntent,
    }),
    [store, ready, loadError, regimen, logs, program, programError, programMissing, startRegimen, updateRegimen, stopRegimen, commitLog, deleteProgramData, countLogs, intent],
  );

  return <TrackerContext value={value}>{children}</TrackerContext>;
}

export function useTracker(): TrackerValue {
  const value = useContext(TrackerContext);
  if (!value) throw new Error("useTracker outside TrackerProvider");
  return value;
}
