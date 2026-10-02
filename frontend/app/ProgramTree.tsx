"use client";

import { useState } from "react";
import { AddDayForm, AddExerciseForm, AddMesocycleForm } from "./StructureForms";
import type { DayTemplate, ExerciseSlot, Mesocycle, Program, WeeklyPrescription } from "./types";
import { useApi } from "./useApi";

type FrequencyResult = {
  frequency: { muscle_group: string; frequency: number; grounding_note: string | null };
  days_added: unknown[];
};

type ProgressionResult = {
  scheme: { muscle_group: string; scheme: string; grounding_note: string | null };
  updated_prescriptions: unknown[];
};

const actionClass = "text-xs underline disabled:opacity-40 disabled:no-underline shrink-0";

// sets=0 with an empty load is the backend's "not generated yet" placeholder
// state (see create_exercise_slot / _clone_day_for_muscle_group).
function isPlaceholder(wp: WeeklyPrescription) {
  return wp.sets === 0 && !wp.load;
}

function generatedCount(slots: ExerciseSlot[]) {
  return slots.flatMap((s) => s.weekly_prescriptions).filter((wp) => !isPlaceholder(wp)).length;
}

function deleteWarning(what: string, slots: ExerciseSlot[]) {
  const generated = generatedCount(slots);
  return generated > 0
    ? `Delete ${what}? This also deletes ${generated} generated week${generated === 1 ? "" : "s"} of values and their citations. This can't be undone.`
    : `Delete ${what}? This can't be undone.`;
}

function muscleGroupsIn(mesocycle: Mesocycle) {
  const groups = new Set<string>();
  for (const day of mesocycle.day_templates) {
    for (const slot of day.exercise_slots) groups.add(slot.muscle_group);
  }
  return [...groups].sort();
}

export default function ProgramTree({
  program,
  anchoredFieldId,
  onAskAbout,
  onChanged,
}: {
  program: Program;
  anchoredFieldId: number | null;
  onAskAbout: (prescription: WeeklyPrescription, label: string) => void;
  onChanged: () => void;
}) {
  const api = useApi();
  // One generation at a time: each call is several seconds of retrieval +
  // generation + citation verification, and running two against the same
  // muscle group at once would race on the sibling-volume context.
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function runAction(key: string, action: () => Promise<string | null>) {
    setBusyKey(key);
    setError(null);
    setNotice(null);
    try {
      setNotice(await action());
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyKey(null);
    }
  }

  function generatePrescription(wp: WeeklyPrescription, field: "volume" | "intensity") {
    return runAction(`${field}-${wp.id}`, async () => {
      await api(`/weekly-prescriptions/${wp.id}/generate-${field}`, { method: "POST" });
      return null;
    });
  }

  function generateFrequency(mesocycle: Mesocycle, muscleGroup: string) {
    return runAction(`frequency-${mesocycle.id}-${muscleGroup}`, async () => {
      const result = await api<FrequencyResult>(`/mesocycles/${mesocycle.id}/generate-frequency`, {
        method: "POST",
        body: { muscle_group: muscleGroup },
      });
      const added = result.days_added.length;
      return (
        `${muscleGroup}: ${result.frequency.frequency}x/week` +
        (added > 0 ? ` - added ${added} day${added === 1 ? "" : "s"} to reach it.` : " - no days needed adding.") +
        (result.frequency.grounding_note ? ` (${result.frequency.grounding_note})` : "")
      );
    });
  }

  function generateProgression(mesocycle: Mesocycle, muscleGroup: string) {
    return runAction(`progression-${mesocycle.id}-${muscleGroup}`, async () => {
      const result = await api<ProgressionResult>(`/mesocycles/${mesocycle.id}/generate-progression`, {
        method: "POST",
        body: { muscle_group: muscleGroup },
      });
      const updated = result.updated_prescriptions.length;
      return (
        `${muscleGroup}: ${result.scheme.scheme} progression` +
        (result.scheme.scheme === "linear"
          ? ` - applied to ${updated} week${updated === 1 ? "" : "s"} (needs a week-1 load in %1RM to progress from).`
          : " - no week-by-week loads applied (only linear is applied automatically).") +
        (result.scheme.grounding_note ? ` (${result.scheme.grounding_note})` : "")
      );
    });
  }

  function deleteDay(day: DayTemplate) {
    if (!window.confirm(deleteWarning(`day "${day.name}" and its ${day.exercise_slots.length} exercise(s)`, day.exercise_slots))) return;
    return runAction(`delete-day-${day.id}`, async () => {
      await api(`/day-templates/${day.id}`, { method: "DELETE" });
      return `Deleted day "${day.name}".`;
    });
  }

  function deleteExercise(slot: ExerciseSlot) {
    if (!window.confirm(deleteWarning(`"${slot.exercise_name}"`, [slot]))) return;
    return runAction(`delete-exercise-${slot.id}`, async () => {
      await api(`/exercise-slots/${slot.id}`, { method: "DELETE" });
      return `Deleted "${slot.exercise_name}".`;
    });
  }

  const busy = busyKey !== null;

  return (
    <div className="flex flex-col gap-4 w-full text-sm">
      <p className="text-zinc-500">
        Program #{program.id} - goal: {program.goal}
      </p>

      {busy && <p className="text-indigo-600 dark:text-indigo-400 text-xs">Generating - this can take a little while...</p>}
      {notice && <p className="text-green-700 dark:text-green-500 text-xs">{notice}</p>}
      {error && <p className="text-red-600 text-xs">{error}</p>}

      {program.mesocycles.length === 0 && (
        <p className="text-zinc-500 text-xs">
          No training blocks yet. Add one below, then add days and exercises to it.
        </p>
      )}

      {program.mesocycles.map((mesocycle) => {
        const muscleGroups = muscleGroupsIn(mesocycle);
        return (
          <div key={mesocycle.id} className="border rounded p-3 flex flex-col gap-3">
            <p className="font-medium">
              {mesocycle.name} (weeks {mesocycle.start_week}-{mesocycle.end_week})
            </p>

            {muscleGroups.length > 0 && (
              <div className="flex flex-col gap-1 text-xs">
                <p className="text-zinc-500">Per muscle group, for this block:</p>
                {muscleGroups.map((group) => (
                  <div key={group} className="flex items-center gap-3 pl-3">
                    <span className="w-24">{group}</span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => generateFrequency(mesocycle, group)}
                      className={actionClass}
                    >
                      {busyKey === `frequency-${mesocycle.id}-${group}` ? "generating..." : "generate frequency"}
                    </button>
                    {program.goal === "strength" && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => generateProgression(mesocycle, group)}
                        className={actionClass}
                      >
                        {busyKey === `progression-${mesocycle.id}-${group}` ? "generating..." : "generate progression"}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {mesocycle.day_templates.map((day) => (
              <div key={day.id} className="pl-3 border-l flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium text-zinc-700 dark:text-zinc-300">
                    {day.name}
                    {day.rest_days_before !== null && (
                      <span className="text-zinc-500 font-normal text-xs ml-2">
                        ({day.rest_days_before} rest day{day.rest_days_before === 1 ? "" : "s"} before)
                      </span>
                    )}
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => deleteDay(day)}
                    className={`${actionClass} text-red-600`}
                  >
                    {busyKey === `delete-day-${day.id}` ? "deleting..." : "delete day"}
                  </button>
                </div>
                {day.exercise_slots.map((slot) => (
                  <div key={slot.id} className="pl-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-zinc-600 dark:text-zinc-400">
                        {slot.exercise_name} ({slot.muscle_group})
                      </p>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => deleteExercise(slot)}
                        className={`${actionClass} text-red-600`}
                      >
                        {busyKey === `delete-exercise-${slot.id}` ? "deleting..." : "delete exercise"}
                      </button>
                    </div>
                    <ul className="flex flex-col gap-1 mt-1">
                      {slot.weekly_prescriptions.map((wp) => {
                        const label = `${slot.exercise_name}, week ${wp.week_number}`;
                        const isAnchored = anchoredFieldId === wp.id;
                        return (
                          <li
                            key={wp.id}
                            className={`flex flex-wrap items-center justify-between gap-2 rounded px-2 py-1 ${
                              isAnchored ? "bg-indigo-100 dark:bg-indigo-950" : ""
                            }`}
                          >
                            <span>
                              week {wp.week_number}:{" "}
                              {isPlaceholder(wp) ? (
                                <span className="text-zinc-400">not generated yet</span>
                              ) : (
                                <>
                                  {wp.sets} sets - {wp.reps || "reps n/a"} - {wp.load || "load n/a"}
                                </>
                              )}
                              {wp.grounding_note && (
                                <span className="text-amber-600 text-xs ml-2">({wp.grounding_note})</span>
                              )}
                            </span>
                            <span className="flex gap-3">
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => generatePrescription(wp, "volume")}
                                className={actionClass}
                              >
                                {busyKey === `volume-${wp.id}` ? "generating..." : "gen sets"}
                              </button>
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => generatePrescription(wp, "intensity")}
                                className={actionClass}
                              >
                                {busyKey === `intensity-${wp.id}` ? "generating..." : "gen load"}
                              </button>
                              <button
                                type="button"
                                onClick={() => onAskAbout(wp, label)}
                                className={`${actionClass} text-indigo-600 dark:text-indigo-400`}
                              >
                                {isAnchored ? "anchored" : "ask about this"}
                              </button>
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
                <div className="pl-3">
                  <AddExerciseForm dayTemplateId={day.id} onAdded={onChanged} />
                </div>
              </div>
            ))}

            <div className="pl-3">
              <AddDayForm mesocycleId={mesocycle.id} onAdded={onChanged} />
            </div>
          </div>
        );
      })}

      <div className="border rounded p-3 border-dashed">
        <AddMesocycleForm programId={program.id} onAdded={onChanged} />
      </div>
    </div>
  );
}
