"use client";

import { useRef, useState } from "react";
import { runBlockGeneration } from "./blockGeneration";
import { SourcesBadge, SourcesPanel } from "./Citations";
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

// How many of the block's weekly sessions train this muscle group - what
// the user actually committed to, shown next to the research frequency.
function daysTraining(mesocycle: Mesocycle, group: string) {
  return mesocycle.day_templates.filter((d) => d.exercise_slots.some((s) => s.muscle_group === group)).length;
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
  externalBusy = false,
}: {
  program: Program;
  anchoredFieldId: number | null;
  onAskAbout: (prescription: WeeklyPrescription, label: string) => void;
  onChanged: () => void;
  // True while something outside the tree (the program wizard) is
  // generating this program, so the tree's own actions don't race it.
  externalBusy?: boolean;
}) {
  const api = useApi();
  // One generation at a time: each call is several seconds of retrieval +
  // generation + citation verification, and running two against the same
  // muscle group at once would race on the sibling-volume context.
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Which value's sources are expanded, e.g. "wp-12-sets" or "freq-3" -
  // one at a time so the tree doesn't turn into a wall of excerpts.
  const [openSources, setOpenSources] = useState<string | null>(null);
  const toggleSources = (key: string) => setOpenSources((current) => (current === key ? null : key));
  // Whole-block generation runs as many sequential requests; progress shows
  // where it is, and cancel takes effect between requests (the one already
  // in flight finishes and is saved).
  const [blockProgress, setBlockProgress] = useState<string | null>(null);
  const cancelBlock = useRef(false);

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

  function generateExercise(slot: ExerciseSlot) {
    return runAction(`exercise-${slot.id}`, async () => {
      await api(`/exercise-slots/${slot.id}/generate`, { method: "POST" });
      return `Generated sets and load for "${slot.exercise_name}" across every week.`;
    });
  }

  async function generateBlock(mesocycle: Mesocycle) {
    const strength = program.goal === "strength";
    const confirmed = window.confirm(
      `Generate every number in "${mesocycle.name}"?\n\n` +
        "1. Research frequency for each muscle group, shown next to how often you actually train it (no days are added).\n" +
        "2. Sets and load for every exercise, applied to all weeks.\n" +
        (strength ? "3. Progression for each muscle group.\n" : "") +
        "\nExisting generated values in this block are replaced. This can take a few minutes.",
    );
    if (!confirmed) return;

    setBusyKey(`block-${mesocycle.id}`);
    setError(null);
    setNotice(null);
    cancelBlock.current = false;
    try {
      const { failures, cancelled } = await runBlockGeneration(api, program.id, mesocycle.id, {
        onProgress: setBlockProgress,
        onStepDone: onChanged,
        isCancelled: () => cancelBlock.current,
      });
      setNotice(`${cancelled ? "Stopped" : "Finished generating"} "${mesocycle.name}".`);
      if (failures.length > 0) setError(`${failures.length} step(s) failed:\n${failures.join("\n")}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBlockProgress(null);
      setBusyKey(null);
      onChanged();
    }
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

  const busy = busyKey !== null || externalBusy;

  return (
    <div className="flex flex-col gap-4 w-full text-sm">
      <p className="text-zinc-500">
        Program #{program.id} - goal: {program.goal}
      </p>

      {busy && !blockProgress && (
        <p className="text-indigo-600 dark:text-indigo-400 text-xs">Generating - this can take a little while...</p>
      )}
      {blockProgress && (
        <div className="flex items-center gap-3 text-indigo-600 dark:text-indigo-400 text-xs">
          <span>{blockProgress}...</span>
          <button type="button" onClick={() => (cancelBlock.current = true)} className={actionClass}>
            cancel
          </button>
        </div>
      )}
      {notice && <p className="text-green-700 dark:text-green-500 text-xs">{notice}</p>}
      {error && <p className="text-red-600 text-xs whitespace-pre-line">{error}</p>}

      {program.mesocycles.length === 0 && (
        <p className="text-zinc-500 text-xs">
          No training blocks yet. Add one below, then add days and exercises to it.
        </p>
      )}

      {program.mesocycles.map((mesocycle) => {
        const muscleGroups = muscleGroupsIn(mesocycle);
        return (
          <div key={mesocycle.id} className="border rounded p-3 flex flex-col gap-3">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">
                {mesocycle.name} (weeks {mesocycle.start_week}-{mesocycle.end_week})
              </p>
              {muscleGroups.length > 0 && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => generateBlock(mesocycle)}
                  className="rounded bg-black text-white px-3 py-1 text-xs disabled:opacity-50 dark:bg-white dark:text-black shrink-0"
                >
                  {busyKey === `block-${mesocycle.id}` ? "Generating block..." : "Generate whole block"}
                </button>
              )}
            </div>

            {muscleGroups.length > 0 && (
              <div className="flex flex-col gap-1 text-xs">
                <p className="text-zinc-500">Per muscle group, for this block:</p>
                {muscleGroups.map((group) => {
                  const frequency = mesocycle.muscle_group_frequencies.find((f) => f.muscle_group === group);
                  const scheme = mesocycle.progression_schemes.find((p) => p.muscle_group === group);
                  const freqKey = `freq-${frequency?.id}`;
                  const schemeKey = `scheme-${scheme?.id}`;
                  return (
                    <div key={group} className="pl-3">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="w-24">{group}</span>
                        <span className="text-zinc-500">you train it {daysTraining(mesocycle, group)}x/week</span>
                        {frequency && (
                          <span>
                            research suggests {frequency.frequency}x/week
                            <SourcesBadge
                              citations={frequency.supporting_citations}
                              note={frequency.grounding_note}
                              open={openSources === freqKey}
                              onToggle={() => toggleSources(freqKey)}
                            />
                          </span>
                        )}
                        {scheme && (
                          <span>
                            {scheme.scheme} progression
                            <SourcesBadge
                              citations={scheme.supporting_citations}
                              note={scheme.grounding_note}
                              open={openSources === schemeKey}
                              onToggle={() => toggleSources(schemeKey)}
                            />
                          </span>
                        )}
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
                      {frequency && openSources === freqKey && (
                        <SourcesPanel
                          heading={`Why research suggests ${frequency.frequency}x/week for ${group}`}
                          citations={frequency.supporting_citations}
                          note={frequency.grounding_note}
                        />
                      )}
                      {scheme && openSources === schemeKey && (
                        <SourcesPanel
                          heading={`Why ${scheme.scheme} progression for ${group}`}
                          citations={scheme.supporting_citations}
                          note={scheme.grounding_note}
                        />
                      )}
                    </div>
                  );
                })}
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
                        {slot.exercise_name} ({slot.muscle_group}
                        {slot.secondary_muscle_groups.length > 0 && (
                          <span className="text-zinc-400"> · also {slot.secondary_muscle_groups.join(", ")}</span>
                        )}
                        )
                      </p>
                      <span className="flex gap-3">
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => generateExercise(slot)}
                          className={actionClass}
                        >
                          {busyKey === `exercise-${slot.id}` ? "generating..." : "generate exercise"}
                        </button>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => deleteExercise(slot)}
                          className={`${actionClass} text-red-600`}
                        >
                          {busyKey === `delete-exercise-${slot.id}` ? "deleting..." : "delete exercise"}
                        </button>
                      </span>
                    </div>
                    <ul className="flex flex-col gap-1 mt-1">
                      {slot.weekly_prescriptions.map((wp) => {
                        const label = `${slot.exercise_name}, week ${wp.week_number}`;
                        const isAnchored = anchoredFieldId === wp.id;
                        const setsKey = `wp-${wp.id}-sets`;
                        const loadKey = `wp-${wp.id}-load`;
                        return (
                          <li
                            key={wp.id}
                            className={`flex flex-col rounded px-2 py-1 ${
                              isAnchored ? "bg-indigo-100 dark:bg-indigo-950" : ""
                            }`}
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <span>
                                week {wp.week_number}:{" "}
                                {isPlaceholder(wp) ? (
                                  <span className="text-zinc-400">not generated yet</span>
                                ) : (
                                  <>
                                    {wp.sets > 0 ? `${wp.sets} sets` : "sets n/a"}
                                    <SourcesBadge
                                      citations={wp.sets_citations}
                                      note={wp.sets_grounding_note}
                                      open={openSources === setsKey}
                                      onToggle={() => toggleSources(setsKey)}
                                    />
                                    {" - "}
                                    {wp.reps || "reps n/a"}
                                    {" - "}
                                    {wp.load || "load n/a"}
                                    <SourcesBadge
                                      citations={wp.load_citations}
                                      note={wp.load_grounding_note}
                                      open={openSources === loadKey}
                                      onToggle={() => toggleSources(loadKey)}
                                    />
                                  </>
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
                                  {isAnchored ? "anchored" : "ask / adjust"}
                                </button>
                              </span>
                            </div>
                            {openSources === setsKey && (
                              <SourcesPanel
                                heading={`Why ${wp.sets} sets`}
                                citations={wp.sets_citations}
                                note={wp.sets_grounding_note}
                              />
                            )}
                            {openSources === loadKey && (
                              <SourcesPanel
                                heading={`Why ${wp.load}`}
                                citations={wp.load_citations}
                                note={wp.load_grounding_note}
                              />
                            )}
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
