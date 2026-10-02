"use client";

import { useState } from "react";
import { useApi } from "./useApi";

// Inline "add" forms for the manual structure builder. Each one posts to its
// backend create endpoint, then calls onAdded so the parent can refetch the
// whole program - one source of truth, rather than patching nested state by
// hand at three different depths.

const inputClass = "border rounded px-2 py-1 text-sm bg-white dark:bg-zinc-900";
const buttonClass =
  "rounded bg-black text-white px-3 py-1 text-sm disabled:opacity-50 dark:bg-white dark:text-black";

// Muscle-group names the backend's retrieval queries are phrased around.
// Suggestions only - any value is accepted and normalized server-side.
const MUSCLE_GROUPS = [
  "chest", "back", "shoulders", "biceps", "triceps",
  "quadriceps", "hamstrings", "glutes", "calves", "abs",
];

function useSubmit(onAdded: () => void) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(action: () => Promise<unknown>, reset: () => void) {
    setError(null);
    setSubmitting(true);
    try {
      await action();
      reset();
      onAdded();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return { submitting, error, submit };
}

export function AddMesocycleForm({ programId, onAdded }: { programId: number; onAdded: () => void }) {
  const api = useApi();
  const { submitting, error, submit } = useSubmit(onAdded);
  const [name, setName] = useState("");
  const [startWeek, setStartWeek] = useState("1");
  const [endWeek, setEndWeek] = useState("4");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit(
          () =>
            api(`/programs/${programId}/mesocycles`, {
              method: "POST",
              body: { name, start_week: Number(startWeek), end_week: Number(endWeek) },
            }),
          () => setName(""),
        );
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Block name (e.g. Accumulation)"
        className={`${inputClass} flex-1 min-w-40`}
        required
      />
      <label className="text-xs text-zinc-500">weeks</label>
      <input
        type="number"
        min={1}
        value={startWeek}
        onChange={(e) => setStartWeek(e.target.value)}
        className={`${inputClass} w-16`}
        required
      />
      <span className="text-xs text-zinc-500">to</span>
      <input
        type="number"
        min={1}
        value={endWeek}
        onChange={(e) => setEndWeek(e.target.value)}
        className={`${inputClass} w-16`}
        required
      />
      <button type="submit" disabled={submitting} className={buttonClass}>
        {submitting ? "Adding..." : "Add block"}
      </button>
      {error && <p className="w-full text-red-600 text-xs">{error}</p>}
    </form>
  );
}

export function AddDayForm({ mesocycleId, onAdded }: { mesocycleId: number; onAdded: () => void }) {
  const api = useApi();
  const { submitting, error, submit } = useSubmit(onAdded);
  const [name, setName] = useState("");
  const [restDaysBefore, setRestDaysBefore] = useState("");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit(
          () =>
            api(`/mesocycles/${mesocycleId}/days`, {
              method: "POST",
              body: {
                name,
                rest_days_before: restDaysBefore === "" ? null : Number(restDaysBefore),
              },
            }),
          () => {
            setName("");
            setRestDaysBefore("");
          },
        );
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Day name (e.g. Push)"
        className={`${inputClass} flex-1 min-w-32`}
        required
      />
      <input
        type="number"
        min={0}
        value={restDaysBefore}
        onChange={(e) => setRestDaysBefore(e.target.value)}
        placeholder="rest days before"
        className={`${inputClass} w-36`}
      />
      <button type="submit" disabled={submitting} className={buttonClass}>
        {submitting ? "Adding..." : "Add day"}
      </button>
      {error && <p className="w-full text-red-600 text-xs">{error}</p>}
    </form>
  );
}

export function AddExerciseForm({ dayTemplateId, onAdded }: { dayTemplateId: number; onAdded: () => void }) {
  const api = useApi();
  const { submitting, error, submit } = useSubmit(onAdded);
  const [exerciseName, setExerciseName] = useState("");
  const [muscleGroup, setMuscleGroup] = useState("");
  const listId = `muscle-groups-${dayTemplateId}`;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit(
          () =>
            api(`/day-templates/${dayTemplateId}/exercises`, {
              method: "POST",
              body: { exercise_name: exerciseName, muscle_group: muscleGroup },
            }),
          () => setExerciseName(""),
        );
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <input
        value={exerciseName}
        onChange={(e) => setExerciseName(e.target.value)}
        placeholder="Exercise (e.g. Barbell Bench Press)"
        className={`${inputClass} flex-1 min-w-40`}
        required
      />
      <input
        value={muscleGroup}
        onChange={(e) => setMuscleGroup(e.target.value)}
        placeholder="Muscle group"
        list={listId}
        className={`${inputClass} w-36`}
        required
      />
      <datalist id={listId}>
        {MUSCLE_GROUPS.map((group) => (
          <option key={group} value={group} />
        ))}
      </datalist>
      <button type="submit" disabled={submitting} className={buttonClass}>
        {submitting ? "Adding..." : "Add exercise"}
      </button>
      {error && <p className="w-full text-red-600 text-xs">{error}</p>}
    </form>
  );
}
