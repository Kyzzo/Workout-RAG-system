"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";

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
      console.log("token:", token);

      const res = await fetch("http://localhost:8000/programs/", {
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
    <div className="flex flex-col items-center gap-6 p-8">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Program goal (e.g. hypertrophy)"
          className="border rounded px-3 py-2"
          required
        />
        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-black text-white px-4 py-2 disabled:opacity-50"
        >
          {submitting ? "Creating..." : "Create Program"}
        </button>
      </form>
      {error && <p className="text-red-600">{error}</p>}
      {program && (
        <pre className="bg-zinc-100 p-4 rounded text-sm max-w-lg overflow-auto">
          {JSON.stringify(program, null, 2)}
        </pre>
      )}
    </div>
  );
}
