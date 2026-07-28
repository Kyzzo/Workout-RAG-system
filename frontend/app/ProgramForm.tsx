"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { API_URL } from "./apiUrl";

type Program = {
  id: number;
  user_id: number;
  goal: string;
  mesocycles: unknown[];
};

export default function ProgramForm() {
  const { getToken } = useAuth();
  const [goal, setGoal] = useState("");
  const [program, setProgram] = useState<Program | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const token = await getToken();

      const res = await fetch(`${API_URL}/programs/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ goal }),
      });

      if (!res.ok) {
        setError(`Request failed: ${res.status} ${await res.text()}`);
        return;
      }

      setProgram(await res.json());
    } catch (err) {
      console.error("submit error:", err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-6 p-8 w-full max-w-lg">
      <form onSubmit={handleSubmit} className="flex gap-2 w-full">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Program goal (e.g. hypertrophy)"
          className="border rounded px-3 py-2 flex-1"
          required
        />
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-black text-white px-4 py-2 disabled:opacity-50 dark:bg-white dark:text-black"
        >
          {submitting ? "Creating..." : "Create Program"}
        </button>
      </form>
      {error && <p className="text-red-600">{error}</p>}
      {program && (
        <pre className="bg-zinc-100 text-zinc-900 p-4 rounded text-sm w-full overflow-auto">
          {JSON.stringify(program, null, 2)}
        </pre>
      )}
    </div>
  );
}
