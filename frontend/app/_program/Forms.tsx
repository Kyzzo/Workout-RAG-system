"use client";

import { useId, useRef, useState } from "react";
import { CANONICAL_MUSCLES } from "../_lib/format";
import { useApp } from "../_state/app";
import { useApi } from "../_state/session";
import { Icon } from "../_ui/Icon";
import type { DayTemplate, ExerciseSlot, Mesocycle, Program } from "../types";

// The manual builder: blocks, then days, then exercises.

function Disclosure({ label, open, onToggle, disabled }: { label: string; open: boolean; onToggle: () => void; disabled?: boolean }) {
  return (
    <button type="button" className="add-toggle" aria-expanded={open} onClick={onToggle} disabled={disabled}>
      <Icon name={open ? "close" : "plus"} size={14} />
      {label}
    </button>
  );
}

export function AddBlockForm({ program, startOpen = false }: { program: Program; startOpen?: boolean }) {
  const api = useApi();
  const { act, locked } = useApp();
  const ids = useId();
  const [open, setOpen] = useState(startOpen);
  const [name, setName] = useState("");
  const [first, setFirst] = useState("1");
  const [last, setLast] = useState("4");
  const a = Number(first);
  const b = Number(last);
  const valid = name.trim().length > 0 && Number.isInteger(a) && Number.isInteger(b) && a >= 1 && b >= a;

  const submit = async () => {
    if (!valid) return;
    const created = await act({
      label: "Add block",
      scope: `program:${program.id}`,
      working: "Adding the block...",
      run: () => api<Mesocycle>(`/programs/${program.id}/mesocycles`, { method: "POST", body: { name: name.trim(), start_week: a, end_week: b } }),
      done: (m) => `Added “${m.name}” (weeks ${m.start_week}–${m.end_week}). Next, add its days.`,
    });
    if (created) {
      setName("");
      setOpen(false);
    }
  };

  return (
    <div className="add add-block">
      <Disclosure label="Add a block" open={open} onToggle={() => setOpen((o) => !o)} disabled={locked && !open} />
      {open && (
        <form
          className="add-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="field add-wide">
            <span className="field-label">Block name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Base block" required />
          </label>
          <label className="field">
            <span className="field-label" id={`${ids}-f`}>
              First week
            </span>
            <input className="input" type="number" inputMode="numeric" min={1} value={first} onChange={(e) => setFirst(e.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Last week</span>
            <input className="input" type="number" inputMode="numeric" min={a || 1} value={last} onChange={(e) => setLast(e.target.value)} />
          </label>
          <div className="add-actions">
            <button type="submit" className="btn btn-steel" disabled={!valid || locked}>
              Add block
            </button>
            {b < a && <span className="field-hint">The last week can’t come before the first.</span>}
          </div>
        </form>
      )}
    </div>
  );
}

export function AddDayForm({ block }: { block: Mesocycle }) {
  const api = useApi();
  const { act, locked } = useApp();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [rest, setRest] = useState("");
  const restValue = rest.trim() === "" ? null : Number(rest);
  const valid = name.trim().length > 0 && (restValue === null || (Number.isInteger(restValue) && restValue >= 0));

  const submit = async () => {
    if (!valid) return;
    const created = await act({
      label: "Add day",
      scope: `block:${block.id}`,
      working: "Adding the day...",
      run: () => api<DayTemplate>(`/mesocycles/${block.id}/days`, { method: "POST", body: { name: name.trim(), rest_days_before: restValue } }),
      done: (d) => `Added “${d.name}” to ${block.name}.`,
    });
    if (created) {
      setName("");
      setRest("");
      setOpen(false);
    }
  };

  return (
    <div className="add add-day">
      <Disclosure label={`Add a day to ${block.name}`} open={open} onToggle={() => setOpen((o) => !o)} disabled={locked && !open} />
      {open && (
        <form
          className="add-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="field add-wide">
            <span className="field-label">Day name</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Upper C" required />
          </label>
          <label className="field">
            <span className="field-label">Rest days before (optional)</span>
            <input className="input" type="number" inputMode="numeric" min={0} value={rest} onChange={(e) => setRest(e.target.value)} />
          </label>
          <div className="add-actions">
            <button type="submit" className="btn btn-steel" disabled={!valid || locked}>
              Add day
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

export function AddExerciseForm({ day }: { day: DayTemplate }) {
  const api = useApi();
  const { act, locked } = useApp();
  const ids = useId();
  const nameRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [muscle, setMuscle] = useState("");
  const [also, setAlso] = useState("");
  const secondary = also
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const valid = name.trim().length > 0 && muscle.trim().length > 0 && secondary.length <= 3;

  const submit = async () => {
    if (!valid) return;
    const created = await act({
      label: "Add exercise",
      scope: `day:${day.id}`,
      working: "Adding the exercise...",
      run: () =>
        api<ExerciseSlot>(`/day-templates/${day.id}/exercises`, {
          method: "POST",
          body: { exercise_name: name.trim(), muscle_group: muscle.trim(), secondary_muscle_groups: secondary },
        }),
      done: (s) => `Added “${s.exercise_name}” to ${day.name}. Its values aren’t generated yet.`,
    });
    // Stays open so several can go in a row.
    if (created) {
      setName("");
      setAlso("");
      nameRef.current?.focus();
    }
  };

  return (
    <div className="add add-ex">
      <Disclosure label="Add an exercise" open={open} onToggle={() => setOpen((o) => !o)} disabled={locked && !open} />
      {open && (
        <form
          className="add-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <label className="field add-wide">
            <span className="field-label">Exercise</span>
            <input ref={nameRef} className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Incline Dumbbell Press" required />
          </label>
          <label className="field">
            <span className="field-label">Main muscle</span>
            <input className="input" list={`${ids}-muscles`} value={muscle} onChange={(e) => setMuscle(e.target.value)} placeholder="e.g. chest" required />
            <datalist id={`${ids}-muscles`}>
              {CANONICAL_MUSCLES.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>
          <label className="field">
            <span className="field-label">Also trains (optional)</span>
            <input className="input" list={`${ids}-muscles`} value={also} onChange={(e) => setAlso(e.target.value)} placeholder="e.g. triceps, front delts" />
            <span className="field-hint">
              {secondary.length > 3 ? "Up to 3 muscles." : "Comma-separated, up to 3. Each counts as half a set."}
            </span>
          </label>
          <div className="add-actions">
            <button type="submit" className="btn btn-steel" disabled={!valid || locked}>
              Add exercise
            </button>
            <button type="button" className="btn btn-quiet" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
