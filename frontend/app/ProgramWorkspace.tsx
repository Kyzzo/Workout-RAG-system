"use client";

import { useCallback, useEffect, useState } from "react";
import ChatWindow from "./ChatWindow";
import { DialogProvider, useDialogs } from "./Dialogs";
import { Pencil, Plus, Trash } from "./Icons";
import ProgramTree from "./ProgramTree";
import ProgramWizard from "./ProgramWizard";
import { programLabel, programTitle, volumeLabel, type Program, type ProgramSummary, type WeeklyPrescription } from "./types";
import { Menu, Notice, Skeleton } from "./ui";
import { useApi } from "./useApi";

export default function ProgramWorkspace() {
  return (
    <DialogProvider>
      <Workspace />
    </DialogProvider>
  );
}

function Workspace() {
  const api = useApi();
  const dialogs = useDialogs();
  const [programs, setPrograms] = useState<ProgramSummary[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [program, setProgram] = useState<Program | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [wizardRunning, setWizardRunning] = useState(false);
  // The generator is the whole screen for a new user; with programs it
  // opens on demand ("New program") so the program itself leads.
  const [wizardOpen, setWizardOpen] = useState(false);

  const [anchoredFieldId, setAnchoredFieldId] = useState<number | null>(null);
  const [anchorLabel, setAnchorLabel] = useState<string | null>(null);

  const clearAnchor = useCallback(() => {
    setAnchoredFieldId(null);
    setAnchorLabel(null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await api<ProgramSummary[]>("/programs/");
        if (cancelled) return;
        setPrograms(list);
        setSelectedId((current) => current ?? list[0]?.id ?? null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api]);

  // Refetches the whole nested program after any structural change or
  // generation call, rather than patching nested state by hand - the
  // backend's response is the single source of truth for what changed.
  // A counter rather than a fetch closure, so a long-running caller (the
  // wizard) always refreshes whichever program is selected NOW, not the one
  // selected when it started.
  const reloadProgram = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (selectedId === null) return;
      try {
        const loaded = await api<Program>(`/programs/${selectedId}`);
        if (!cancelled) setProgram(loaded);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [api, selectedId, refreshKey]);

  function handleSelect(id: number) {
    setError(null);
    setProgram(null);
    clearAnchor();
    setSelectedId(id);
  }

  async function handleDelete() {
    const target = programs?.find((p) => p.id === selectedId);
    if (!programs || !target) return;
    const confirmed = await dialogs.confirm({
      title: `Delete ${programLabel(target)}?`,
      body: "This deletes all of its blocks, days, exercises, generated values and their citations. This can't be undone.",
      confirmLabel: "Delete program",
      danger: true,
    });
    if (!confirmed) return;

    setError(null);
    try {
      await api(`/programs/${target.id}`, { method: "DELETE" });
      const remaining = programs.filter((p) => p.id !== target.id);
      setPrograms(remaining);
      clearAnchor();
      setProgram(null);
      setSelectedId(remaining[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRename() {
    const target = programs?.find((p) => p.id === selectedId);
    if (!target) return;
    const name = await dialogs.prompt({
      title: "Rename program",
      label: "Name",
      defaultValue: programTitle(target),
      placeholder: "e.g. Summer strength block",
    });
    if (name === null || !name.trim()) return;
    try {
      const renamed = await api<ProgramSummary>(`/programs/${target.id}`, { method: "PATCH", body: { name } });
      setPrograms((prev) => prev?.map((p) => (p.id === renamed.id ? { ...p, name: renamed.name } : p)) ?? null);
      reloadProgram();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function handleCreated(created: ProgramSummary) {
    setPrograms((prev) => [created, ...(prev ?? [])]);
    handleSelect(created.id);
  }

  // The anchored prescription as it is now (adjustments reload the
  // program), so suggested prompts match it - e.g. load prompts only for a
  // %1RM load.
  const anchored = program?.mesocycles
    .flatMap((m) => m.day_templates)
    .flatMap((d) => d.exercise_slots)
    .flatMap((s) => s.weekly_prescriptions)
    .find((wp) => wp.id === anchoredFieldId);

  function handleAskAbout(prescription: WeeklyPrescription, label: string) {
    setAnchoredFieldId(prescription.id);
    setAnchorLabel(label);
  }

  const hasPrograms = programs !== null && programs.length > 0;
  const showWizard = programs !== null && (!hasPrograms || wizardOpen || wizardRunning);
  const strength = program?.goal === "strength";

  return (
    // Wide screens: program on the left, chat as a sticky panel on the right
    // so it stays in view while the program scrolls. Narrow screens stack.
    <div className="mx-auto grid w-full max-w-7xl grid-cols-1 gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_25rem] lg:gap-8 lg:px-8 lg:py-8 xl:grid-cols-[minmax(0,1fr)_27rem]">
      <main className="stagger flex min-w-0 flex-col gap-5">
        {hasPrograms && (
          <div className="flex items-center gap-2">
            <label htmlFor="program-select" className="sr-only">
              Program
            </label>
            <select
              id="program-select"
              value={selectedId ?? ""}
              onChange={(e) => handleSelect(Number(e.target.value))}
              className="input h-10 flex-1 bg-surface font-medium shadow-card"
            >
              {programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {programLabel(p)}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              disabled={showWizard}
              className="btn btn-secondary h-10"
            >
              <Plus className="size-4" />
              <span className="hidden sm:inline">New program</span>
              <span className="sm:hidden">New</span>
            </button>
          </div>
        )}

        {showWizard && (
          <ProgramWizard
            onCreated={handleCreated}
            onRefresh={reloadProgram}
            onRunningChange={setWizardRunning}
            onClose={hasPrograms ? () => setWizardOpen(false) : undefined}
          />
        )}

        {error && <Notice tone="error">{error}</Notice>}

        {selectedId !== null && program === null && !error && (
          <div className="card flex flex-col gap-4 p-6" aria-busy="true" aria-label="Loading program">
            <Skeleton className="h-7 w-1/3" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}

        {program && (
          <>
            <header className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                  <h1 className="display truncate pb-1 text-[2.25rem] sm:text-[2.75rem]">
                    {programTitle(program)}
                  </h1>
                  <button
                    type="button"
                    onClick={handleRename}
                    disabled={wizardRunning}
                    className="icon-btn"
                    aria-label="Rename program"
                    title="Rename program"
                  >
                    <Pencil className="size-4" />
                  </button>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <span className="chip border-transparent bg-accent-soft font-medium capitalize text-accent-text">
                    {program.goal}
                  </span>
                  <span className="chip">{volumeLabel(program.volume_preference, program.goal)}</span>
                  {strength && <span className="chip">{program.trained ? "Lifting 1+ year" : "Lifting under a year"}</span>}
                  {strength && program.include_deload && <span className="chip">Deload week</span>}
                </div>
              </div>
              <Menu
                label="Program actions"
                disabled={wizardRunning}
                items={[
                  { label: "Rename program", icon: <Pencil className="size-4" />, onSelect: handleRename },
                  { label: "Delete program", icon: <Trash className="size-4" />, danger: true, onSelect: handleDelete },
                ]}
              />
            </header>
            <ProgramTree
              program={program}
              anchoredFieldId={anchoredFieldId}
              onAskAbout={handleAskAbout}
              onChanged={reloadProgram}
              externalBusy={wizardRunning}
            />
          </>
        )}
      </main>

      <aside className="h-[36rem] lg:sticky lg:top-[5.25rem] lg:h-[calc(100dvh-6.75rem)] lg:self-start">
        <ChatWindow
          fieldId={anchoredFieldId}
          anchorLabel={anchorLabel}
          anchorHasPercentLoad={!!anchored && anchored.load.includes("%")}
          goal={program?.goal ?? null}
          onClearAnchor={clearAnchor}
          onPrescriptionUpdated={reloadProgram}
        />
      </aside>
    </div>
  );
}
