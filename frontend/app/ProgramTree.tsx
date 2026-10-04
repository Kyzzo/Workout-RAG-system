"use client";

import { useEffect, useRef, useState } from "react";
import { runBlockGeneration } from "./blockGeneration";
import ProgressionGuide from "./ProgressionGuide";
import { SourcesBadge, SourcesPanel } from "./Citations";
import { AddDayForm, AddExerciseForm, AddMesocycleForm } from "./StructureForms";
import {
  VOLUME_LABELS,
  type DayTemplate,
  type ExerciseSlot,
  type Mesocycle,
  type Program,
  type RuleJustification,
  type WeeklyPrescription,
} from "./types";
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
  return wp.sets === 0 && !wp.reps && !wp.load && !wp.rir;
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

// Weekly sets the block actually gives a muscle (first week): full sets
// from exercises where it's the main muscle, half from secondaries.
function deliveredSets(mesocycle: Mesocycle, group: string) {
  let total = 0;
  for (const slot of mesocycle.day_templates.flatMap((d) => d.exercise_slots)) {
    const sets = slot.weekly_prescriptions[0]?.sets ?? 0;
    if (slot.muscle_group === group) total += sets;
    else if (slot.secondary_muscle_groups.includes(group)) total += sets / 2;
  }
  return Math.round(total);
}

// Hypertrophy prescriptions are the same every week (progression happens
// session to session, see ProgressionGuide), so they're shown once per
// exercise. Strength lists each week because its loads progress - and so
// does hypertrophy if its weeks ever differ (e.g. older data), so a single
// line never hides a difference.
function rowsToShow(slot: ExerciseSlot, strength: boolean) {
  const weeks = slot.weekly_prescriptions;
  const first = weeks[0];
  const same = (wp: WeeklyPrescription) =>
    wp.sets === first.sets && wp.reps === first.reps && wp.load === first.load && wp.rir === first.rir;
  if (!strength && first && weeks.every(same)) return [{ wp: first, everyWeek: true }];
  return weeks.map((wp) => ({ wp, everyWeek: false }));
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
  // Days start collapsed so a long program reads as an outline; open the
  // ones you're looking at.
  const [openDays, setOpenDays] = useState<Set<number>>(new Set());
  const toggleDay = (id: number) =>
    setOpenDays((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleSources = (key: string) => setOpenSources((current) => (current === key ? null : key));
  // Whole-block generation runs as many sequential requests; progress shows
  // where it is, and cancel takes effect between requests (the one already
  // in flight finishes and is saved).
  const [blockProgress, setBlockProgress] = useState<string | null>(null);
  const cancelBlock = useRef(false);
  // The verified sources for the even-split rule behind every split sets
  // value - the same for every program, fetched once.
  const [splitRule, setSplitRule] = useState<RuleJustification | null>(null);
  useEffect(() => {
    let stale = false;
    (async () => {
      try {
        const rule = await api<RuleJustification>("/rules/even_session_split");
        if (!stale) setSplitRule(rule);
      } catch {
        // Optional context; the sets' own sources still show without it.
      }
    })();
    return () => {
      stale = true;
    };
  }, [api]);

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
      return `Generated reps and effort${program.goal === "strength" ? ", and load," : ""} for "${slot.exercise_name}" across every week.`;
    });
  }

  function generateVolume(mesocycle: Mesocycle, muscleGroup: string) {
    return runAction(`volume-${mesocycle.id}-${muscleGroup}`, async () => {
      const result = await api<{
        volume: { weekly_sets: number };
        delivered_weekly_sets: number;
        exercises_added: string[];
      }>(`/mesocycles/${mesocycle.id}/generate-weekly-volume`, {
        method: "POST",
        body: { muscle_group: muscleGroup },
      });
      const { weekly_sets } = result.volume;
      const added = result.exercises_added;
      return (
        `${muscleGroup}: research suggests ${weekly_sets} sets/week; split across its exercises the plan gives ` +
        `${result.delivered_weekly_sets}.` +
        (added.length > 0
          ? ` Added ${added.join(", ")} so the sets are spread across exercises - use "generate reps & effort" on ${added.length === 1 ? "it" : "them"}.`
          : "") +
        (result.delivered_weekly_sets < weekly_sets ? " Add an exercise or a day to get closer." : "")
      );
    });
  }

  async function generateBlock(mesocycle: Mesocycle) {
    const strength = program.goal === "strength";
    const confirmed = window.confirm(
      `Generate every number in "${mesocycle.name}"?\n\n` +
        "1. Research frequency for each muscle group, shown next to how often you actually train it (no days are added).\n" +
        "2. Weekly volume for each muscle group (cited), split across its exercises - at most " +
        `${strength ? 5 : 3} sets per exercise` +
        (strength ? ".\n" : "; exercises are added where a muscle needs more than that.\n") +
        `3. Reps, effort (RIR)${strength ? " and load (%1RM)" : ""} for every exercise, applied to all weeks.\n` +
        (strength ? "4. Progression for each muscle group.\n" : "") +
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
  // Strength prescribes a %1RM load as well as effort; hypertrophy only effort.
  const strength = program.goal === "strength";

  return (
    <div className="flex flex-col gap-4 w-full text-sm">
      <p className="text-zinc-500">
        Program #{program.id} - goal: {program.goal} · {VOLUME_LABELS[program.volume_preference] ?? program.volume_preference}
      </p>
      {/* Strength progression is built into the loads (cited linear scheme);
          hypertrophy progression is a principle applied session to session. */}
      {!strength && program.mesocycles.length > 0 && <ProgressionGuide />}

      {busy && !blockProgress && (
        <p className="text-indigo-600 dark:text-indigo-400 text-xs">Generating - this can take a little while...</p>
      )}
      {blockProgress && (
        <div className="flex items-center gap-3 text-indigo-600 dark:text-indigo-400 text-xs">
          <span>{blockProgress}... keep this tab open until it finishes</span>
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
              <details className="text-xs border rounded px-3 py-2">
                <summary className="cursor-pointer text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Per muscle dosing
                  <span className="text-zinc-500 font-normal text-xs ml-2">
                    {"·"} volume, frequency{strength ? " and progression" : ""} for {muscleGroups.length} muscle
                    {muscleGroups.length === 1 ? "" : "s"}
                  </span>
                </summary>
                <div className="flex flex-col mt-2">
                  {muscleGroups.map((group) => {
                    const frequency = mesocycle.muscle_group_frequencies.find((f) => f.muscle_group === group);
                    const volume = mesocycle.muscle_group_volumes.find((v) => v.muscle_group === group);
                    const scheme = mesocycle.progression_schemes.find((p) => p.muscle_group === group);
                    const freqKey = `freq-${frequency?.id}`;
                    const volumeKey = `volume-${volume?.id}`;
                    const schemeKey = `scheme-${scheme?.id}`;
                    const delivered = deliveredSets(mesocycle, group);
                    return (
                      <div key={group} className="py-1.5 border-b last:border-b-0">
                        <div className="flex flex-wrap items-center gap-3">
                          <span className="w-24">{group}</span>
                          <span className="text-zinc-500">you train it {daysTraining(mesocycle, group)}x/week</span>
                          {volume && (
                            <span>
                              {volume.weekly_sets} sets/week suggested
                              <SourcesBadge
                                citations={volume.supporting_citations}
                                note={volume.grounding_note}
                                open={openSources === volumeKey}
                                onToggle={() => toggleSources(volumeKey)}
                              />
                              <span className={delivered < volume.weekly_sets ? "text-amber-600" : "text-zinc-500"}>
                                {" "}
                                · plan gives {delivered}
                                {delivered < volume.weekly_sets && " (add an exercise or a day)"}
                              </span>
                            </span>
                          )}
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
                            onClick={() => generateVolume(mesocycle, group)}
                            className={actionClass}
                          >
                            {busyKey === `volume-${mesocycle.id}-${group}` ? "generating..." : "generate volume"}
                          </button>
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
                        {volume && openSources === volumeKey && (
                          <SourcesPanel
                            heading={`Why research suggests ${volume.weekly_sets} weekly sets for ${group}`}
                            citations={volume.supporting_citations}
                            note={volume.grounding_note}
                          />
                        )}
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
              </details>
            )}

            {mesocycle.day_templates.map((day, dayIndex) => (
              <div key={day.id} className="pl-3 border-l flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => toggleDay(day.id)}
                    aria-expanded={openDays.has(day.id)}
                    className="font-medium text-zinc-700 dark:text-zinc-300 text-left"
                  >
                    <span className="inline-block w-4">{openDays.has(day.id) ? "▾" : "▸"}</span>
                    Day {dayIndex + 1}: {day.name}
                    {day.rest_days_before !== null && (
                      <span className="text-zinc-500 font-normal text-xs ml-2">
                        ({day.rest_days_before} rest day{day.rest_days_before === 1 ? "" : "s"} before)
                      </span>
                    )}
                    <span className="text-zinc-500 font-normal text-xs ml-2">
                      {"·"} {day.exercise_slots.length} exercise{day.exercise_slots.length === 1 ? "" : "s"}
                    </span>
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => deleteDay(day)}
                    className={`${actionClass} text-red-600`}
                  >
                    {busyKey === `delete-day-${day.id}` ? "deleting..." : "delete day"}
                  </button>
                </div>
                {openDays.has(day.id) && (
                  <>
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
                              {busyKey === `exercise-${slot.id}` ? "generating..." : "generate reps & effort"}
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
                          {rowsToShow(slot, strength).map(({ wp, everyWeek }) => {
                            const label = everyWeek ? slot.exercise_name : `${slot.exercise_name}, week ${wp.week_number}`;
                            const isAnchored = anchoredFieldId === wp.id;
                            // Split sets carry no per-exercise citations; their
                            // evidence is the muscle's cited weekly volume.
                            const muscleVolume = mesocycle.muscle_group_volumes.find((v) => v.muscle_group === slot.muscle_group);
                            const setsCitations =
                              wp.sets_citations.length > 0 ? wp.sets_citations : (muscleVolume?.supporting_citations ?? []);
                            // Each value with its own sources: sets (a share of the
                            // muscle's cited weekly volume), reps, load (%1RM,
                            // strength only) and effort (RIR).
                            const values = [
                              {
                                field: "sets",
                                text: wp.sets > 0 ? `${wp.sets} sets` : "sets n/a",
                                citations: setsCitations,
                                note: wp.sets_grounding_note,
                                heading: `Why ${wp.sets} sets`,
                              },
                              {
                                field: "reps",
                                text: wp.reps ? `${wp.reps} reps` : "reps n/a",
                                citations: wp.reps_citations,
                                note: wp.reps_grounding_note,
                                heading: `Why ${wp.reps} reps`,
                              },
                              ...(strength || wp.load
                                ? [{
                                    field: "load",
                                    text: wp.load ? `@ ${wp.load}` : "load n/a",
                                    citations: wp.load_citations,
                                    note: wp.load_grounding_note,
                                    heading: `Why ${wp.load}`,
                                  }]
                                : []),
                              {
                                field: "rir",
                                text: wp.rir || "effort n/a",
                                citations: wp.rir_citations,
                                note: wp.rir_grounding_note,
                                heading: `Why ${wp.rir}`,
                              },
                            ];
                            const open = values.find((v) => openSources === `wp-${wp.id}-${v.field}`);
                            return (
                              <li
                                key={wp.id}
                                className={`flex flex-col rounded px-2 py-1 ${
                                  isAnchored ? "bg-indigo-100 dark:bg-indigo-950" : ""
                                }`}
                              >
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span>
                                    {everyWeek ? "every week" : `week ${wp.week_number}`}:{" "}
                                    {isPlaceholder(wp) ? (
                                      <span className="text-zinc-400">not generated yet</span>
                                    ) : (
                                      values.map((v, i) => (
                                        <span key={v.field}>
                                          {i > 0 && " · "}
                                          {v.text}
                                          <SourcesBadge
                                            citations={v.citations}
                                            note={v.note}
                                            open={openSources === `wp-${wp.id}-${v.field}`}
                                            onToggle={() => toggleSources(`wp-${wp.id}-${v.field}`)}
                                          />
                                        </span>
                                      ))
                                    )}
                                  </span>
                                  <span className="flex gap-3">
                                    {/* Regenerating one week's sets only makes sense
                                        when weeks are listed separately. */}
                                    {!everyWeek && (
                                      <button
                                        type="button"
                                        disabled={busy}
                                        onClick={() => generatePrescription(wp, "volume")}
                                        className={actionClass}
                                      >
                                        {busyKey === `volume-${wp.id}` ? "generating..." : "gen sets"}
                                      </button>
                                    )}
                                    {strength && (
                                      <button
                                        type="button"
                                        disabled={busy}
                                        onClick={() => generatePrescription(wp, "intensity")}
                                        className={actionClass}
                                      >
                                        {busyKey === `intensity-${wp.id}` ? "generating..." : "gen load"}
                                      </button>
                                    )}
                                    <button
                                      type="button"
                                      onClick={() => onAskAbout(wp, label)}
                                      className={`${actionClass} text-indigo-600 dark:text-indigo-400`}
                                    >
                                      {isAnchored ? "anchored" : "ask / adjust"}
                                    </button>
                                  </span>
                                </div>
                                {open && (
                                  <SourcesPanel
                                    heading={open.heading}
                                    citations={open.citations}
                                    note={open.note}
                                    rule={
                                      open.field === "sets" && splitRule && wp.sets_grounding_note?.startsWith("Share of")
                                        ? { heading: "Why the sets are spread evenly across sessions", justification: splitRule }
                                        : null
                                    }
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
                  </>
                )}
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
