"use client";

import { Check } from "./Icons";
import { ProgressBar, Spinner } from "./ui";

// The phases runBlockGeneration reports ("Weekly volume 3/12"), plus the
// wizard's first step. Strength runs frequency and progression as well.
const PHASES: { key: string; label: string; strengthOnly?: boolean; wizardOnly?: boolean }[] = [
  { key: "Choosing exercises", label: "Exercises", wizardOnly: true },
  { key: "Frequency", label: "Frequency", strengthOnly: true },
  { key: "Weekly volume", label: "Volume" },
  { key: "Reps & effort", label: "Reps & effort" },
  { key: "Progression", label: "Progression", strengthOnly: true },
];

function parse(progress: string) {
  const match = progress.match(/^(.*?) (\d+)\/(\d+)$/);
  if (!match) return { phase: progress, fraction: null };
  const [, phase, done, total] = match;
  return { phase, fraction: Number(total) > 0 ? Number(done) / Number(total) : 0, done, total };
}

export default function GenerationProgress({
  progress,
  strength,
  includeExercises,
  onCancel,
}: {
  progress: string;
  strength: boolean;
  // The wizard also chooses the exercises; block generation starts at volume.
  includeExercises: boolean;
  onCancel: () => void;
}) {
  const parsed = parse(progress);
  const phases = PHASES.filter((p) => (strength || !p.strengthOnly) && (includeExercises || !p.wizardOnly));
  const current = phases.findIndex((p) => parsed.phase.startsWith(p.key));

  return (
    <div className="animate-in flex flex-col gap-3.5 rounded-xl border border-line bg-surface-2/60 p-4" aria-live="polite">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5 text-sm">
          <Spinner className="size-4 shrink-0 text-accent-text" />
          <span className="truncate font-medium">{parsed.phase}</span>
          {"done" in parsed && (
            <span className="font-mono text-xs tabular-nums text-fg-subtle">
              {parsed.done}/{parsed.total}
            </span>
          )}
        </div>
        <button type="button" onClick={onCancel} className="btn btn-ghost btn-sm">
          Stop
        </button>
      </div>
      <ProgressBar value={parsed.fraction} />
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
        {phases.map((p, i) => {
          const state = current === -1 ? "todo" : i < current ? "done" : i === current ? "now" : "todo";
          return (
            <li key={p.key} className="flex items-center gap-1.5">
              {i > 0 && <span className="h-px w-3 bg-line-strong" aria-hidden="true" />}
              <span
                className={`flex items-center gap-1 rounded-full px-2 py-0.5 ${
                  state === "now"
                    ? "bg-accent-soft font-medium text-accent-text"
                    : state === "done"
                      ? "text-evidence"
                      : "text-fg-subtle"
                }`}
              >
                {state === "done" && <Check className="size-3" />}
                {p.label}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-fg-subtle">Keep this tab open until it finishes. Stopping keeps the steps already done.</p>
    </div>
  );
}
