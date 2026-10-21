"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { runBlockGeneration } from "./blockGeneration";
import { CaveatNote, SourcesBadge, SourcesPanel } from "./Citations";
import { useDialogs } from "./Dialogs";
import GenerationProgress from "./GenerationProgress";
import { Alert, ChevronDown, ChevronRight, Layers, Message, Pencil, Refresh, Swap, Trash, Undo, Zap } from "./Icons";
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
import { Menu, Notice, Segmented, Spinner } from "./ui";
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

// A block's shown week, or every week at once.
// A week number, "all" (every week as a table) or "every" (a hypertrophy
// exercise shown once because its weeks are the same).
type Week = number | "all" | "every";

// How a value moved from the week before ("70% 1RM" -> "72.5% 1RM" is up),
// by its leading number; null if it didn't change or can't be compared.
function change(before: string | number | undefined, now: string | number): "up" | "down" | null {
  if (before === undefined || String(before) === String(now)) return null;
  const a = parseFloat(String(before));
  const b = parseFloat(String(now));
  if (Number.isNaN(a) || Number.isNaN(b) || a === b) return null;
  return b > a ? "up" : "down";
}

// "12" or "11–14" for a list of numbers.
function range(values: number[]) {
  const low = Math.min(...values);
  const high = Math.max(...values);
  return low === high ? `${low}` : `${low}–${high}`;
}

// The value every muscle shares, or null if any muscle differs or lacks one.
function shared<T>(items: (T | undefined)[], key: (item: T) => string): T | null {
  const first = items[0];
  if (first === undefined) return null;
  return items.every((item) => item !== undefined && key(item) === key(first)) ? first : null;
}

// One value at the top of the dosing details, shown once for every muscle.
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <span className="text-[11px] text-fg-subtle">{label}</span>
      <span className="flex items-center gap-2 text-[15px] font-semibold tabular-nums">{children}</span>
    </div>
  );
}

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
  onAskAbout: (prescription: WeeklyPrescription, label: string, thisWeekOnly: boolean) => void;
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
  // Blocks whose dosing details table is open (the chart above it always shows).
  const [openDosing, setOpenDosing] = useState<Set<number>>(new Set());
  // Blocks whose chart is shown on phones, where it starts collapsed (the
  // header's "below target" chip summarises it); wider screens always show it.
  const [openCharts, setOpenCharts] = useState<Set<number>>(new Set());
  const toggleChart = (id: number) =>
    setOpenCharts((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleDosing = (id: number) =>
    setOpenDosing((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  // The week each block shows (its first week by default), or "all" for
  // every week at once. Only blocks whose weeks differ (strength) get a
  // picker; the rest are the same every week.
  const [weekByBlock, setWeekByBlock] = useState<Record<number, Week>>({});
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
        const weeks = [...new Set(slots.flatMap((s) => s.weekly_prescriptions.map((wp) => wp.week_number)))].sort(
          (a, b) => a - b,
        );
        const weeksDiffer = slots.some((s) => rowsToShow(s, false).length > 1);
        // Blocks whose weeks differ pick a week or "All"; a hypertrophy block
        // that's the same every week shows it once ("Every week") and can
        // still pick one week to change on its own.
        const pickWeek = weeks.length > 1 && (weeksDiffer || !strength);
        const picked = weekByBlock[mesocycle.id];
        const week: Week =
          picked === undefined || (picked === "every" && weeksDiffer) || (picked === "all" && !weeksDiffer)
            ? weeksDiffer
              ? (weeks[0] ?? "all")
              : "every"
            : picked;
        // A preview of the dosing table, shown on its collapsed row.
        const suggested = mesocycle.muscle_group_volumes
          .filter((v) => muscleGroups.includes(v.muscle_group))
          .map((v) => v.weekly_sets);
        const trainedPerWeek = muscleGroups.map((g) => daysTraining(mesocycle, g));
        const belowTarget = mesocycle.muscle_group_volumes.filter(
          (v) => muscleGroups.includes(v.muscle_group) && deliveredSets(mesocycle, v.muscle_group) < v.weekly_sets,
        ).length;
        // The dosing chart: sets per week the plan gives each muscle against
        // the research-suggested sets, on one shared scale.
        const dosing = muscleGroups.map((group) => ({
          group,
          delivered: deliveredSets(mesocycle, group),
          target: mesocycle.muscle_group_volumes.find((v) => v.muscle_group === group)?.weekly_sets,
        }));
        const dosingMax = Math.max(1, ...dosing.map((d) => Math.max(d.delivered, d.target ?? 0)));
        const dosingOpen = openDosing.has(mesocycle.id);
        const chartOpen = openCharts.has(mesocycle.id);
        // Details: a value every muscle shares (weekly sets and frequency are
        // one generated answer for all of them) is shown once above the
        // table, not on every row. A value that differs stays a column.
        const sharedVolume = shared(
          muscleGroups.map((g) => mesocycle.muscle_group_volumes.find((v) => v.muscle_group === g)),
          (v) => `${v.weekly_sets}|${v.supporting_citations.length}`,
        );
        const sharedFrequency = strength
          ? shared(
              muscleGroups.map((g) => mesocycle.muscle_group_frequencies.find((f) => f.muscle_group === g)),
              (f) => `${f.frequency}|${f.supporting_citations.length}`,
            )
          : null;
        const sharedTrained = shared(trainedPerWeek, String);
        return (
          // On phones the block drops its frame so the cards inside it
          // (chart, weeks, days) use the full width.
          <section
            key={mesocycle.id}
            className="card flex flex-col max-sm:rounded-none max-sm:border-0 max-sm:bg-transparent max-sm:shadow-none"
          >
            <header className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line px-1 pb-3 sm:px-5 sm:py-4 max-sm:border-b-0">
              <div className="min-w-0 flex-1 basis-56">
                <p className="eyebrow">
                  Weeks {mesocycle.start_week}–{mesocycle.end_week}
                  {!weeksDiffer && slots.length > 0 && weeks.length > 1 && " · same every week"}
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
                  aria-label={ungenerated ? "Generate block" : "Regenerate block"}
                  title={ungenerated ? "Generate block" : "Regenerate block"}
                  // Icon-only on phones so it sits beside the title.
                  className={`btn ${ungenerated ? "btn-primary" : "btn-secondary"} max-sm:size-10 max-sm:p-0`}
                >
                  {busyKey === `block-${mesocycle.id}` ? (
                    <Spinner className="size-4" />
                  ) : ungenerated ? (
                    <Zap className="size-4" />
                  ) : (
                    <Refresh className="size-4" />
                  )}
                  <span className="hidden sm:inline">
                    {busyKey === `block-${mesocycle.id}`
                      ? "Generating..."
                      : ungenerated
                        ? "Generate block"
                        : "Regenerate block"}
                  </span>
                </button>
              )}
            </header>

            <div className="flex flex-col gap-4 sm:p-5">
              {blockProgress && busyKey === `block-${mesocycle.id}` && (
                <GenerationProgress
                  progress={blockProgress}
                  strength={strength}
                  includeExercises={false}
                  onCancel={() => (cancelBlock.current = true)}
                />
              )}

              {muscleGroups.length > 0 && (
                // A summary panel, not another day row: a chart of weekly sets
                // per muscle against the research suggestion, always shown, with
                // the full table (sources, frequency, actions) behind Details.
                <section className="rounded-xl border border-line-strong bg-surface-2/70" aria-label="Weekly sets by muscle">
                  <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3.5 ${chartOpen ? "" : "pb-3.5 sm:pb-0"}`}>
                    <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-text">
                      <Layers className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1 basis-52">
                      <span className="block text-sm font-semibold">Weekly sets by muscle</span>
                      <span className="hidden text-xs text-fg-subtle sm:block">
                        What the plan gives vs. research
                        {suggested.length > 0 && ` (${range(suggested)} suggested)`} · trained {range(trainedPerWeek)}x/wk
                      </span>
                    </span>
                    {belowTarget > 0 && (
                      <span className="chip border-transparent bg-warn-soft text-warn">
                        <Alert className="size-3" />
                        {belowTarget} below target
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => toggleChart(mesocycle.id)}
                      aria-expanded={chartOpen}
                      className="ms-auto inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent-text sm:hidden"
                    >
                      {chartOpen ? "Hide chart" : "Show chart"}
                      <ChevronDown className={`size-4 transition-transform duration-200 ${chartOpen ? "rotate-180" : ""}`} />
                    </button>
                    <button
                      type="button"
                      onClick={() => toggleDosing(mesocycle.id)}
                      aria-expanded={dosingOpen}
                      className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent-text sm:ms-auto"
                    >
                      {dosingOpen ? "Hide details" : "Details"}
                      <ChevronDown className={`size-4 transition-transform duration-200 ${dosingOpen ? "rotate-180" : ""}`} />
                    </button>
                  </div>

                  {/* Bullet chart: bar = sets the plan gives, tick = research
                      suggestion. Light accent for bars (the fill accent is too
                      dark to read as a mark); below target uses the warning
                      colour with an icon. Values stay in text colours. */}
                  <ul className={`${chartOpen ? "grid" : "hidden sm:grid"} gap-x-8 gap-y-2.5 px-4 pb-3.5 pt-3.5 sm:grid-cols-2`}>
                    {dosing.map(({ group, delivered, target }) => {
                      const short = target !== undefined && delivered < target;
                      const pct = (n: number) => `${(n / dosingMax) * 100}%`;
                      return (
                        <li
                          key={group}
                          title={`${capitalize(group)}: plan gives ${delivered} sets/wk${
                            target !== undefined ? `, research suggests ${target}` : ""
                          }`}
                          className="grid grid-cols-[6.5rem_minmax(0,1fr)_3.5rem] items-center gap-3"
                        >
                          <span className="truncate text-xs text-fg-muted">{capitalize(group)}</span>
                          <span className="relative h-2 rounded-full bg-surface-3">
                            <span
                              className={`absolute inset-y-0 start-0 rounded-full ${short ? "bg-warn" : "bg-accent-text"}`}
                              style={{ width: pct(delivered) }}
                            />
                            {target !== undefined && (
                              <span
                                aria-hidden="true"
                                className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-full bg-fg-muted ring-2 ring-surface-2"
                                style={{ insetInlineStart: pct(target) }}
                              />
                            )}
                          </span>
                          <span className={`inline-flex items-center justify-end gap-1 text-xs tabular-nums ${short ? "text-warn" : "text-fg"}`}>
                            {short && <Alert className="size-3" />}
                            {delivered}
                            {target !== undefined && <span className="text-fg-subtle">/{target}</span>}
                            {short && <span className="sr-only"> (below the suggestion)</span>}
                          </span>
                        </li>
                      );
                    })}
                  </ul>

                  {dosingOpen && (
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
                    {(sharedFrequency || sharedVolume || sharedTrained !== null) && (
                      <div className="border-b border-line">
                        <div className="grid divide-y divide-line sm:auto-cols-fr sm:grid-flow-col sm:divide-x sm:divide-y-0">
                          {sharedFrequency && (
                            <Fact label="Research frequency">
                              {sharedFrequency.frequency}x/wk
                              <SourcesBadge
                                what="frequency"
                                citations={sharedFrequency.supporting_citations}
                                note={sharedFrequency.grounding_note}
                                open={openSources === `freq-${sharedFrequency.id}`}
                                onToggle={() => toggleSources(`freq-${sharedFrequency.id}`)}
                              />
                            </Fact>
                          )}
                          {sharedVolume && (
                            <Fact label="Suggested sets per muscle">
                              <span>
                                {sharedVolume.weekly_sets}
                                <span className="text-xs font-normal text-fg-subtle">/wk</span>
                              </span>
                              <SourcesBadge
                                what="weekly sets"
                                citations={sharedVolume.supporting_citations}
                                note={sharedVolume.grounding_note}
                                open={openSources === `volume-${sharedVolume.id}`}
                                onToggle={() => toggleSources(`volume-${sharedVolume.id}`)}
                              />
                            </Fact>
                          )}
                          {sharedTrained !== null && (
                            <Fact label="You train each muscle">
                              <span>
                                {sharedTrained}x<span className="text-xs font-normal text-fg-subtle">/wk</span>
                              </span>
                            </Fact>
                          )}
                        </div>
                        {sharedFrequency && openSources === `freq-${sharedFrequency.id}` && (
                          <div className="px-4 pb-3">
                            <SourcesPanel
                              heading={`Why research suggests ${sharedFrequency.frequency}x/week per muscle`}
                              citations={sharedFrequency.supporting_citations}
                              note={sharedFrequency.grounding_note}
                              question={`Why train each muscle ${sharedFrequency.frequency}x a week for ${program.goal}?`}
                              onClose={() => setOpenSources(null)}
                            />
                          </div>
                        )}
                        {sharedVolume && openSources === `volume-${sharedVolume.id}` && (
                          <div className="px-4 pb-3">
                            <SourcesPanel
                              heading={`Why research suggests ${sharedVolume.weekly_sets} weekly sets per muscle`}
                              citations={sharedVolume.supporting_citations}
                              note={sharedVolume.grounding_note}
                              question={`Why ${sharedVolume.weekly_sets} weekly sets per muscle in a ${program.goal} program?`}
                              onClose={() => setOpenSources(null)}
                            />
                          </div>
                        )}
                      </div>
                    )}
                    {/* Two columns of muscles on wider screens so the expanded
                        view stays short; each reads top to bottom, and a row's
                        sources open right under it in its own column. */}
                    <div className="grid sm:grid-cols-2">
                      {[muscleGroups.slice(0, Math.ceil(muscleGroups.length / 2)), muscleGroups.slice(Math.ceil(muscleGroups.length / 2))].map(
                        (column, columnIndex) => (
                          <div key={columnIndex} className={columnIndex === 1 ? "sm:border-s sm:border-line" : undefined}>
                            <div
                              className={`items-center gap-3 py-2 ps-4 pe-2 text-[11px] font-medium text-fg-subtle ${
                                columnIndex === 1 ? "hidden sm:flex" : "flex"
                              }`}
                            >
                              <span className="w-24 shrink-0">Muscle</span>
                              {sharedTrained === null && <span className="w-12 text-end">Trained</span>}
                              {strength && !sharedFrequency && <span className="w-[4.5rem] text-end">Research</span>}
                              {!sharedVolume && <span className="w-14 text-end">Sets/wk</span>}
                              {!strength && <span className="w-16 text-end">Per session</span>}
                              <span className="min-w-0 flex-1">{strength && "Progression"}</span>
                              <span className="w-8 shrink-0" />
                            </div>
                            {column.map((group) => {
                              const frequency = mesocycle.muscle_group_frequencies.find((f) => f.muscle_group === group);
                              const volume = mesocycle.muscle_group_volumes.find((v) => v.muscle_group === group);
                              const scheme = mesocycle.progression_schemes.find((p) => p.muscle_group === group);
                              const freqKey = `freq-${frequency?.id}`;
                              const volumeKey = `volume-${volume?.id}`;
                              const schemeKey = `scheme-${scheme?.id}`;
                              const delivered = deliveredSets(mesocycle, group);
                              const trainedDays = daysTraining(mesocycle, group);
                              const rowBusy = [
                                `volume-${mesocycle.id}-${group}`,
                                `frequency-${mesocycle.id}-${group}`,
                                `progression-${mesocycle.id}-${group}`,
                              ].includes(busyKey ?? "");
                              const panel =
                                !sharedVolume && volume && openSources === volumeKey ? (
                                  <SourcesPanel
                                    heading={`Why research suggests ${volume.weekly_sets} weekly sets for ${group}`}
                                    citations={volume.supporting_citations}
                                    note={volume.grounding_note}
                                    // Muscle-generic: weekly volume and frequency are one shared
                                    // answer for every muscle, so naming the muscle wrote (and paid
                                    // for) 14 copies of the same summary.
                                    question={`Why ${volume.weekly_sets} weekly sets per muscle in a ${program.goal} program?`}
                                    onClose={() => setOpenSources(null)}
                                  />
                                ) : strength && !sharedFrequency && frequency && openSources === freqKey ? (
                                  <SourcesPanel
                                    heading={`Why research suggests ${frequency.frequency}x/week for ${group}`}
                                    citations={frequency.supporting_citations}
                                    note={frequency.grounding_note}
                                    question={`Why train each muscle ${frequency.frequency}x a week for ${program.goal}?`}
                                    onClose={() => setOpenSources(null)}
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
                                    question={
                                      scheme.scheme === "constant"
                                        ? undefined
                                        : `Why ${schemeLabel(scheme.scheme)} progression for ${program.goal}?`
                                    }
                                    onClose={() => setOpenSources(null)}
                                  />
                                ) : null;
                              return (
                                <div key={group} className="border-t border-line">
                                  <div className="flex items-center gap-3 py-1 ps-4 pe-2 text-[13px]">
                                    <span className="flex w-24 shrink-0 items-center gap-1.5 font-medium">
                                      <span className="truncate">{capitalize(group)}</span>
                                      {rowBusy && <Spinner className="size-3 shrink-0 text-accent-text" />}
                                    </span>
                                    {sharedTrained === null && (
                                      <span className="w-12 text-end tabular-nums text-fg-muted">{trainedDays}x/wk</span>
                                    )}
                                    {strength && !sharedFrequency && (
                                      <span className="inline-flex w-[4.5rem] items-center justify-end gap-1.5 tabular-nums">
                                        {frequency ? (
                                          <>
                                            {frequency.frequency}x/wk
                                            <SourcesBadge
                                              what={`${group} frequency`}
                                              citations={frequency.supporting_citations}
                                              note={frequency.grounding_note}
                                              open={openSources === freqKey}
                                              onToggle={() => toggleSources(freqKey)}
                                            />
                                          </>
                                        ) : (
                                          <span className="text-fg-subtle">—</span>
                                        )}
                                      </span>
                                    )}
                                    {!sharedVolume && (
                                      <span className="inline-flex w-14 items-center justify-end gap-1.5 tabular-nums">
                                        {volume ? (
                                          <>
                                            {volume.weekly_sets}
                                            <SourcesBadge
                                              what={`${group} weekly sets`}
                                              citations={volume.supporting_citations}
                                              note={volume.grounding_note}
                                              open={openSources === volumeKey}
                                              onToggle={() => toggleSources(volumeKey)}
                                            />
                                          </>
                                        ) : (
                                          <span className="text-fg-subtle">—</span>
                                        )}
                                      </span>
                                    )}
                                    {!strength && (
                                      <span className="w-16 text-end tabular-nums text-fg-muted">
                                        {trainedDays > 0 ? `~${Math.round(delivered / trainedDays)}` : "—"}
                                      </span>
                                    )}
                                    <span className="min-w-0 flex-1">
                                      {strength &&
                                        (scheme ? (
                                          <span className="inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                                            {scheme.scheme === "constant" ? (
                                              <span>
                                                None <span className="text-xs text-fg-muted">· accessories only</span>
                                              </span>
                                            ) : (
                                              <span className="capitalize">{schemeLabel(scheme.scheme)}</span>
                                            )}
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
                                        ))}
                                    </span>
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
                                  </div>
                                  {panel && <div className="px-4 pb-3">{panel}</div>}
                                </div>
                              );
                            })}
                          </div>
                        ),
                      )}
                    </div>
                  </div>
                  )}
                </section>
              )}

              {pickWeek && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <span className="text-[13px] font-medium text-fg-muted">Week</span>
                  <div className="min-w-0 flex-1 sm:max-w-md">
                    <Segmented
                      label="Week shown"
                      options={[
                        ...(weeksDiffer ? [] : [{ value: "every", label: "Every" }]),
                        ...weeks.map((w) => ({ value: String(w), label: String(w) })),
                        ...(weeksDiffer ? [{ value: "all", label: "All" }] : []),
                      ]}
                      value={String(week)}
                      onChange={(v) =>
                        setWeekByBlock((current) => ({
                          ...current,
                          [mesocycle.id]: v === "all" || v === "every" ? v : Number(v),
                        }))
                      }
                    />
                  </div>
                  {!strength && typeof week === "number" && (
                    <p className="basis-full text-xs text-fg-subtle">
                      Changes made here apply to week {week} only.
                    </p>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-2.5">
                {mesocycle.day_templates.map((day, dayIndex) => {
                  const open = openDays.has(day.id);
                  const dayBusy = busyKey === `delete-day-${day.id}`;
                  return (
                    <div
                      key={day.id}
                      // Arrow and badge turn purple: on the open day, and on hover
                      // anywhere over a closed one. The outline stays neutral.
                      className={`group/day rounded-xl border transition-colors duration-150 ${
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
                          {/* Purple marks the open day, and previews it on hover. */}
                          <ChevronRight
                            className={`size-4 shrink-0 transition-[rotate,color] duration-200 ${
                              open ? "rotate-90 text-accent-text" : "text-fg-subtle group-hover/day:text-accent-text"
                            }`}
                          />
                          <span
                            className={`grid size-8 shrink-0 place-items-center rounded-lg font-mono text-xs font-medium transition-colors duration-150 ${
                              open
                                ? "bg-accent-soft text-accent-text"
                                : "bg-surface-3 text-fg-muted group-hover/day:bg-accent-soft group-hover/day:text-accent-text"
                            }`}
                          >
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
                                trained={program.trained}
                                week={week}
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

type ValueCell = {
  field: string;
  value: string;
  unit: string;
  // The same value the week before, when it changed (single-week view).
  before: string | undefined;
  citations: SupportingCitation[];
  note: string | null;
  heading: string;
  // What the panel's combined summary answers (see SourcesPanel).
  question: string;
};

function ExerciseBlock({
  slot,
  mesocycle,
  strength,
  trained,
  week,
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
  trained: boolean;
  week: Week;
  busy: boolean;
  busyKey: string | null;
  anchoredFieldId: number | null;
  openSources: string | null;
  toggleSources: (key: string) => void;
  splitRule: RuleJustification | null;
  onAskAbout: (prescription: WeeklyPrescription, label: string, thisWeekOnly: boolean) => void;
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
  const allRows = rowsToShow(slot, strength);
  // "All" lists every week as a table; otherwise (one week picked, or an
  // exercise that's the same every week) it's one line under the name.
  const table = week === "all" && allRows.length > 1;
  // A picked week of an exercise that's the same every week is still that
  // week's own prescription, so changes made from it stay on that week.
  const pickedWeek =
    typeof week === "number" && allRows.length === 1 && allRows[0].everyWeek
      ? slot.weekly_prescriptions.find((wp) => wp.week_number === week)
      : undefined;
  const single = pickedWeek
    ? { wp: pickedWeek, everyWeek: false }
    : (allRows.find((r) => r.wp.week_number === week) ?? allRows[0]);
  const showLoad = strength || slot.weekly_prescriptions.some((wp) => wp.load);
  const goal = strength ? "strength" : "hypertrophy";
  // Sets / reps / (load) / effort - the same widths in both views, so values
  // line up down a day.
  const valueColumns = `minmax(0,0.8fr) minmax(0,1fr) ${showLoad ? "minmax(0,1.35fr) " : ""}minmax(0,1.1fr)`;
  // Split sets carry no per-exercise citations; their evidence is the
  // muscle's cited weekly volume.
  const muscleVolume = mesocycle.muscle_group_volumes.find((v) => v.muscle_group === slot.muscle_group);
  const scheme = mesocycle.progression_schemes.find((p) => p.muscle_group === slot.muscle_group)?.scheme;

  const labelOf = (wp: WeeklyPrescription, everyWeek: boolean) =>
    everyWeek ? slot.exercise_name : `${slot.exercise_name}, week ${wp.week_number}`;

  // Each value with its own sources: sets (a share of the muscle's cited
  // weekly volume), reps, load (%1RM) and effort (RIR).
  function valuesOf(wp: WeeklyPrescription, previous?: WeeklyPrescription): ValueCell[] {
    const ownSetsCitations = wp.sets_citations.length > 0;
    const setsCitations = ownSetsCitations ? wp.sets_citations : (muscleVolume?.supporting_citations ?? []);
    const why = (value: string, what: string) => `Why ${value} ${what} for a ${goal} program?`;
    const linearPhase = (p: WeeklyPrescription) =>
      strength && scheme === "linear" && (p.reps_grounding_note ?? "").startsWith("Phase ");
    const changed = (now: string | number, before: string | number | undefined) =>
      previous && change(before, now) ? String(before) : undefined;
    return [
      {
        field: "sets",
        value: wp.sets > 0 ? String(wp.sets) : "—",
        unit: wp.sets === 1 ? "set" : "sets",
        before: changed(wp.sets, previous?.sets),
        citations: setsCitations,
        note: wp.sets_grounding_note,
        heading: `Why ${wp.sets} sets`,
        // Split sets are cited by the muscle's weekly volume, so the
        // question is about that weekly total - worded like the weekly
        // volume panel's, so both share one stored summary.
        question:
          !ownSetsCitations && muscleVolume
            ? `Why ${muscleVolume.weekly_sets} weekly sets per muscle in a ${goal} program?`
            : why(String(wp.sets), "sets"),
      },
      {
        field: "reps",
        value: wp.reps || "—",
        unit: "reps",
        before: changed(wp.reps, previous?.reps),
        citations: wp.reps_citations,
        note: wp.reps_grounding_note,
        heading: `Why ${wp.reps} reps`,
        // A linear phase's reps say which phase and for whom: asked as a
        // bare "Why 8 reps for a strength program?", the summary argued from
        // the trained-lifter finding (undulating beats linear) on a plan the
        // app gives newer lifters, for whom the models didn't differ.
        question: linearPhase(wp)
          ? `Why ${wp.reps} reps in this phase of linear progression, for a ${trained ? "trained lifter" : "lifter newer to training"} with a strength goal?`
          : why(wp.reps, "reps"),
      },
      ...(showLoad
        ? [
            {
              field: "load",
              value: wp.load || "—",
              unit: "",
              before: changed(wp.load, previous?.load),
              citations: wp.load_citations,
              note: wp.load_grounding_note,
              heading: `Why ${wp.load}`,
              question: why(wp.load, "load"),
            },
          ]
        : []),
      {
        field: "rir",
        value: wp.rir || "—",
        unit: "",
        before: changed(wp.rir, previous?.rir),
        citations: wp.rir_citations,
        note: wp.rir_grounding_note,
        heading: `Why ${wp.rir}`,
        question: why(wp.rir, "effort (RIR)"),
      },
    ];
  }

  function regenerateItems(wp: WeeklyPrescription, everyWeek: boolean, suffix = "") {
    return [
      // Regenerating one week's sets only makes sense when weeks differ.
      ...(!everyWeek
        ? [{ label: `Regenerate sets${suffix}`, icon: <Refresh className="size-4" />, onSelect: () => onGeneratePrescription(wp, "volume") }]
        : []),
      ...(strength
        ? [{ label: `Regenerate load${suffix}`, icon: <Refresh className="size-4" />, onSelect: () => onGeneratePrescription(wp, "intensity") }]
        : []),
    ];
  }

  function cells(wp: WeeklyPrescription, values: ValueCell[]) {
    if (isPlaceholder(wp)) {
      return (
        <span className="col-span-2 text-sm italic text-fg-subtle sm:[grid-column:span_var(--span)]">
          Not generated yet
        </span>
      );
    }
    return values.map((v) => {
      const move = v.before !== undefined ? change(v.before, v.value) : null;
      return (
        <span key={v.field} className="flex min-w-0 items-center gap-1.5 whitespace-nowrap">
          <span className="text-sm font-medium tabular-nums text-fg">
            {v.value}
            {v.unit && v.value !== "—" && <span className="ms-1 text-xs font-normal text-fg-subtle">{v.unit}</span>}
          </span>
          {move && (
            <span
              className="text-xs font-semibold text-accent-text"
              title={`Week ${wp.week_number - 1}: ${v.before}`}
              aria-label={`${move === "up" ? "up" : "down"} from ${v.before} the week before`}
            >
              {move === "up" ? "↑" : "↓"}
            </span>
          )}
          <SourcesBadge
            what={v.field === "rir" ? "effort" : v.field}
            citations={v.citations}
            note={v.note}
            open={openSources === `wp-${wp.id}-${v.field}`}
            onToggle={() => toggleSources(`wp-${wp.id}-${v.field}`)}
          />
        </span>
      );
    });
  }

  function details(wp: WeeklyPrescription, values: ValueCell[]) {
    const open = values.find((v) => openSources === `wp-${wp.id}-${v.field}`);
    return (
      <>
        {wp.load_fit_note && !isPlaceholder(wp) && (
          <CaveatNote className="px-2 pb-2 text-xs">{wp.load_fit_note}</CaveatNote>
        )}
        {open && (
          <div className="px-2 pb-2">
            <SourcesPanel
              heading={open.heading}
              citations={open.citations}
              note={open.note}
              question={open.question}
              onClose={() => toggleSources(`wp-${wp.id}-${open.field}`)}
              rule={
                open.field === "sets" && splitRule && wp.sets_grounding_note?.startsWith("Share of")
                  ? { heading: "Why the sets are spread evenly across sessions", justification: splitRule }
                  : null
              }
            />
          </div>
        )}
      </>
    );
  }

  // thisWeekOnly: asked from one week of a hypertrophy exercise, so a change
  // stays on that week instead of applying to every week.
  function askButton(wp: WeeklyPrescription, label: string, thisWeekOnly: boolean) {
    const isAnchored = anchoredFieldId === wp.id;
    return (
      <button
        type="button"
        onClick={() => onAskAbout(wp, label, thisWeekOnly)}
        aria-pressed={isAnchored}
        aria-label={`Ask about or adjust ${label}`}
        title="Ask about or adjust this in the chat"
        className={`btn btn-sm h-7 gap-1.5 px-2 ${isAnchored ? "bg-accent text-accent-fg" : "btn-ghost text-accent-text"}`}
      >
        <Message className="size-3.5" />
        <span className="hidden sm:inline">{isAnchored ? "Asking" : "Ask"}</span>
      </button>
    );
  }

  const rowWorking = (wp: WeeklyPrescription) => busyKey === `volume-${wp.id}` || busyKey === `intensity-${wp.id}`;
  const singleLabel = single ? labelOf(single.wp, single.everyWeek) : slot.exercise_name;

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
        <span className="flex shrink-0 items-center gap-0.5">
          {!table && single && rowWorking(single.wp) && <Spinner className="me-1 size-3.5 text-accent-text" />}
          {!table && single && askButton(single.wp, singleLabel, !single.everyWeek)}
          <Menu
            label={`Actions for ${slot.exercise_name}`}
            disabled={busy}
            items={[
              { label: "Generate reps & effort", icon: <Zap className="size-4" />, onSelect: onGenerate },
              ...(!table && single
                ? regenerateItems(single.wp, single.everyWeek, single.everyWeek ? "" : ` (week ${single.wp.week_number})`)
                : []),
              { label: "Swap exercise", icon: <Swap className="size-4" />, onSelect: onSwap },
              { label: "Delete exercise", icon: <Trash className="size-4" />, danger: true, onSelect: onDelete },
            ]}
          />
        </span>
      </div>

      {!table && single && (() => {
        const previous =
          allRows.length > 1
            ? slot.weekly_prescriptions.find((wp) => wp.week_number === single.wp.week_number - 1)
            : undefined;
        const values = valuesOf(single.wp, previous);
        return (
          <div
            className={`rounded-lg transition-colors duration-150 ${
              anchoredFieldId === single.wp.id ? "bg-accent-soft ring-1 ring-accent-ring/70" : ""
            }`}
          >
            <div
              className="grid grid-cols-2 items-center gap-x-3 gap-y-1 px-2 py-1.5 sm:grid-cols-[var(--cols)]"
              style={{ "--cols": valueColumns, "--span": values.length } as React.CSSProperties}
            >
              {cells(single.wp, values)}
            </div>
            {details(single.wp, values)}
          </div>
        );
      })()}

      {table && (
        <ul className="flex flex-col gap-0.5">
          {allRows.map(({ wp, everyWeek }) => {
            const label = labelOf(wp, everyWeek);
            const values = valuesOf(wp);
            const regenerate = regenerateItems(wp, everyWeek);
            return (
              <li
                key={wp.id}
                className={`rounded-lg transition-colors duration-150 ${
                  anchoredFieldId === wp.id ? "bg-accent-soft ring-1 ring-accent-ring/70" : "hover:bg-surface-3/40"
                }`}
              >
                {/* Narrow: week label and actions on a slim top line, values
                    in a 2x2 grid below. From sm up the values wrapper
                    dissolves (display: contents) so each value takes its own
                    column of the shared template and the row is one line. */}
                <div
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-2 py-2 sm:grid-cols-[var(--cols)] sm:gap-y-0 sm:py-1.5"
                  style={{ "--cols": `4.25rem ${valueColumns} auto`, "--span": values.length } as React.CSSProperties}
                >
                  <span className="font-mono text-xs text-fg-subtle">Wk {wp.week_number}</span>
                  <div className="col-span-2 grid grid-cols-2 gap-x-3 gap-y-1 sm:contents">{cells(wp, values)}</div>
                  <span className="col-start-2 row-start-1 flex items-center justify-end gap-0.5 sm:col-start-auto sm:row-start-auto">
                    {rowWorking(wp) && <Spinner className="me-1 size-3.5 text-accent-text" />}
                    {askButton(wp, label, true)}
                    {regenerate.length > 0 && <Menu label={`More for ${label}`} disabled={busy} items={regenerate} quiet />}
                  </span>
                </div>
                {details(wp, values)}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
