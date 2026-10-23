"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { runBlockGeneration } from "../blockGeneration";
import {
  programTitle,
  type GenerateProgramRequest,
  type Goal,
  type Mesocycle,
  type Program,
  type ProgramSummary,
  type SplitOut,
  type VolumePreference,
} from "../types";
import { errorMessage } from "../useApi";
import { useDialogs } from "./dialogs";
import { useSession } from "./session";
import { useUi } from "./ui";

export type Notice = {
  id: string;
  tone: "done" | "error" | "info";
  text: string;
  lines?: string[];
  action?: { label: string; run: () => Promise<void> | void };
};

export type Phase = "Choosing exercises" | "Frequency" | "Weekly volume" | "Reps & effort" | "Progression";

export type Run = {
  id: number;
  source: "generator" | "block";
  programId: number | null;
  title: string;
  phases: Phase[];
  phase: Phase;
  done: number;
  total: number | null;
  stopping: boolean;
  result: { ok: boolean; message: string; failures: string[] } | null;
};

export type Busy = { label: string; scope: string; working: string };

export type ActOptions<T> = {
  label: string;
  scope: string;
  working?: string;
  run: () => Promise<T>;
  done?: (result: T) => Omit<Notice, "id"> | string | null;
  refresh?: boolean;
};

type AppValue = {
  programs: ProgramSummary[] | null;
  listError: string | null;
  selectedId: number | null;
  program: Program | null;
  programLoading: boolean;
  programError: string | null;
  trees: Record<number, Program>;
  treeErrors: Record<number, string>;
  splits: SplitOut[] | null;
  splitsError: string | null;
  select: (id: number | null) => void;
  loadTree: (id: number) => Promise<Program | null>;
  refreshTree: (id: number) => Promise<void>;
  refreshProgram: () => Promise<void>;
  retryList: () => void;
  busy: Busy | null;
  locked: boolean;
  act: <T>(options: ActOptions<T>) => Promise<T | undefined>;
  run: Run | null;
  startGenerator: (request: GenerateProgramRequest) => Promise<void>;
  createEmpty: (options: { goal: Goal; volume_preference: VolumePreference; trained: boolean; include_deload: boolean }) => Promise<void>;
  generateBlock: (block: Mesocycle) => Promise<void>;
  stopRun: () => void;
  dismissRun: () => void;
  renameProgram: (id: number) => Promise<void>;
  deleteProgram: (id: number, trackingNote: string | null) => Promise<boolean>;
  notices: Notice[];
  notify: (notice: Omit<Notice, "id">) => string;
  dismiss: (id: string) => void;
};

const AppContext = createContext<AppValue | null>(null);

// Shown to guests only, who make no API calls (the generator's empty state
// still needs something to show). Signed-in users always get /splits/.
export const GUEST_SPLITS: SplitOut[] = [
  { key: "upper_lower", label: "Upper/Lower", allowed_days: [2, 4, 6], day_types: ["Upper", "Lower"] },
  { key: "ppl", label: "Push/Pull/Legs", allowed_days: [3, 6], day_types: ["Push", "Pull", "Legs"] },
  { key: "anterior_posterior", label: "Anterior/Posterior", allowed_days: [2, 4, 6], day_types: ["Anterior", "Posterior"] },
  { key: "torso_limbs", label: "Torso/Limbs", allowed_days: [2, 4, 6], day_types: ["Torso", "Limbs"] },
  { key: "arnold", label: "Arnold", allowed_days: [3, 6], day_types: ["Chest & Back", "Shoulders & Arms", "Legs"] },
  { key: "full_body", label: "Full Body (FBEOD)", allowed_days: [2, 3, 4], day_types: ["Full Body"] },
];

let noticeCounter = 0;
let runCounter = 0;

function phasesFor(goal: string, withExercises: boolean): Phase[] {
  const strength = goal === "strength";
  return [
    ...(withExercises ? (["Choosing exercises"] as Phase[]) : []),
    ...(strength ? (["Frequency"] as Phase[]) : []),
    "Weekly volume",
    "Reps & effort",
    ...(strength ? (["Progression"] as Phase[]) : []),
  ];
}

function withProgress(run: Run | null, label: string): Run | null {
  if (!run) return run;
  const m = /^(.*) (\d+)\/(\d+)$/.exec(label);
  if (!m) return run;
  return { ...run, phase: m[1] as Phase, done: Number(m[2]), total: Number(m[3]) };
}

export function AppProvider({ children }: { children: ReactNode }) {
  const { status, api } = useSession();
  const { confirm, prompt } = useDialogs();
  const { closeSheet } = useUi();
  const router = useRouter();
  const signedIn = status === "user";

  const [programs, setPrograms] = useState<ProgramSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [listAttempt, setListAttempt] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [trees, setTrees] = useState<Record<number, Program>>({});
  const [treeErrors, setTreeErrors] = useState<Record<number, string>>({});
  const [splits, setSplits] = useState<SplitOut[] | null>(null);
  const [splitsError, setSplitsError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);

  // Read by long-running work, which must act on what's true *now*.
  const selectedRef = useRef<number | null>(null);
  const lockRef = useRef(false);
  const cancelRef = useRef(false);
  const inflight = useRef(new Map<number, Promise<Program | null>>());
  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);

  const notify = useCallback((notice: Omit<Notice, "id">) => {
    noticeCounter += 1;
    const id = `n${noticeCounter}`;
    setNotices((list) => [...list.slice(-4), { ...notice, id }]);
    return id;
  }, []);
  const dismiss = useCallback((id: string) => setNotices((list) => list.filter((n) => n.id !== id)), []);

  // ---- Loading ----

  useEffect(() => {
    if (!signedIn) return;
    let alive = true;
    api<ProgramSummary[]>("/programs/")
      .then((list) => {
        if (!alive) return;
        setPrograms(list);
        setListError(null);
        setSelectedId((current) => (current !== null && list.some((p) => p.id === current) ? current : (list[0]?.id ?? null)));
      })
      .catch((err) => alive && setListError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [signedIn, api, listAttempt]);

  useEffect(() => {
    if (!signedIn) return;
    let alive = true;
    api<SplitOut[]>("/splits/")
      .then((list) => alive && setSplits(list))
      .catch((err) => alive && setSplitsError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [signedIn, api]);

  const refreshTree = useCallback(
    async (id: number) => {
      try {
        const tree = await api<Program>(`/programs/${id}`);
        setTrees((t) => ({ ...t, [id]: tree }));
        setTreeErrors((e) => {
          if (!(id in e)) return e;
          const next = { ...e };
          delete next[id];
          return next;
        });
      } catch (err) {
        setTreeErrors((e) => ({ ...e, [id]: errorMessage(err) }));
      }
    },
    [api],
  );

  // Loads a tree once (concurrent callers share the request).
  const loadTree = useCallback(
    (id: number) => {
      const pending = inflight.current.get(id);
      if (pending) return pending;
      const promise = api<Program>(`/programs/${id}`)
        .then((tree) => {
          setTrees((t) => ({ ...t, [id]: tree }));
          return tree;
        })
        .catch((err) => {
          setTreeErrors((e) => ({ ...e, [id]: errorMessage(err) }));
          return null;
        })
        .finally(() => inflight.current.delete(id));
      inflight.current.set(id, promise);
      return promise;
    },
    [api],
  );

  useEffect(() => {
    if (selectedId === null || trees[selectedId] || treeErrors[selectedId]) return;
    void loadTree(selectedId);
  }, [selectedId, trees, treeErrors, loadTree]);

  const refreshProgram = useCallback(async () => {
    const id = selectedRef.current;
    if (id !== null) await refreshTree(id);
  }, [refreshTree]);

  const select = useCallback(
    (id: number | null) => {
      setSelectedId(id);
      setNotices((list) => list.filter((n) => n.tone !== "error"));
      if (id === null) return;
      setTreeErrors((e) => {
        if (!(id in e)) return e;
        const next = { ...e };
        delete next[id];
        return next;
      });
    },
    [],
  );

  const retryList = useCallback(() => {
    setListError(null);
    setListAttempt((n) => n + 1);
  }, []);

  // ---- One program action at a time ----

  const act = useCallback(
    async <T,>(options: ActOptions<T>): Promise<T | undefined> => {
      if (lockRef.current) return undefined;
      lockRef.current = true;
      setBusy({ label: options.label, scope: options.scope, working: options.working ?? "Working..." });
      let result: T | undefined;
      try {
        result = await options.run();
        const message = options.done?.(result);
        if (typeof message === "string") notify({ tone: "done", text: message });
        else if (message) notify(message);
      } catch (err) {
        notify({ tone: "error", text: `${options.label} failed: ${errorMessage(err)}` });
      } finally {
        if (options.refresh !== false) await refreshProgram();
        lockRef.current = false;
        setBusy(null);
      }
      return result;
    },
    [notify, refreshProgram],
  );

  // ---- Generation (generator and whole-block) ----

  const finishRun = useCallback(
    async (programId: number, result: Run["result"]) => {
      setRun((r) => (r ? { ...r, stopping: false, result } : r));
      // Refresh only if the user is still looking at this program; otherwise
      // drop the stale copy so it's re-read when next needed.
      if (selectedRef.current === programId) await refreshTree(programId);
      else
        setTrees((t) => {
          const next = { ...t };
          delete next[programId];
          return next;
        });
      lockRef.current = false;
    },
    [refreshTree],
  );

  const driveBlock = useCallback(
    async (programId: number, blockId: number) => {
      return runBlockGeneration(api, programId, blockId, {
        onProgress: (label) => setRun((r) => withProgress(r, label)),
        onStepDone: () => {
          if (selectedRef.current === programId) void refreshTree(programId);
        },
        isCancelled: () => cancelRef.current,
      });
    },
    [api, refreshTree],
  );

  const startGenerator = useCallback(
    async (request: GenerateProgramRequest) => {
      if (lockRef.current) return;
      lockRef.current = true;
      cancelRef.current = false;
      runCounter += 1;
      setRun({
        id: runCounter,
        source: "generator",
        programId: null,
        title: "New program",
        phases: phasesFor(request.goal, true),
        phase: "Choosing exercises",
        done: 0,
        total: null,
        stopping: false,
        result: null,
      });
      closeSheet();

      let program: Program;
      try {
        program = await api<Program>("/programs/generate", { method: "POST", body: request });
      } catch (err) {
        setRun((r) => (r ? { ...r, result: { ok: false, message: `Couldn't create the program: ${errorMessage(err)}`, failures: [] } } : r));
        lockRef.current = false;
        return;
      }

      // The program exists: list it, select it and let the user watch it fill in.
      const title = programTitle(program);
      setPrograms((list) => [
        {
          id: program.id,
          goal: program.goal,
          name: program.name,
          volume_preference: program.volume_preference,
          trained: program.trained,
          include_deload: program.include_deload,
        },
        ...(list ?? []).filter((p) => p.id !== program.id),
      ]);
      setTrees((t) => ({ ...t, [program.id]: program }));
      setSelectedId(program.id);
      selectedRef.current = program.id;
      setRun((r) => (r ? { ...r, programId: program.id, title } : r));
      router.push("/program");

      const block = [...program.mesocycles].sort((a, b) => a.start_week - b.start_week)[0];
      if (!block) {
        await finishRun(program.id, { ok: true, message: `${title} is ready.`, failures: [] });
        return;
      }
      try {
        const outcome = await driveBlock(program.id, block.id);
        const message = outcome.cancelled ? `Stopped - ${title} is partly generated.` : `${title} is ready.`;
        await finishRun(program.id, { ok: !outcome.cancelled && !outcome.failures.length, message, failures: outcome.failures });
      } catch (err) {
        await finishRun(program.id, { ok: false, message: `Stopped - ${title} is partly generated.`, failures: [errorMessage(err)] });
      }
    },
    [api, closeSheet, driveBlock, finishRun, router],
  );

  const createEmpty = useCallback(
    async (options: { goal: Goal; volume_preference: VolumePreference; trained: boolean; include_deload: boolean }) => {
      if (lockRef.current) return;
      lockRef.current = true;
      setBusy({ label: "Create program", scope: "program:new", working: "Creating..." });
      try {
        const summary = await api<ProgramSummary>("/programs/", {
          method: "POST",
          body: { ...options, include_deload: options.goal === "strength" && options.include_deload },
        });
        setPrograms((list) => [summary, ...(list ?? []).filter((p) => p.id !== summary.id)]);
        setSelectedId(summary.id);
        closeSheet();
        router.push("/program");
        notify({ tone: "done", text: `Created ${programTitle(summary)}. Add a block to start building it.` });
      } catch (err) {
        notify({ tone: "error", text: `Couldn't create the program: ${errorMessage(err)}` });
      } finally {
        lockRef.current = false;
        setBusy(null);
      }
    },
    [api, closeSheet, notify, router],
  );

  const generateBlock = useCallback(
    async (block: Mesocycle) => {
      const programId = block.program_id;
      const program = trees[programId];
      if (lockRef.current || !program) return;
      const regenerate = !block.day_templates.some((d) => d.exercise_slots.some((s) => s.weekly_prescriptions.some((p) => p.sets === 0 && !p.reps && !p.load && !p.rir)));
      const strength = program.goal === "strength";
      const ok = await confirm({
        title: `${regenerate ? "Regenerate" : "Generate"} “${block.name}”?`,
        body: (
          <p>
            Every number in this block is generated and cited, step by step. Existing generated values are replaced. It
            can take a few minutes.
          </p>
        ),
        consequences: [
          ...(strength ? ["Research frequency for each muscle group, shown next to how often you actually train it (no days are added)."] : []),
          `Weekly volume for each muscle group (cited), split across its exercises, at most ${strength ? 5 : 3} sets per exercise.${strength ? "" : " Exercises are added where a muscle needs more than that."}`,
          `Reps${strength ? ", effort (RIR) and load (%1RM)" : " and effort (RIR)"} for every exercise, applied to all weeks.`,
          ...(strength ? ["Progression for each muscle group."] : []),
        ],
        confirmLabel: regenerate ? "Regenerate block" : "Generate block",
      });
      if (!ok || lockRef.current) return;
      lockRef.current = true;
      cancelRef.current = false;
      runCounter += 1;
      const phases = phasesFor(program.goal, false);
      setRun({
        id: runCounter,
        source: "block",
        programId,
        title: block.name,
        phases,
        phase: phases[0],
        done: 0,
        total: null,
        stopping: false,
        result: null,
      });
      try {
        const outcome = await driveBlock(programId, block.id);
        const message = outcome.cancelled ? `Stopped “${block.name}”.` : `Finished generating “${block.name}”.`;
        await finishRun(programId, { ok: !outcome.cancelled && !outcome.failures.length, message, failures: outcome.failures });
      } catch (err) {
        await finishRun(programId, { ok: false, message: `Stopped “${block.name}”.`, failures: [errorMessage(err)] });
      }
    },
    [trees, confirm, driveBlock, finishRun],
  );

  const stopRun = useCallback(() => {
    cancelRef.current = true;
    setRun((r) => (r && !r.result ? { ...r, stopping: true } : r));
  }, []);

  const dismissRun = useCallback(() => setRun((r) => (r?.result ? null : r)), []);

  // Stopping between steps also covers an account switch mid-run.
  useEffect(
    () => () => {
      cancelRef.current = true;
    },
    [],
  );

  // ---- Rename and delete ----

  const renameProgram = useCallback(
    async (id: number) => {
      const summary = programs?.find((p) => p.id === id);
      if (!summary || lockRef.current) return;
      const current = programTitle(summary);
      const name = await prompt({
        title: "Rename program",
        label: "Name",
        initial: current,
        maxLength: 80,
        confirmLabel: "Rename",
      });
      const trimmed = name?.trim();
      if (!trimmed || trimmed === current) return;
      await act({
        label: "Rename",
        scope: `program:${id}`,
        working: "Renaming...",
        run: () => api<ProgramSummary>(`/programs/${id}`, { method: "PATCH", body: { name: trimmed } }),
        done: (updated) => {
          setPrograms((list) => list?.map((p) => (p.id === id ? { ...p, ...updated } : p)) ?? list);
          return `Renamed to “${programTitle(updated)}”.`;
        },
      });
    },
    [programs, prompt, act, api],
  );

  const deleteProgram = useCallback(
    async (id: number, trackingNote: string | null) => {
      const summary = programs?.find((p) => p.id === id);
      if (!summary || lockRef.current) return false;
      const title = programTitle(summary);
      const ok = await confirm({
        title: `Delete “${title}”?`,
        destructive: true,
        consequences: [
          "This deletes all of its blocks, days, exercises, generated values and their citations. This can't be undone.",
          ...(trackingNote ? [trackingNote] : []),
        ],
        confirmLabel: "Delete program",
      });
      if (!ok || lockRef.current) return false;
      lockRef.current = true;
      setBusy({ label: "Delete", scope: `program:${id}`, working: "Deleting..." });
      try {
        await api<void>(`/programs/${id}`, { method: "DELETE" });
        const list = programs ?? [];
        const index = list.findIndex((p) => p.id === id);
        const remaining = list.filter((p) => p.id !== id);
        const next = remaining[Math.min(index, remaining.length - 1)]?.id ?? null;
        setPrograms(remaining);
        setTrees((t) => {
          const copy = { ...t };
          delete copy[id];
          return copy;
        });
        if (selectedRef.current === id) setSelectedId(next);
        notify({ tone: "done", text: `Deleted “${title}”.` });
        return true;
      } catch (err) {
        notify({ tone: "error", text: `Couldn't delete “${title}”: ${errorMessage(err)}` });
        return false;
      } finally {
        lockRef.current = false;
        setBusy(null);
      }
    },
    [programs, confirm, api, notify],
  );

  const program = selectedId !== null ? (trees[selectedId] ?? null) : null;
  const programError = selectedId !== null ? (treeErrors[selectedId] ?? null) : null;
  const programLoading = selectedId !== null && !program && !programError;
  const locked = busy !== null || (run !== null && run.result === null);

  const value = useMemo<AppValue>(
    () => ({
      programs,
      listError,
      selectedId,
      program,
      programLoading,
      programError,
      trees,
      treeErrors,
      splits,
      splitsError,
      select,
      loadTree,
      refreshTree,
      refreshProgram,
      retryList,
      busy,
      locked,
      act,
      run,
      startGenerator,
      createEmpty,
      generateBlock,
      stopRun,
      dismissRun,
      renameProgram,
      deleteProgram,
      notices,
      notify,
      dismiss,
    }),
    [
      programs, listError, selectedId, program, programLoading, programError, trees, treeErrors, splits, splitsError,
      select, loadTree, refreshTree, refreshProgram, retryList, busy, locked, act, run, startGenerator, createEmpty,
      generateBlock, stopRun, dismissRun, renameProgram, deleteProgram, notices, notify, dismiss,
    ],
  );

  return <AppContext value={value}>{children}</AppContext>;
}

export function useApp(): AppValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp outside AppProvider");
  return value;
}
