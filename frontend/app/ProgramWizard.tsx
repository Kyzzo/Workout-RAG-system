"use client";

import { useEffect, useRef, useState } from "react";
import { runBlockGeneration } from "./blockGeneration";
import { VOLUME_LABELS, volumeLabel, type Program, type ProgramSummary, type VolumePreference } from "./types";
import { useApi } from "./useApi";

type SplitOption = { key: string; label: string; allowed_days: number[]; day_types: string[] };

const GOALS = ["hypertrophy", "strength"];
const selectClass = "border rounded px-3 py-2 bg-white dark:bg-zinc-900";

// Generates a whole program from four choices: the structure (days, rest
// spacing, AI-picked exercises) in one request, then every number through
// the same per-exercise generation + citation verification as the builder.
export default function ProgramWizard({
  onCreated,
  onRefresh,
  onRunningChange,
}: {
  onCreated: (program: ProgramSummary) => void;
  onRefresh: () => void;
  onRunningChange: (running: boolean) => void;
}) {
  const api = useApi();
  const [splits, setSplits] = useState<SplitOption[]>([]);
  const [goal, setGoal] = useState(GOALS[0]);
  const [splitKey, setSplitKey] = useState("");
  const [days, setDays] = useState(0);
  const [weeks, setWeeks] = useState("6");
  const [volume, setVolume] = useState<VolumePreference>("moderate");
  const [progress, setProgress] = useState<string | null>(null);
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
        setDays(list[0]?.allowed_days[0] ?? 0);
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
    // Keep the day count if the new split supports it, else its first option.
    if (next && !next.allowed_days.includes(days)) setDays(next.allowed_days[0]);
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
        body: { goal, split: splitKey, days_per_week: days, weeks: Number(weeks), volume_preference: volume },
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

  const running = progress !== null;

  return (
    <form onSubmit={handleGenerate} className="flex flex-col gap-3 w-full border rounded p-4">
      <p className="font-medium">Generate a program</p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select value={goal} onChange={(e) => setGoal(e.target.value)} className={selectClass} disabled={running}>
          {GOALS.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <select
          value={splitKey}
          onChange={(e) => chooseSplit(e.target.value)}
          className={`${selectClass} flex-1`}
          disabled={running}
        >
          {splits.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className={selectClass}
          disabled={running}
        >
          {(split?.allowed_days ?? []).map((d) => (
            <option key={d} value={d}>
              {d} days/week
            </option>
          ))}
        </select>
        <input
          type="number"
          min={2}
          max={12}
          value={weeks}
          onChange={(e) => setWeeks(e.target.value)}
          className={`${selectClass} w-20`}
          disabled={running}
          required
        />
        <span className="text-zinc-500">weeks</span>
        <select
          value={volume}
          onChange={(e) => setVolume(e.target.value as VolumePreference)}
          className={selectClass}
          disabled={running}
          title="Hypertrophy: weekly sets per muscle within the research's most efficient range (Pelland et al. 2025's tiers, secondary work counted as half). Minimal pairs fewer sets with sets taken closer to failure."
        >
          {(Object.keys(VOLUME_LABELS) as VolumePreference[]).map((v) => (
            <option key={v} value={v}>
              {volumeLabel(v, goal)}
            </option>
          ))}
        </select>
      </div>
      {split && (
        <p className="text-xs text-zinc-500">
          {split.label} rotates {split.day_types.join(" / ")}. Exercises are picked by AI and aren&apos;t
          research-cited; every sets, load, frequency and progression number is.
        </p>
      )}
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={running || !split}
          className="rounded bg-black text-white px-4 py-2 text-sm disabled:opacity-50 dark:bg-white dark:text-black"
        >
          {running ? "Generating..." : "Generate program"}
        </button>
        {running && (
          <>
            <span className="text-indigo-600 dark:text-indigo-400 text-xs">
              {progress}... keep this tab open until it finishes
            </span>
            <button type="button" onClick={() => (cancelled.current = true)} className="text-xs underline">
              cancel
            </button>
          </>
        )}
      </div>
      {notice && <p className="text-green-700 dark:text-green-500 text-xs">{notice}</p>}
      {error && <p className="text-red-600 text-xs whitespace-pre-line">{error}</p>}
    </form>
  );
}
