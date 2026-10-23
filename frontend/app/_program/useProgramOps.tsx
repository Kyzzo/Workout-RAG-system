"use client";

import { splitSwapChanges, swapSummary } from "../_lib/chatModel";
import { capitalize, countValueWeeks, isPlaceholder, plural, schemeLabel } from "../_lib/format";
import { useApp } from "../_state/app";
import { useDialogs } from "../_state/dialogs";
import { useApi } from "../_state/session";
import type {
  DayTemplate,
  ExerciseSlot,
  GenerateFrequencyResponse,
  GenerateProgressionResponse,
  GenerateWeeklyVolumeResponse,
  Mesocycle,
  Program,
  SwapExerciseResponse,
  WeeklyPrescription,
} from "../types";

// Every granular program action: each one goes through `act`, so only one
// runs at a time, its result or error is reported, and the program is
// re-read afterwards.
export function useProgramOps(program: Program) {
  const api = useApi();
  const { act, notify } = useApp();
  const { confirm, prompt } = useDialogs();
  const strength = program.goal === "strength";

  const generateExercise = (slot: ExerciseSlot) =>
    act({
      label: `Generate reps & effort for ${slot.exercise_name}`,
      scope: `slot:${slot.id}`,
      working: "Generating...",
      run: () => api<ExerciseSlot>(`/exercise-slots/${slot.id}/generate`, { method: "POST" }),
      done: () =>
        strength
          ? `Generated reps, effort and load for “${slot.exercise_name}” across every week.`
          : `Generated reps and effort for “${slot.exercise_name}” across every week.`,
    });

  const regenerateSets = (slot: ExerciseSlot, p: WeeklyPrescription) =>
    act({
      label: `Regenerate sets for ${slot.exercise_name}, week ${p.week_number}`,
      scope: `row:${p.id}`,
      working: "Generating...",
      run: () => api<WeeklyPrescription>(`/weekly-prescriptions/${p.id}/generate-volume`, { method: "POST" }),
      done: (r) => `${slot.exercise_name}, week ${p.week_number}: ${plural(r.sets, "set")}.`,
    });

  const regenerateLoad = (slot: ExerciseSlot, p: WeeklyPrescription) =>
    act({
      label: `Regenerate load for ${slot.exercise_name}, week ${p.week_number}`,
      scope: `row:${p.id}`,
      working: "Generating...",
      run: () => api<WeeklyPrescription>(`/weekly-prescriptions/${p.id}/generate-intensity`, { method: "POST" }),
      done: (r) => `${slot.exercise_name}, week ${p.week_number}: load ${r.load || "unchanged"}.`,
    });

  const undoSwap = (changeId: number, oldName: string) =>
    act({
      label: "Undo the swap",
      scope: `change:${changeId}`,
      working: "Undoing...",
      run: () => api(`/changes/${changeId}/undo`, { method: "POST" }),
      done: () => `Undid the swap of ${oldName}.`,
    });

  const swap = async (slot: ExerciseSlot) => {
    const name = await prompt({
      title: `Swap ${slot.exercise_name}`,
      body: (
        <p>
          Pick another {slot.muscle_group} exercise, or leave it blank to have one suggested. You’ll see everything the
          swap changes before anything is applied.
        </p>
      ),
      label: "Replacement exercise",
      placeholder: "Blank for a suggestion",
      allowEmpty: true,
      maxLength: 80,
      confirmLabel: "Preview swap",
    });
    if (name === null) return;
    const preview = await act({
      label: "Swap preview",
      scope: `slot:${slot.id}`,
      working: "Swapping...",
      run: () => api<SwapExerciseResponse>(`/exercise-slots/${slot.id}/swap`, { method: "POST", body: { exercise_name: name.trim() || null } }),
      refresh: false,
    });
    if (!preview || preview.change_id == null) return;
    const changeId = preview.change_id;
    const { own, other } = splitSwapChanges(preview.changes);
    const ok = await confirm({
      title: `Swap ${preview.old_name} for ${preview.new_name}?`,
      body: (
        <div className="swap-preview">
          {own.length > 0 && (
            <ul className="changes">
              {own.map((c, i) => (
                <li key={i}>The new exercise: {c}</li>
              ))}
            </ul>
          )}
          {other.length > 0 ? (
            <>
              <p className="label changes-head">This also changes</p>
              <ul className="changes changes-other">
                {other.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            </>
          ) : (
            <p>Nothing else in the block changes.</p>
          )}
          <p className="field-hint">You can undo it afterwards.</p>
        </div>
      ),
      confirmLabel: "Swap",
      cancelLabel: "Cancel",
    });
    if (!ok) {
      await act({
        label: "Cancel the swap",
        scope: `slot:${slot.id}`,
        working: "Cancelling...",
        run: () => api(`/changes/${changeId}`, { method: "DELETE" }),
        done: () => "Swap cancelled - nothing changed.",
        refresh: false,
      });
      return;
    }
    await act({
      label: "Swap",
      scope: `slot:${slot.id}`,
      working: "Swapping...",
      run: () => api<SwapExerciseResponse>(`/changes/${changeId}/confirm`, { method: "POST" }),
      done: (applied) => ({
        tone: "done",
        text: swapSummary(applied),
        action: applied.change_id != null ? { label: "Undo", run: () => void undoSwap(applied.change_id!, applied.old_name) } : undefined,
      }),
    });
  };

  const deleteExercise = async (slot: ExerciseSlot) => {
    const k = countValueWeeks([slot]);
    const ok = await confirm({
      title: `Delete ${slot.exercise_name}?`,
      destructive: true,
      consequences: [k ? `This also deletes ${plural(k, "generated week")} of values and their citations. This can't be undone.` : "This can't be undone."],
      confirmLabel: "Delete exercise",
    });
    if (!ok) return;
    await act({
      label: `Delete ${slot.exercise_name}`,
      scope: `slot:${slot.id}`,
      working: "Deleting...",
      run: () => api(`/exercise-slots/${slot.id}`, { method: "DELETE" }),
      done: () => `Deleted “${slot.exercise_name}”.`,
    });
  };

  const deleteDay = async (day: DayTemplate) => {
    const n = day.exercise_slots.length;
    const k = countValueWeeks(day.exercise_slots);
    const ok = await confirm({
      title: `Delete ${day.name}?`,
      destructive: true,
      consequences: [
        `Its ${plural(n, "exercise")} go${n === 1 ? "es" : ""} with it.`,
        k ? `This also deletes ${plural(k, "generated week")} of values and their citations. This can't be undone.` : "This can't be undone.",
        "Its future sessions leave the schedule; sessions already logged stay in your history.",
      ],
      confirmLabel: "Delete day",
    });
    if (!ok) return;
    await act({
      label: `Delete ${day.name}`,
      scope: `day:${day.id}`,
      working: "Deleting...",
      run: () => api(`/day-templates/${day.id}`, { method: "DELETE" }),
      done: () => `Deleted “${day.name}”.`,
    });
  };

  const rename = async (kind: "block" | "day", target: Mesocycle | DayTemplate) => {
    const next = await prompt({
      title: `Rename ${kind}`,
      label: "Name",
      initial: target.name,
      confirmLabel: "Rename",
    });
    const trimmed = next?.trim();
    if (!trimmed || trimmed === target.name) return;
    await act({
      label: `Rename ${kind}`,
      scope: `${kind}:${target.id}`,
      working: "Renaming...",
      run: () =>
        api(kind === "block" ? `/mesocycles/${target.id}` : `/day-templates/${target.id}`, {
          method: "PATCH",
          body: { name: trimmed },
        }),
      done: () => `Renamed to “${trimmed}”.`,
    });
  };

  const muscleVolume = (block: Mesocycle, muscle: string) =>
    act({
      label: `Weekly volume for ${muscle}`,
      scope: `muscle:${block.id}:${muscle}`,
      working: "Generating...",
      run: () =>
        api<GenerateWeeklyVolumeResponse>(`/mesocycles/${block.id}/generate-weekly-volume`, {
          method: "POST",
          body: { muscle_group: muscle },
        }),
      done: (r) => {
        const n = r.volume.weekly_sets;
        const m = r.delivered_weekly_sets;
        let text = `${capitalize(muscle)}: research suggests ${n} sets/week; split across its exercises the plan gives ${m}.`;
        if (r.exercises_added.length) {
          const list = r.exercises_added.join(", ");
          text += ` Added ${list} to fit them - run “Generate reps & effort” on ${r.exercises_added.length === 1 ? "it" : "them"}.`;
        }
        if (m < n) text += " Add an exercise or a day to get closer.";
        return text;
      },
    });

  const muscleFrequency = (block: Mesocycle, muscle: string) =>
    act({
      label: `Frequency for ${muscle}`,
      scope: `muscle:${block.id}:${muscle}`,
      working: "Generating...",
      run: () =>
        api<GenerateFrequencyResponse>(`/mesocycles/${block.id}/generate-frequency`, {
          method: "POST",
          body: { muscle_group: muscle },
        }),
      done: (r) => {
        const k = r.days_added.length;
        const tail = k ? ` - added ${plural(k, "day")} to reach it.` : " - no days needed adding.";
        return {
          tone: "done",
          text: `${capitalize(muscle)}: ${r.frequency.frequency}x/week${tail}`,
          lines: r.frequency.grounding_note ? [r.frequency.grounding_note] : undefined,
        };
      },
    });

  const muscleProgression = (block: Mesocycle, muscle: string) =>
    act({
      label: `Progression for ${muscle}`,
      scope: `muscle:${block.id}:${muscle}`,
      working: "Generating...",
      run: () =>
        api<GenerateProgressionResponse>(`/mesocycles/${block.id}/generate-progression`, {
          method: "POST",
          body: { muscle_group: muscle },
        }),
      done: (r) => ({
        tone: "done",
        text: `${capitalize(muscle)}: ${schemeLabel(r.scheme.scheme)} progression - ${plural(r.updated_prescriptions.length, "week value")} updated.`,
        lines: r.scheme.grounding_note ? [r.scheme.grounding_note] : undefined,
      }),
    });

  return {
    generateExercise,
    regenerateSets,
    regenerateLoad,
    swap,
    deleteExercise,
    deleteDay,
    rename,
    muscleVolume,
    muscleFrequency,
    muscleProgression,
    notify,
    isPlaceholder,
  };
}
