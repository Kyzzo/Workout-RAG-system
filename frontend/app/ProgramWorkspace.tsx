"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { API_URL } from "./apiUrl";
import ChatWindow from "./ChatWindow";
import ProgramTree from "./ProgramTree";
import type { Program, WeeklyPrescription } from "./types";

export default function ProgramWorkspace() {
  const { getToken } = useAuth();
  const [programId, setProgramId] = useState("");
  const [program, setProgram] = useState<Program | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [anchoredFieldId, setAnchoredFieldId] = useState<number | null>(null);
  const [anchorLabel, setAnchorLabel] = useState<string | null>(null);

  async function handleLoad(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setProgram(null);
    setAnchoredFieldId(null);
    setAnchorLabel(null);
    setLoading(true);

    try {
      const token = await getToken();
      const res = await fetch(`${API_URL}/programs/${programId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) {
        setError(`Request failed: ${res.status} ${await res.text()}`);
        return;
      }

      setProgram(await res.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function handleAskAbout(prescription: WeeklyPrescription, label: string) {
    setAnchoredFieldId(prescription.id);
    setAnchorLabel(label);
  }

  return (
    <div className="flex flex-col items-center gap-6 p-8 w-full max-w-lg">
      <form onSubmit={handleLoad} className="flex gap-2 w-full">
        <input
          value={programId}
          onChange={(e) => setProgramId(e.target.value)}
          placeholder="Program id (e.g. 1)"
          className="border rounded px-3 py-2 flex-1"
          required
        />
        <button
          type="submit"
          disabled={loading}
          className="rounded bg-black text-white px-4 py-2 disabled:opacity-50 dark:bg-white dark:text-black"
        >
          {loading ? "Loading..." : "View Program"}
        </button>
      </form>
      {error && <p className="text-red-600">{error}</p>}
      {program && (
        <ProgramTree program={program} anchoredFieldId={anchoredFieldId} onAskAbout={handleAskAbout} />
      )}

      <ChatWindow
        fieldId={anchoredFieldId}
        anchorLabel={anchorLabel}
        onClearAnchor={() => {
          setAnchoredFieldId(null);
          setAnchorLabel(null);
        }}
      />
    </div>
  );
}
