"use client";

import { useState } from "react";
import { Close, Plus } from "./Icons";
import { useApi } from "./useApi";

// Inline "add" forms for the manual structure builder. Each one posts to its
// backend create endpoint, then calls onAdded so the parent can refetch the
// whole program - one source of truth, rather than patching nested state by
// hand at three different depths. Each starts as a quiet "+ Add ..." button
// and opens in place, so the program reads as content, not as forms.

// Muscle-group names the backend's retrieval queries are phrased around.
// Suggestions only - any value is accepted and normalized server-side.
// Mirrors backend/app/splits.py MUSCLE_GROUPS.
const MUSCLE_GROUPS = [
  "chest", "lats", "upper back", "lower back",
  "front delts", "side delts", "rear delts", "biceps", "triceps",
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

function AddToggle({
  label,
  dashed = false,
  children,
}: {
  label: string;
  dashed?: boolean;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={
          dashed
            ? "flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-line-strong py-4 text-sm font-medium text-fg-muted transition-colors hover:border-accent hover:text-accent-text"
            : "btn btn-ghost btn-sm -ms-2 self-start"
        }
      >
        <Plus className="size-4" />
        {label}
      </button>
    );
  }
  return (
    <div className="animate-in flex items-start gap-2 rounded-xl border border-line bg-surface-2/60 p-3">
      <div className="min-w-0 flex-1">{children(() => setOpen(false))}</div>
      <button type="button" onClick={() => setOpen(false)} className="icon-btn" aria-label="Close">
        <Close className="size-4" />
      </button>
    </div>
  );
}

function SubmitButton({ submitting, label }: { submitting: boolean; label: string }) {
  return (
    <button type="submit" disabled={submitting} className="btn btn-primary">
      {submitting ? "Adding..." : label}
    </button>
  );
}

function FormError({ error }: { error: string | null }) {
  return error ? <p className="w-full text-xs text-danger">{error}</p> : null;
}

export function AddMesocycleForm({ programId, onAdded }: { programId: number; onAdded: () => void }) {
  const api = useApi();
  const { submitting, error, submit } = useSubmit(onAdded);
  const [name, setName] = useState("");
  const [startWeek, setStartWeek] = useState("1");
  const [endWeek, setEndWeek] = useState("4");

  return (
    <AddToggle label="Add a training block" dashed>
      {(close) => (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(
              () =>
                api(`/programs/${programId}/mesocycles`, {
                  method: "POST",
                  body: { name, start_week: Number(startWeek), end_week: Number(endWeek) },
                }),
              () => {
                setName("");
                close();
              },
            );
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Block name (e.g. Accumulation)"
            aria-label="Block name"
            className="input min-w-40 flex-1"
            required
          />
          <span className="text-sm text-fg-subtle">Weeks</span>
          <input
            type="number"
            min={1}
            value={startWeek}
            onChange={(e) => setStartWeek(e.target.value)}
            aria-label="First week"
            className="input w-16 tabular-nums"
            required
          />
          <span className="text-sm text-fg-subtle">to</span>
          <input
            type="number"
            min={1}
            value={endWeek}
            onChange={(e) => setEndWeek(e.target.value)}
            aria-label="Last week"
            className="input w-16 tabular-nums"
            required
          />
          <SubmitButton submitting={submitting} label="Add block" />
          <FormError error={error} />
        </form>
      )}
    </AddToggle>
  );
}

export function AddDayForm({ mesocycleId, onAdded }: { mesocycleId: number; onAdded: () => void }) {
  const api = useApi();
  const { submitting, error, submit } = useSubmit(onAdded);
  const [name, setName] = useState("");
  const [restDaysBefore, setRestDaysBefore] = useState("");

  return (
    <AddToggle label="Add day">
      {(close) => (
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
                close();
              },
            );
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Day name (e.g. Push)"
            aria-label="Day name"
            className="input min-w-32 flex-1"
            required
          />
          <input
            type="number"
            min={0}
            value={restDaysBefore}
            onChange={(e) => setRestDaysBefore(e.target.value)}
            placeholder="Rest days before"
            aria-label="Rest days before (optional)"
            className="input w-40 tabular-nums"
          />
          <SubmitButton submitting={submitting} label="Add day" />
          <FormError error={error} />
        </form>
      )}
    </AddToggle>
  );
}

export function AddExerciseForm({ dayTemplateId, onAdded }: { dayTemplateId: number; onAdded: () => void }) {
  const api = useApi();
  const { submitting, error, submit } = useSubmit(onAdded);
  const [exerciseName, setExerciseName] = useState("");
  const [muscleGroup, setMuscleGroup] = useState("");
  const [secondaries, setSecondaries] = useState("");
  const listId = `muscle-groups-${dayTemplateId}`;

  return (
    <AddToggle label="Add exercise">
      {() => (
        // Stays open after adding, so several exercises can go in a row.
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(
              () =>
                api(`/day-templates/${dayTemplateId}/exercises`, {
                  method: "POST",
                  body: {
                    exercise_name: exerciseName,
                    muscle_group: muscleGroup,
                    secondary_muscle_groups: secondaries
                      .split(",")
                      .map((g) => g.trim())
                      .filter(Boolean),
                  },
                }),
              () => {
                setExerciseName("");
                setSecondaries("");
              },
            );
          }}
          className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]"
        >
          <input
            autoFocus
            value={exerciseName}
            onChange={(e) => setExerciseName(e.target.value)}
            placeholder="Exercise (e.g. Barbell Bench Press)"
            aria-label="Exercise name"
            className="input"
            required
          />
          <input
            value={muscleGroup}
            onChange={(e) => setMuscleGroup(e.target.value)}
            placeholder="Main muscle"
            aria-label="Main muscle"
            list={listId}
            className="input"
            required
          />
          <input
            value={secondaries}
            onChange={(e) => setSecondaries(e.target.value)}
            placeholder="Also trains (optional, e.g. lats, biceps)"
            aria-label="Also trains (optional)"
            title="Up to 3 secondary muscles, comma-separated - each counts as half a set toward that muscle's weekly volume"
            className="input"
          />
          <datalist id={listId}>
            {MUSCLE_GROUPS.map((group) => (
              <option key={group} value={group} />
            ))}
          </datalist>
          <SubmitButton submitting={submitting} label="Add exercise" />
          <FormError error={error} />
        </form>
      )}
    </AddToggle>
  );
}
