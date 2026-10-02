"use client";

import { useCallback, useEffect, useState } from "react";
import ChatWindow from "./ChatWindow";
import ProgramForm from "./ProgramForm";
import ProgramTree from "./ProgramTree";
import type { Program, ProgramSummary, WeeklyPrescription } from "./types";
import { useApi } from "./useApi";

export default function ProgramWorkspace() {
  const api = useApi();
  const [programs, setPrograms] = useState<ProgramSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [program, setProgram] = useState<Program | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  // backend's response is the single source of truth for what changed
  // (e.g. frequency generation can add whole days).
  const reloadProgram = useCallback(async () => {
    if (selectedId === null) return;
    try {
      setProgram(await api<Program>(`/programs/${selectedId}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [api, selectedId]);

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
  }, [api, selectedId]);

  function handleSelect(id: number) {
    setError(null);
    setProgram(null);
    clearAnchor();
    setSelectedId(id);
  }

  function handleCreated(created: ProgramSummary) {
    setPrograms((prev) => [created, ...prev]);
    handleSelect(created.id);
  }

  function handleAskAbout(prescription: WeeklyPrescription, label: string) {
    setAnchoredFieldId(prescription.id);
    setAnchorLabel(label);
  }

  return (
    <div className="flex flex-col items-center gap-6 p-8 w-full max-w-3xl">
      <ProgramForm onCreated={handleCreated} />

      {programs.length > 0 && (
        <div className="flex items-center gap-2 w-full">
          <label className="text-sm text-zinc-500">Program:</label>
          <select
            value={selectedId ?? ""}
            onChange={(e) => handleSelect(Number(e.target.value))}
            className="border rounded px-3 py-2 flex-1 bg-white dark:bg-zinc-900"
          >
            {programs.map((p) => (
              <option key={p.id} value={p.id}>
                #{p.id} - {p.goal}
              </option>
            ))}
          </select>
        </div>
      )}

      {error && <p className="text-red-600 text-sm w-full">{error}</p>}
      {selectedId !== null && program === null && !error && (
        <p className="text-zinc-500 text-sm w-full">Loading program...</p>
      )}
      {program && (
        <ProgramTree
          program={program}
          anchoredFieldId={anchoredFieldId}
          onAskAbout={handleAskAbout}
          onChanged={reloadProgram}
        />
      )}

      <ChatWindow
        fieldId={anchoredFieldId}
        anchorLabel={anchorLabel}
        onClearAnchor={clearAnchor}
        onPrescriptionUpdated={reloadProgram}
      />
    </div>
  );
}
