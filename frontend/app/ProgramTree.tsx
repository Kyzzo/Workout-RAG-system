"use client";

import { useEffect, useRef, useState } from "react";
import { runBlockGeneration } from "./blockGeneration";
import { CaveatNote, SourcesBadge, SourcesPanel } from "./Citations";
import { useDialogs } from "./Dialogs";
import GenerationProgress from "./GenerationProgress";
import { Alert, ChevronRight, Layers, Message, Pencil, Refresh, Swap, Trash, Undo, Zap } from "./Icons";
import ProgressionGuide from "./ProgressionGuide";
import { RuleSources } from "./RuleSources";
import { AddDayForm, AddExerciseForm, AddMesocycleForm } from "./StructureForms";
import {
  type DayTemplate,
  type ExerciseSlot,
  type Mesocycle,
  type Program,
  type RuleJustification,
  type SupportingCitation,
  type WeeklyPrescription,
} from "./types";
import { Menu, Notice, Spinner } from "./ui";
import { useApi } from "./useApi";

type FrequencyResult = {
  frequency: { muscle_group: string; frequency: number; grounding_note: string | null };
  days_added: unknown[];
};

export type SwapResult = {
  old_name: string;
  new_name: string;
  changes: string[];
  change_id: number;
  pending: boolean;
};

export function swapSummary(result: { old_name: string; new_name: string; changes: string[] }): string {
  const others = result.changes.filter((c) => !c.includes(" - the new exercise:"));
  return (
    `Swapped "${result.old_name}" for "${result.new_name}".` +
    (others.length > 0 ? ` Also changed: ${others.join("; ")}.` : " Nothing else in the block changed.")
  );
}

// "constant": a muscle with only accessory lifts - the trials periodized
// their main lifts only, so nothing is scheduled.
function schemeLabel(scheme: string): string {
  if (scheme === "constant") return "none scheduled (accessories only)";
  if (scheme === "undulating") return "daily undulating";
  return scheme;
}

type ProgressionResult = {
  scheme: { muscle_group: string; scheme: string; grounding_note: string | null };
  updated_prescriptions: unknown[];
};

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// sets=0 with an empty load is the backend's "not generated yet" placeholder
// state (see create_exercise_slot / _clone_day_for_muscle_group).
function isPlaceholder(wp: WeeklyPrescription) {
  return wp.sets === 0 && !wp.reps && !wp.load && !wp.rir;
}

function generatedCount(slots: ExerciseSlot[]) {
  return slots.flatMap((s) => s.weekly_prescriptions).filter((wp) => !isPlaceholder(wp)).length;
}

function deleteWarning(slots: ExerciseSlot[]) {
  const generated = generatedCount(slots);
  return generated > 0
    ? `This also deletes ${generated} generated week${generated === 1 ? "" : "s"} of values and their citations. This can't be undone.`
    : "This can't be undone.";
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

// What a swap would change besides the exercise itself, for its preview.
function SwapPreview({ changes }: { changes: string[] }) {
  const own = changes.filter((c) => c.includes(" - the new exercise:"));
  const others = changes.filter((c) => !c.includes(" - the new exercise:"));
  return (
    <div className="flex flex-col gap-3">
      {own.length > 0 && (
        <ul className="flex flex-col gap-1">
          {own.map((c) => (
            <li key={c}>{c.replace(/^.* - the new exercise: /, "The new exercise: ")}</li>
          ))}
        </ul>
      )}
      {others.length > 0 ? (
        <div className="rounded-xl bg-warn-soft p-3 text-warn">
          <p className="mb-1.5 font-medium">This also changes</p>
          <ul className="flex list-disc flex-col gap-1 ps-4">
            {others.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p>Nothing else in the block changes.</p>
      )}
      <p className="text-xs text-fg-subtle">You can undo it afterwards.</p>
    </div>
  );
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
  const dialogs = useDialogs();
  // One generation at a time: each call is several seconds of retrieval +
  // generation + citation verification, and running two against the same
  // muscle group at once would race on the sibling-volume context.
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The last swap made from this view, undoable from its notice.
  const [undoable, setUndoable] = useState<{ id: number; label: string } | null>(null);
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
        `${capitalize(muscleGroup)}: ${result.frequency.frequency}x/week` +
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
        `${capitalize(muscleGroup)}: ${schemeLabel(result.scheme.scheme)} progression - ${updated} week value${updated === 1 ? "" : "s"} updated.` +
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
        `${capitalize(muscleGroup)}: research suggests ${weekly_sets} sets/week; split across its exercises the plan gives ` +
        `${result.delivered_weekly_sets}.` +
        (added.length > 0
          ? ` Added ${added.join(", ")} so the sets are spread across exercises - use "Generate reps & effort" on ${added.length === 1 ? "it" : "them"}.`
          : "") +
        (result.delivered_weekly_sets < weekly_sets ? " Add an exercise or a day to get closer." : "")
      );
    });
  }

  async function generateBlock(mesocycle: Mesocycle) {
    const strength = program.goal === "strength";
    const confirmed = await dialogs.confirm({
      title: `Generate every number in "${mesocycle.name}"?`,
      body: (
        <div className="flex flex-col gap-3">
          <ol className="flex list-decimal flex-col gap-1.5 ps-5">
            <li>
              Research frequency for each muscle group, shown next to how often you actually train it (no days are
              added).
            </li>
            <li>
              Weekly volume for each muscle group (cited), split across its exercises - at most {strength ? 5 : 3} sets
              per exercise{strength ? "." : "; exercises are added where a muscle needs more than that."}
            </li>
            <li>Reps, effort (RIR){strength ? " and load (%1RM)" : ""} for every exercise, applied to all weeks.</li>
            {strength && <li>Progression for each muscle group.</li>}
          </ol>
          <p>Existing generated values in this block are replaced. This can take a few minutes.</p>
        </div>
      ),
      confirmLabel: "Generate block",
    });
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

  async function deleteDay(day: DayTemplate) {
    const ok = await dialogs.confirm({
      title: `Delete "${day.name}"?`,
      body: `Its ${day.exercise_slots.length} exercise${day.exercise_slots.length === 1 ? "" : "s"} go with it. ${deleteWarning(day.exercise_slots)}`,
      confirmLabel: "Delete day",
      danger: true,
    });
    if (!ok) return;
    return runAction(`delete-day-${day.id}`, async () => {
      await api(`/day-templates/${day.id}`, { method: "DELETE" });
      return `Deleted day "${day.name}".`;
    });
  }

  async function rename(path: string, what: string, current: string) {
    const name = await dialogs.prompt({ title: `Rename ${what}`, label: "Name", defaultValue: current });
    if (name === null || !name.trim() || name.trim() === current) return;
    return runAction(`rename-${path}`, async () => {
      await api(path, { method: "PATCH", body: { name } });
      return `Renamed the ${what} to "${name.trim()}".`;
    });
  }

  // Same target muscle; blank asks for a suggestion. Previewed first: the
  // confirm dialog lists everything it would change elsewhere (rotation on
  // other days, other muscles' sets); nothing is applied unless confirmed.
  async function swapExercise(slot: ExerciseSlot) {
    const name = await dialogs.prompt({
      title: `Swap ${slot.exercise_name}`,
      body: `Pick another ${slot.muscle_group} exercise, or leave it blank to have one suggested. You'll see everything the swap changes before anything is applied.`,
      label: "Replacement (optional)",
      placeholder: "e.g. Dumbbell Bench Press",
      confirmLabel: "Preview swap",
      allowEmpty: true,
    });
    if (name === null) return;
    return runAction(`swap-${slot.id}`, async () => {
      const preview = await api<SwapResult>(`/exercise-slots/${slot.id}/swap`, {
        method: "POST", body: { exercise_name: name.trim() || null },
      });
      const ok = await dialogs.confirm({
        title: `Swap ${preview.old_name} for ${preview.new_name}?`,
        body: <SwapPreview changes={preview.changes} />,
        confirmLabel: "Confirm swap",
      });
      if (!ok) {
        await api(`/changes/${preview.change_id}`, { method: "DELETE" });
        return "Swap cancelled - nothing changed.";
      }
      const applied = await api<SwapResult>(`/changes/${preview.change_id}/confirm`, { method: "POST" });
      setUndoable({ id: applied.change_id, label: `swap of ${applied.old_name}` });
      return swapSummary(applied);
    });
  }

  function undoLast() {
    if (!undoable) return;
    const target = undoable;
    return runAction("undo", async () => {
      await api(`/changes/${target.id}/undo`, { method: "POST" });
      setUndoable(null);
      return `Undid the ${target.label}.`;
    });
  }

  async function deleteExercise(slot: ExerciseSlot) {
    const ok = await dialogs.confirm({
      title: `Delete ${slot.exercise_name}?`,
      body: deleteWarning([slot]),
      confirmLabel: "Delete exercise",
      danger: true,
    });
    if (!ok) return;
    return runAction(`delete-exercise-${slot.id}`, async () => {
      await api(`/exercise-slots/${slot.id}`, { method: "DELETE" });
      return `Deleted "${slot.exercise_name}".`;
    });
  }

  const busy = busyKey !== null || externalBusy;
  // Strength prescribes a %1RM load as well as effort; hypertrophy only effort.
  const strength = program.goal === "strength";

  return (
    <div className="flex w-full flex-col gap-5">
      {/* Strength progression is built into the loads (a cited scheme chosen
          by training status); hypertrophy progression is a principle applied
          session to session. */}
      {!strength && program.mesocycles.length > 0 && <ProgressionGuide />}

      {busy && !blockProgress && !externalBusy && (
        <Notice tone="info">
          <span className="flex items-center gap-2">
            Working on it - generation can take a little while.
            <Spinner className="size-3.5" />
          </span>
        </Notice>
      )}
      {notice && (
        <Notice
          tone="success"
          action={
            undoable && notice.startsWith("Swapped") ? (
              <button type="button" disabled={busy} onClick={undoLast} className="btn btn-secondary btn-sm">
                <Undo className="size-3.5" />
                Undo
              </button>
            ) : undefined
          }
        >
          {notice}
        </Notice>
      )}
      {error && <Notice tone="error">{error}</Notice>}

      {program.mesocycles.length === 0 && (
        <div className="card flex flex-col items-center gap-2 px-6 py-10 text-center">
          <span className="grid size-10 place-items-center rounded-xl bg-surface-3 text-fg-muted">
            <Layers className="size-5" />
          </span>
          <p className="font-medium">No training blocks yet</p>
          <p className="max-w-sm text-sm text-fg-muted">Add a block below, then add days and exercises to it.</p>
        </div>
      )}

      {program.mesocycles.map((mesocycle) => {
        const muscleGroups = muscleGroupsIn(mesocycle);
        const slots = mesocycle.day_templates.flatMap((d) => d.exercise_slots);
        const ungenerated = slots.some((s) => s.weekly_prescriptions.some(isPlaceholder));
        return (
          <section key={mesocycle.id} className="card flex flex-col">
            <header className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line px-5 py-4">
              <div className="min-w-0 flex-1">
                <p className="eyebrow">
                  Weeks {mesocycle.start_week}–{mesocycle.end_week}
                </p>
                <div className="mt-0.5 flex items-center gap-1">
                  <h3 className="truncate text-lg font-semibold tracking-tight">{mesocycle.name}</h3>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => rename(`/mesocycles/${mesocycle.id}`, "block", mesocycle.name)}
                    className="icon-btn size-7"
                    aria-label={`Rename block ${mesocycle.name}`}
                    title="Rename block"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                </div>
              </div>
              {muscleGroups.length > 0 && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => generateBlock(mesocycle)}
                  className={`btn ${ungenerated ? "btn-primary" : "btn-secondary"}`}
                >
                  {busyKey === `block-${mesocycle.id}` ? (
                    <Spinner className="size-4" />
                  ) : ungenerated ? (
                    <Zap className="size-4" />
                  ) : (
                    <Refresh className="size-4" />
                  )}
                  {busyKey === `block-${mesocycle.id}`
                    ? "Generating..."
                    : ungenerated
                      ? "Generate block"
                      : "Regenerate block"}
                </button>
              )}
            </header>

            <div className="flex flex-col gap-4 p-4 sm:p-5">
              {blockProgress && busyKey === `block-${mesocycle.id}` && (
                <GenerationProgress
                  progress={blockProgress}
                  strength={strength}
                  includeExercises={false}
                  onCancel={() => (cancelBlock.current = true)}
                />
              )}

              {muscleGroups.length > 0 && (
                <details className="group rounded-xl border border-line">
                  <summary className="flex cursor-pointer items-center gap-2.5 px-4 py-3 select-none">
                    <Layers className="size-4 text-fg-subtle" />
                    <span className="text-sm font-medium">Per-muscle dosing</span>
                    <span className="hidden flex-1 truncate text-xs text-fg-subtle sm:block">
                      Volume, frequency{strength ? " and progression" : ""} for {muscleGroups.length} muscle
                      {muscleGroups.length === 1 ? "" : "s"}
                    </span>
                    <span className="flex-1 sm:hidden" />
                    <ChevronRight className="size-4 text-fg-subtle transition-transform duration-200 group-open:rotate-90" />
                  </summary>
                  <div className="animate-in border-t border-line">
                    {/* Hypertrophy frequency isn't a generated number: with weekly
                        sets matched it doesn't change growth detectably, so the
                        cited finding is shown once and each muscle shows its
                        plan's frequency and per-session load instead. */}
                    {!strength && (
                      <div className="border-b border-line px-4 py-3">
                        <RuleSources
                          label="Frequency"
                          text={
                            "With weekly sets matched, studies show no significant growth difference " +
                            "between training a muscle 2x and 3x a week. More sessions help at higher volumes, " +
                            "since gains within one session diminish past ~11 sets."
                          }
                          ruleKeys={["frequency_matched_volume", "per_session_diminishing_returns"]}
                          secondHeading="Why more sessions help at higher volume"
                        />
                      </div>
                    )}
                    <div className="scroll-thin overflow-x-auto">
                      <table className="w-full min-w-[34rem] text-sm">
                        <thead>
                          <tr className="text-start text-xs text-fg-subtle">
                            <th className="px-4 py-2.5 text-start font-medium">Muscle</th>
                            <th className="px-3 py-2.5 text-end font-medium">You train it</th>
                            {strength && <th className="px-3 py-2.5 text-end font-medium">Research</th>}
                            <th className="px-3 py-2.5 text-end font-medium">Suggested sets/wk</th>
                            <th className="px-3 py-2.5 text-end font-medium">Plan gives</th>
                            {!strength && <th className="px-3 py-2.5 text-end font-medium">Per session</th>}
                            {strength && <th className="px-3 py-2.5 text-start font-medium">Progression</th>}
                            <th className="w-12 px-2 py-2.5">
                              <span className="sr-only">Actions</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {muscleGroups.map((group) => {
                            const frequency = mesocycle.muscle_group_frequencies.find((f) => f.muscle_group === group);
                            const volume = mesocycle.muscle_group_volumes.find((v) => v.muscle_group === group);
                            const scheme = mesocycle.progression_schemes.find((p) => p.muscle_group === group);
                            const freqKey = `freq-${frequency?.id}`;
                            const volumeKey = `volume-${volume?.id}`;
                            const schemeKey = `scheme-${scheme?.id}`;
                            const delivered = deliveredSets(mesocycle, group);
                            const trainedDays = daysTraining(mesocycle, group);
                            const short = volume !== undefined && delivered < volume.weekly_sets;
                            const rowBusy = [
                              `volume-${mesocycle.id}-${group}`,
                              `frequency-${mesocycle.id}-${group}`,
                              `progression-${mesocycle.id}-${group}`,
                            ].includes(busyKey ?? "");
                            const panel =
                              volume && openSources === volumeKey ? (
                                <SourcesPanel
                                  heading={`Why research suggests ${volume.weekly_sets} weekly sets for ${group}`}
                                  citations={volume.supporting_citations}
                                  note={volume.grounding_note}
                                />
                              ) : strength && frequency && openSources === freqKey ? (
                                <SourcesPanel
                                  heading={`Why research suggests ${frequency.frequency}x/week for ${group}`}
                                  citations={frequency.supporting_citations}
                                  note={frequency.grounding_note}
                                />
                              ) : scheme && openSources === schemeKey ? (
                                <SourcesPanel
                                  heading={
                                    scheme.scheme === "constant"
                                      ? `Why ${group} has no scheduled progression`
                                      : `Why ${schemeLabel(scheme.scheme)} progression: ` +
                                        (program.trained ? "you've lifted consistently for 1+ year" : "you're newer to lifting")
                                  }
                                  citations={scheme.supporting_citations}
                                  note={scheme.grounding_note}
                                />
                              ) : null;
                            return [
                              <tr key={group} className="border-t border-line">
                                <td className="px-4 py-2.5 font-medium">
                                  <span className="flex items-center gap-2">
                                    {capitalize(group)}
                                    {rowBusy && <Spinner className="size-3.5 text-accent-text" />}
                                  </span>
                                </td>
                                <td className="px-3 py-2.5 text-end tabular-nums text-fg-muted">
                                  {trainedDays}x/wk
                                </td>
                                {strength && (
                                  <td className="px-3 py-2.5 text-end tabular-nums">
                                    {frequency ? (
                                      <span className="inline-flex items-center gap-1.5">
                                        {frequency.frequency}x/wk
                                        <SourcesBadge
                                          what={`${group} frequency`}
                                          citations={frequency.supporting_citations}
                                          note={frequency.grounding_note}
                                          open={openSources === freqKey}
                                          onToggle={() => toggleSources(freqKey)}
                                        />
                                      </span>
                                    ) : (
                                      <span className="text-fg-subtle">—</span>
                                    )}
                                  </td>
                                )}
                                <td className="px-3 py-2.5 text-end tabular-nums">
                                  {volume ? (
                                    <span className="inline-flex items-center gap-1.5">
                                      {volume.weekly_sets}
                                      <SourcesBadge
                                        what={`${group} weekly sets`}
                                        citations={volume.supporting_citations}
                                        note={volume.grounding_note}
                                        open={openSources === volumeKey}
                                        onToggle={() => toggleSources(volumeKey)}
                                      />
                                    </span>
                                  ) : (
                                    <span className="text-fg-subtle">—</span>
                                  )}
                                </td>
                                <td className={`px-3 py-2.5 text-end tabular-nums ${short ? "text-warn" : "text-fg-muted"}`}>
                                  <span
                                    className="inline-flex items-center gap-1"
                                    title={short ? "Below the suggestion - add an exercise or a day" : undefined}
                                  >
                                    {short && <Alert className="size-3.5" />}
                                    {delivered}
                                    {short && <span className="sr-only"> (below the suggestion - add an exercise or a day)</span>}
                                  </span>
                                </td>
                                {!strength && (
                                  <td className="px-3 py-2.5 text-end tabular-nums text-fg-muted">
                                    {trainedDays > 0 ? `~${Math.round(delivered / trainedDays)}` : "—"}
                                  </td>
                                )}
                                {strength && (
                                  <td className="px-3 py-2.5">
                                    {scheme ? (
                                      <span className="inline-flex items-center gap-1.5">
                                        <span className="capitalize">{schemeLabel(scheme.scheme)}</span>
                                        <SourcesBadge
                                          what={`${group} progression`}
                                          citations={scheme.supporting_citations}
                                          note={scheme.grounding_note}
                                          open={openSources === schemeKey}
                                          onToggle={() => toggleSources(schemeKey)}
                                        />
                                      </span>
                                    ) : (
                                      <span className="text-fg-subtle">—</span>
                                    )}
                                  </td>
                                )}
                                <td className="px-2 py-1.5 text-end">
                                  <Menu
                                    label={`Actions for ${group}`}
                                    disabled={busy}
                                    items={[
                                      {
                                        label: "Generate weekly volume",
                                        icon: <Zap className="size-4" />,
                                        onSelect: () => generateVolume(mesocycle, group),
                                      },
                                      ...(strength
                                        ? [
                                            {
                                              label: "Generate frequency",
                                              icon: <Zap className="size-4" />,
                                              onSelect: () => generateFrequency(mesocycle, group),
                                            },
                                            {
                                              label: "Generate progression",
                                              icon: <Zap className="size-4" />,
                                              onSelect: () => generateProgression(mesocycle, group),
                                            },
                                          ]
                                        : []),
                                    ]}
                                  />
                                </td>
                              </tr>,
                              panel && (
                                <tr key={`${group}-sources`}>
                                  <td colSpan={8} className="px-4 pb-3">
                                    {panel}
                                  </td>
                                </tr>
                              ),
                            ];
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </details>
              )}

              <div className="flex flex-col gap-2.5">
                {mesocycle.day_templates.map((day, dayIndex) => {
                  const open = openDays.has(day.id);
                  const dayBusy = busyKey === `delete-day-${day.id}`;
                  return (
                    <div
                      key={day.id}
                      className={`rounded-xl border transition-colors duration-150 ${
                        open ? "border-line-strong bg-surface-2/40" : "border-line hover:border-line-strong"
                      }`}
                    >
                      <div className="flex items-center gap-1 pe-2">
                        <button
                          type="button"
                          onClick={() => toggleDay(day.id)}
                          aria-expanded={open}
                          className="flex min-w-0 flex-1 items-center gap-3 rounded-xl px-3 py-3 text-start"
                        >
                          <ChevronRight
                            className={`size-4 shrink-0 text-fg-subtle transition-transform duration-200 ${open ? "rotate-90" : ""}`}
                          />
                          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-3 font-mono text-xs font-medium text-fg-muted">
                            D{dayIndex + 1}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{day.name}</span>
                            <span className="block text-xs text-fg-subtle">
                              {day.exercise_slots.length} exercise{day.exercise_slots.length === 1 ? "" : "s"}
                              {day.rest_days_before !== null && (
                                <>
                                  {" · "}
                                  {day.rest_days_before} rest day{day.rest_days_before === 1 ? "" : "s"} before
                                </>
                              )}
                            </span>
                          </span>
                          {dayBusy && <Spinner className="size-4 text-fg-subtle" />}
                        </button>
                        <Menu
                          label={`Actions for ${day.name}`}
                          disabled={busy}
                          items={[
                            {
                              label: "Rename day",
                              icon: <Pencil className="size-4" />,
                              onSelect: () => rename(`/day-templates/${day.id}`, "day", day.name),
                            },
                            {
                              label: "Delete day",
                              icon: <Trash className="size-4" />,
                              danger: true,
                              onSelect: () => deleteDay(day),
                            },
                          ]}
                        />
                      </div>
                      {open && (
                        <div className="animate-in flex flex-col border-t border-line px-3 pb-3 sm:px-4">
                          {day.exercise_slots.length === 0 && (
                            <p className="py-4 text-sm text-fg-subtle">No exercises yet.</p>
                          )}
                          <div className="flex flex-col divide-y divide-line">
                            {day.exercise_slots.map((slot) => (
                              <ExerciseBlock
                                key={slot.id}
                                slot={slot}
                                mesocycle={mesocycle}
                                strength={strength}
                                busy={busy}
                                busyKey={busyKey}
                                anchoredFieldId={anchoredFieldId}
                                openSources={openSources}
                                toggleSources={toggleSources}
                                splitRule={splitRule}
                                onAskAbout={onAskAbout}
                                onGenerate={() => generateExercise(slot)}
                                onSwap={() => swapExercise(slot)}
                                onDelete={() => deleteExercise(slot)}
                                onGeneratePrescription={generatePrescription}
                              />
                            ))}
                          </div>
                          <div className="pt-2">
                            <AddExerciseForm dayTemplateId={day.id} onAdded={onChanged} />
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <AddDayForm mesocycleId={mesocycle.id} onAdded={onChanged} />
            </div>
          </section>
        );
      })}

      <AddMesocycleForm programId={program.id} onAdded={onChanged} />
    </div>
  );
}

function ExerciseBlock({
  slot,
  mesocycle,
  strength,
  busy,
  busyKey,
  anchoredFieldId,
  openSources,
  toggleSources,
  splitRule,
  onAskAbout,
  onGenerate,
  onSwap,
  onDelete,
  onGeneratePrescription,
}: {
  slot: ExerciseSlot;
  mesocycle: Mesocycle;
  strength: boolean;
  busy: boolean;
  busyKey: string | null;
  anchoredFieldId: number | null;
  openSources: string | null;
  toggleSources: (key: string) => void;
  splitRule: RuleJustification | null;
  onAskAbout: (prescription: WeeklyPrescription, label: string) => void;
  onGenerate: () => void;
  onSwap: () => void;
  onDelete: () => void;
  onGeneratePrescription: (wp: WeeklyPrescription, field: "volume" | "intensity") => void;
}) {
  const working =
    busyKey === `exercise-${slot.id}`
      ? "Generating..."
      : busyKey === `swap-${slot.id}`
        ? "Swapping..."
        : busyKey === `delete-exercise-${slot.id}`
          ? "Deleting..."
          : null;
  const rows = rowsToShow(slot, strength);
  const showLoad = strength || slot.weekly_prescriptions.some((wp) => wp.load);
  // Week label, then sets / reps / (load) / effort, then actions. Every row
  // of an exercise shares it, so the weeks line up as columns (from sm up;
  // narrower, each row wraps as a line).
  const columns = `4.25rem minmax(0,0.8fr) minmax(0,1fr) ${showLoad ? "minmax(0,1.35fr) " : ""}minmax(0,1.1fr) auto`;
  // Split sets carry no per-exercise citations; their evidence is the
  // muscle's cited weekly volume.
  const muscleVolume = mesocycle.muscle_group_volumes.find((v) => v.muscle_group === slot.muscle_group);

  return (
    <div className="flex flex-col gap-2 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium leading-snug text-fg">{slot.exercise_name}</p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-subtle">
            <span className="chip h-5 border-transparent bg-accent-soft px-1.5 text-accent-text">{slot.muscle_group}</span>
            {slot.secondary_muscle_groups.length > 0 && <span>also {slot.secondary_muscle_groups.join(", ")}</span>}
            {working && (
              <span className="inline-flex items-center gap-1.5 text-accent-text">
                <Spinner className="size-3" />
                {working}
              </span>
            )}
          </p>
        </div>
        <Menu
          label={`Actions for ${slot.exercise_name}`}
          disabled={busy}
          items={[
            { label: "Generate reps & effort", icon: <Zap className="size-4" />, onSelect: onGenerate },
            { label: "Swap exercise", icon: <Swap className="size-4" />, onSelect: onSwap },
            { label: "Delete exercise", icon: <Trash className="size-4" />, danger: true, onSelect: onDelete },
          ]}
        />
      </div>

      <ul className="flex flex-col gap-0.5">
        {rows.map(({ wp, everyWeek }) => {
          const label = everyWeek ? slot.exercise_name : `${slot.exercise_name}, week ${wp.week_number}`;
          const isAnchored = anchoredFieldId === wp.id;
          const setsCitations: SupportingCitation[] =
            wp.sets_citations.length > 0 ? wp.sets_citations : (muscleVolume?.supporting_citations ?? []);
          // Each value with its own sources: sets (a share of the muscle's
          // cited weekly volume), reps, load (%1RM) and effort (RIR).
          const values = [
            {
              field: "sets",
              value: wp.sets > 0 ? String(wp.sets) : "—",
              unit: wp.sets === 1 ? "set" : "sets",
              citations: setsCitations,
              note: wp.sets_grounding_note,
              heading: `Why ${wp.sets} sets`,
            },
            {
              field: "reps",
              value: wp.reps || "—",
              unit: "reps",
              citations: wp.reps_citations,
              note: wp.reps_grounding_note,
              heading: `Why ${wp.reps} reps`,
            },
            ...(showLoad
              ? [
                  {
                    field: "load",
                    value: wp.load || "—",
                    unit: "",
                    citations: wp.load_citations,
                    note: wp.load_grounding_note,
                    heading: `Why ${wp.load}`,
                  },
                ]
              : []),
            {
              field: "rir",
              value: wp.rir || "—",
              unit: "",
              citations: wp.rir_citations,
              note: wp.rir_grounding_note,
              heading: `Why ${wp.rir}`,
            },
          ];
          const open = values.find((v) => openSources === `wp-${wp.id}-${v.field}`);
          const regenerate = [
            // Regenerating one week's sets only makes sense when weeks are
            // listed separately.
            ...(!everyWeek
              ? [{ label: "Regenerate sets", icon: <Refresh className="size-4" />, onSelect: () => onGeneratePrescription(wp, "volume") }]
              : []),
            ...(strength
              ? [{ label: "Regenerate load", icon: <Refresh className="size-4" />, onSelect: () => onGeneratePrescription(wp, "intensity") }]
              : []),
          ];
          const rowWorking = busyKey === `volume-${wp.id}` || busyKey === `intensity-${wp.id}`;
          return (
            <li
              key={wp.id}
              className={`rounded-lg transition-colors duration-150 ${
                isAnchored ? "bg-accent-soft ring-1 ring-accent/50" : "hover:bg-surface-3/40"
              }`}
            >
              {/* Narrow: week label and actions on a slim top line, values in
                  a 2x2 grid below. From sm up the values wrapper dissolves
                  (display: contents) so each value takes its own column of the
                  shared template and the row is one line. */}
              <div
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-2 py-2 sm:grid-cols-[var(--cols)] sm:gap-y-0 sm:py-1.5"
                style={{ "--cols": columns, "--span": values.length } as React.CSSProperties}
              >
                <span className="font-mono text-xs text-fg-subtle">
                  {everyWeek ? "Weekly" : `Wk ${wp.week_number}`}
                </span>
                <div className="col-span-2 grid grid-cols-2 gap-x-3 gap-y-1 sm:contents">
                  {isPlaceholder(wp) ? (
                    <span className="col-span-2 text-sm italic text-fg-subtle sm:[grid-column:span_var(--span)]">
                      Not generated yet
                    </span>
                  ) : (
                    values.map((v) => (
                      <span key={v.field} className="flex min-w-0 items-center gap-1.5 whitespace-nowrap">
                        <span className="text-sm font-medium tabular-nums text-fg">
                          {v.value}
                          {v.unit && v.value !== "—" && <span className="ms-1 text-xs font-normal text-fg-subtle">{v.unit}</span>}
                        </span>
                        <SourcesBadge
                          what={v.field === "rir" ? "effort" : v.field}
                          citations={v.citations}
                          note={v.note}
                          open={openSources === `wp-${wp.id}-${v.field}`}
                          onToggle={() => toggleSources(`wp-${wp.id}-${v.field}`)}
                        />
                      </span>
                    ))
                  )}
                </div>
                <span className="col-start-2 row-start-1 flex items-center justify-end gap-0.5 sm:col-start-auto sm:row-start-auto">
                  {rowWorking && <Spinner className="me-1 size-3.5 text-accent-text" />}
                  <button
                    type="button"
                    onClick={() => onAskAbout(wp, label)}
                    aria-pressed={isAnchored}
                    aria-label={`Ask about or adjust ${label}`}
                    title="Ask about or adjust this in the chat"
                    className={`btn btn-sm h-7 gap-1.5 px-2 ${
                      isAnchored ? "bg-accent text-accent-fg" : "btn-ghost text-accent-text"
                    }`}
                  >
                    <Message className="size-3.5" />
                    <span className="hidden sm:inline">{isAnchored ? "Asking" : "Ask"}</span>
                  </button>
                  {regenerate.length > 0 && (
                    <Menu label={`More for ${label}`} disabled={busy} items={regenerate} quiet />
                  )}
                </span>
              </div>
              {wp.load_fit_note && !isPlaceholder(wp) && (
                <CaveatNote className="px-2 pb-2 text-xs">{wp.load_fit_note}</CaveatNote>
              )}
              {open && (
                <div className="px-2 pb-2">
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
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
