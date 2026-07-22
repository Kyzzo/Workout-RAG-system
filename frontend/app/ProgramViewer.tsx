"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";

type Program = {
  id: number;
  user_id: number;
  goal: string;
  mesocycles: unknown[];
};

export default function ProgramViewer() {
  const { getToken } = useAuth();
  const [programId, setProgramId] = useState("");
  const [program, setProgram] = useState<Program | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLoad(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setProgram(null);
    setLoading(true);

    try {
      const token = await getToken();
      const res = await fetch(`http://localhost:8000/programs/${programId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
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
        <pre className="bg-zinc-100 text-zinc-900 p-4 rounded text-sm w-full overflow-auto">
          {JSON.stringify(program, null, 2)}
        </pre>
      )}
    </div>
  );
}
