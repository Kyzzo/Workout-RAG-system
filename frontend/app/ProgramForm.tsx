"use client";

import { useState } from "react";
import type { ProgramSummary } from "./types";
import { useApi } from "./useApi";

// A fixed list rather than free text: goal feeds every retrieval query, the
// corpus is organized around these two goals, and progression generation is
// gated on goal === "strength" exactly - "Strength " would silently miss it.
const GOALS = ["hypertrophy", "strength"];

export default function ProgramForm({ onCreated }: { onCreated: (program: ProgramSummary) => void }) {
  const api = useApi();
  const [goal, setGoal] = useState(GOALS[0]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      onCreated(await api<ProgramSummary>("/programs/", { method: "POST", body: { goal } }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-center gap-2 w-full">
      <label className="text-sm text-zinc-500">New program, goal:</label>
      <select
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        className="border rounded px-3 py-2 flex-1 bg-white dark:bg-zinc-900"
      >
        {GOALS.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </select>
      <button
        type="submit"
        disabled={submitting}
        className="rounded bg-black text-white px-4 py-2 disabled:opacity-50 dark:bg-white dark:text-black"
      >
        {submitting ? "Creating..." : "Create Program"}
      </button>
      {error && <p className="w-full text-red-600 text-sm">{error}</p>}
    </form>
  );
}
