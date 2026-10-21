"use client";

import { useEffect, useRef, useState } from "react";
import { runBlockGeneration } from "./blockGeneration";
import GenerationProgress from "./GenerationProgress";
import { Book, ChevronRight, Close, Sparkles } from "./Icons";
import { RuleSources } from "./RuleSources";
import {
  VOLUME_LABELS,
  volumeLabel,
  type Program,
  type ProgramSummary,
  type VolumePreference,
} from "./types";
import { Field, Notice, Segmented, Switch } from "./ui";
import { useApi } from "./useApi";

type SplitOption = { key: string; label: string; allowed_days: number[]; day_types: string[] };

// A fixed list rather than free text: goal feeds every retrieval query, the
// corpus is organized around these two goals, and progression generation is
// gated on goal === "strength" exactly.
type Goal = "hypertrophy" | "strength";
const GOALS: { value: Goal; label: string }[] = [
  { value: "hypertrophy", label: "Hypertrophy" },
  { value: "strength", label: "Strength" },
];

// Each muscle sits in one of a split's day types, so training days divided
// by day types is how many times a week each muscle is trained.
function perMuscle(split: SplitOption, days: number) {
  return days / split.day_types.length;
}

function frequencyLabel(split: SplitOption, days: number) {
  return `${perMuscle(split, days)}x per muscle · ${days} days/week`;
}

// The split's day count closest to a per-muscle frequency (default 2x).
function daysForFrequency(split: SplitOption, frequency: number) {
  return split.allowed_days.reduce((best, d) =>
    Math.abs(perMuscle(split, d) - frequency) < Math.abs(perMuscle(split, best) - frequency) ? d : best,
  );
}

type Rule = { label: string; text: string; ruleKeys: [string] | [string, string]; secondHeading?: string };

// The cited rules behind the numbers this program will get, for the
// chosen goal (and, for strength, training status).
function rulesFor(goal: Goal, trained: boolean): Rule[] {
  if (goal === "hypertrophy") {
    return [
      {
        label: "Volume",
        text: "Pelland et al. 2025's efficiency tiers (5-10 sets higher efficiency, 11-18 intermediate).",
        ruleKeys: ["volume_efficiency_tiers"],
      },
      {
        label: "Frequency",
        text:
          "With weekly sets matched, studies show no significant growth difference between training a muscle 2x " +
          "and 3x a week. More sessions still help at higher volumes, since gains within one session diminish past ~11 sets.",
        ruleKeys: ["frequency_matched_volume", "per_session_diminishing_returns"],
        secondHeading: "Why more sessions help at higher volume",
      },
    ];
  }
  return [
    {
      label: "Volume",
      text:
        "Pelland et al. 2025's strength efficiency tiers (1 set minimum effective dose, 2 higher efficiency, 3-4 " +
        "intermediate; more doesn't consistently add strength).",
      ruleKeys: ["strength_volume_efficiency_tiers"],
    },
    {
      label: "Loads",
      text:
        "Estimated from each exercise's reps and RIR using Nuzzo et al. 2024's table of reps to failure at each " +
        "%1RM, so they fit together. People differ by about 2.5 reps at 80% 1RM, so treat the % as a starting " +
        "weight and adjust it until sets end at the prescribed RIR.",
      ruleKeys: ["reps_at_percent_1rm"],
    },
    {
      label: "Frequency",
      text: "Strength gains rise with how often a lift is trained, with diminishing returns at higher frequencies.",
      ruleKeys: ["strength_frequency"],
    },
    ...(trained
      ? [
          {
            label: "Progression: daily undulating",
            text:
              "Each compound lift's sessions in the week rotate 8, 6 and 4 reps, heaviest last (Rhea et al. 2002's " +
              "protocol), with each day's load set from its reps and RIR; the weight rises as you get stronger. " +
              "Undulating periodization has produced larger 1RM gains than linear in trained lifters.",
            ruleKeys: ["periodization_by_training_status", "daily_undulating_protocol"] as [string, string],
            secondHeading: "The protocol the program follows",
          },
          {
            label: "Why daily, not weekly",
            text: "Undulating week to week hasn't beaten linear progression in trials.",
            ruleKeys: ["weekly_undulation_not_better"] as [string],
          },
          {
            label: "Session order",
            text:
              "The heaviest session comes last, not straight after the highest-volume one, and the exact rep " +
              "numbers matter less than the volume - Rhea's 8/6/4 is one tested option.",
            ruleKeys: ["dup_session_order", "dup_rep_scheme"] as [string, string],
            secondHeading: "Why the exact reps matter less",
          },
        ]
      : [
          {
            label: "Progression: linear",
            text:
              "Compound lifts move through phases of 8, then 6, then 4 reps across the block (the linear arms of " +
              "Rhea et al. 2002 and Buford et al. 2007), each week's load set from its reps and RIR. Undulating " +
              "periodization's advantage over linear has been seen in trained lifters, not untrained.",
            ruleKeys: ["periodization_by_training_status", "linear_periodization_protocol"] as [string, string],
            secondHeading: "The protocol the program follows",
          },
        ]),
    {
      label: "Accessories",
      text:
        "Single-joint exercises stay at 8-12 reps every week, as in the strength trials, which periodized only the main lifts.",
      ruleKeys: ["strength_accessory_reps"],
    },
    {
      label: "Deload",
      text:
        "Off by default: in trained lifters, a week off partway through a 9-week program had minimal impact on muscle " +
        "growth, and lower-body strength gains were modestly smaller than with continuous training. The deload's size " +
        "here (60% of peak load) is common practice.",
      ruleKeys: ["deload_week"],
    },
  ];
}

// Generates a whole program from a few choices: the structure (days, rest
// spacing, AI-picked exercises) in one request, then every number through
// the same per-exercise generation + citation verification as the builder.
// "Start empty" creates a blank program with the chosen goal instead.
export default function ProgramWizard({
  onCreated,
  onRefresh,
  onRunningChange,
  onClose,
}: {
  onCreated: (program: ProgramSummary) => void;
  onRefresh: () => void;
  onRunningChange: (running: boolean) => void;
  // Shown when there are programs to go back to.
  onClose?: () => void;
}) {
  const api = useApi();
  const [splits, setSplits] = useState<SplitOption[]>([]);
  const [goal, setGoal] = useState<Goal>("hypertrophy");
  const [splitKey, setSplitKey] = useState("");
  const [days, setDays] = useState(0);
  const [weeks, setWeeks] = useState("6");
  const [volume, setVolume] = useState<VolumePreference>("moderate");
  const [trained, setTrained] = useState(false);
  const [includeDeload, setIncludeDeload] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [creatingEmpty, setCreatingEmpty] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    let stale = false;
    (async () => {
      try {
        const list = await api<SplitOption[]>("/splits/");
        if (stale) return;
        setSplits(list);
        setSplitKey(list[0]?.key ?? "");
        setDays(list[0] ? daysForFrequency(list[0], 2) : 0);
      } catch (err) {
        if (!stale) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    return () => {
      stale = true;
    };
  }, [api]);

  const split = splits.find((s) => s.key === splitKey);

  function chooseSplit(key: string) {
    setSplitKey(key);
    const next = splits.find((s) => s.key === key);
    // Keep the per-muscle frequency across splits (as close as the new one allows).
    if (next) setDays(daysForFrequency(next, split ? perMuscle(split, days) : 2));
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    cancelled.current = false;
    onRunningChange(true);
    try {
      setProgress("Choosing exercises for each day");
      const program = await api<Program>("/programs/generate", {
        method: "POST",
        body: {
          goal,
          split: splitKey,
          days_per_week: days,
          weeks: Number(weeks),
          volume_preference: volume,
          trained,
          include_deload: goal === "strength" && includeDeload,
        },
      });
      onCreated({ id: program.id, goal: program.goal });

      const { failures, cancelled: stopped } = await runBlockGeneration(api, program.id, program.mesocycles[0].id, {
        onProgress: setProgress,
        onStepDone: onRefresh,
        isCancelled: () => cancelled.current,
      });
      setNotice(stopped ? `Stopped - program #${program.id} is partly generated.` : `Program #${program.id} is ready.`);
      if (failures.length > 0) setError(`${failures.length} step(s) failed:\n${failures.join("\n")}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setProgress(null);
      onRunningChange(false);
      onRefresh();
    }
  }

  async function handleCreateEmpty() {
    setError(null);
    setNotice(null);
    setCreatingEmpty(true);
    try {
      onCreated(await api<ProgramSummary>("/programs/", { method: "POST", body: { goal } }));
      onClose?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreatingEmpty(false);
    }
  }

  const running = progress !== null;
  const rules = rulesFor(goal, trained);

  return (
    <form onSubmit={handleGenerate} className="card animate-in flex flex-col">
      <div className="flex items-start gap-3.5 px-5 pt-5 sm:px-6 sm:pt-6">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-2 text-white shadow-[0_8px_20px_-8px_var(--accent-ring)]">
          <Sparkles className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold tracking-tight">Generate a program</h2>
          <p className="mt-0.5 text-sm text-fg-muted">
            Exercises are picked by AI. Every sets, reps, load, frequency and progression number is research-cited.
          </p>
        </div>
        {onClose && !running && (
          <button type="button" onClick={onClose} className="icon-btn -me-1.5 -mt-1" aria-label="Close the generator">
            <Close className="size-4" />
          </button>
        )}
      </div>

      <fieldset disabled={running} className="grid grid-cols-1 gap-4 px-5 pt-5 sm:grid-cols-6 sm:px-6">
        <div className="flex flex-col gap-1.5 sm:col-span-6">
          <span className="text-[13px] font-medium text-fg-muted">Goal</span>
          <Segmented label="Goal" options={GOALS} value={goal} onChange={setGoal} disabled={running} />
        </div>
        <Field className="sm:col-span-3" label="Split" hint={split ? `Rotates ${split.day_types.join(" / ")}` : undefined}>
          <select value={splitKey} onChange={(e) => chooseSplit(e.target.value)} className="input">
            {splits.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </Field>
        {/* Frequency per muscle and days per week map one-to-one within a
            split (each muscle sits in one day type), so picking a frequency
            picks the days. */}
        <Field className="sm:col-span-3" label="Frequency" hint="How often each muscle is trained per week">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="input">
            {(split?.allowed_days ?? []).map((d) => (
              <option key={d} value={d}>
                {frequencyLabel(split!, d)}
              </option>
            ))}
          </select>
        </Field>
        <Field className="sm:col-span-4" label="Weekly volume" hint="Weekly sets per muscle; secondary work counts as half">
          <select value={volume} onChange={(e) => setVolume(e.target.value as VolumePreference)} className="input">
            {(Object.keys(VOLUME_LABELS) as VolumePreference[]).map((v) => (
              <option key={v} value={v}>
                {volumeLabel(v, goal)}
              </option>
            ))}
          </select>
        </Field>
        <Field className="sm:col-span-2" label="Length">
          <span className="relative block">
            <input
              type="number"
              min={2}
              max={12}
              value={weeks}
              onChange={(e) => setWeeks(e.target.value)}
              className="input pe-16 tabular-nums"
              required
            />
            <span className="pointer-events-none absolute inset-y-0 end-3 flex items-center text-sm text-fg-subtle">
              weeks
            </span>
          </span>
        </Field>

        {goal === "strength" && (
          <div className="animate-in flex flex-col gap-4 rounded-xl border border-line bg-surface-2/50 p-4 sm:col-span-6">
            <Switch
              checked={trained}
              onChange={setTrained}
              disabled={running}
              label="I've lifted consistently for 1+ year"
              description={trained ? "Daily undulating progression (8/6/4 reps across the week)." : "Linear progression (phases of 8, 6, then 4 reps)."}
            />
            <div className="h-px bg-line" />
            <Switch
              checked={includeDeload}
              onChange={setIncludeDeload}
              disabled={running}
              label="Include a deload week"
              description="A lighter final week. Off by default - see Deload below."
            />
          </div>
        )}
      </fieldset>

      <details className="group mx-5 mt-5 rounded-xl border border-line sm:mx-6">
        <summary className="flex cursor-pointer items-center gap-2.5 px-4 py-3 text-sm select-none">
          <Book className="size-4 text-evidence" />
          <span className="flex-1 font-medium">How this program is built</span>
          <span className="chip">{rules.length} cited rules</span>
          <ChevronRight className="size-4 text-fg-subtle transition-transform duration-200 group-open:rotate-90" />
        </summary>
        <ul className="animate-in flex flex-col gap-3.5 border-t border-line px-4 py-4">
          {rules.map((rule) => (
            <li key={rule.label}>
              <RuleSources label={rule.label} text={rule.text} ruleKeys={rule.ruleKeys} secondHeading={rule.secondHeading} />
            </li>
          ))}
        </ul>
      </details>

      <div className="flex flex-col gap-3 px-5 pb-5 pt-5 sm:px-6 sm:pb-6">
        {running ? (
          <GenerationProgress
            progress={progress}
            strength={goal === "strength"}
            includeExercises
            onCancel={() => (cancelled.current = true)}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button type="submit" disabled={!split} className="btn btn-primary h-10 px-5">
              <Sparkles className="size-4" />
              Generate program
            </button>
            <button type="button" onClick={handleCreateEmpty} disabled={creatingEmpty} className="btn btn-ghost h-10">
              {creatingEmpty ? "Creating..." : "Start an empty one instead"}
            </button>
          </div>
        )}
        {notice && <Notice tone="success">{notice}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}
      </div>
    </form>
  );
}
