import { ChevronRight, TrendingUp } from "./Icons";
import { RuleSources } from "./RuleSources";

// How to progress a hypertrophy program week to week. Hypertrophy programs
// don't schedule progression into the numbers (strength programs do, via
// their cited scheme): it depends on how each session actually goes, so
// it's given as a principle the lifter applies, i.e. double progression.
// Adding reps at a fixed load is cited (Plotkin et al. 2022); combining it
// with load increases at the top of the range is labeled as convention.
const STEPS: React.ReactNode[] = [
  <>
    {/* Explicit space: the build dropped the one before "of" (it rendered "bottomof"). */}
    Pick a weight that lets you hit the <strong className="font-medium text-fg">bottom</strong>{" "}of each
    exercise&apos;s rep range, around its prescribed effort (RIR).
  </>,
  <>
    Session to session, try to <strong className="font-medium text-fg">add reps</strong> at the same weight.
  </>,
  <>
    Once you reach the <strong className="font-medium text-fg">top of the range on every set</strong>, increase the
    weight by the smallest step available (often about 2.5-5%) and work back up from the bottom of the range.
  </>,
  <>Keep your form consistent: if reps only go up because your form breaks down, that isn&apos;t progress.</>,
  <>
    Stalling for a few sessions is a normal part of progressing. Sleep, recovery and nutrition all play a role in how
    quickly your lifts move.
  </>,
];

export default function ProgressionGuide() {
  return (
    <details className="group card overflow-hidden">
      <summary className="flex cursor-pointer items-center gap-3 px-5 py-4 select-none">
        <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent-text">
          <TrendingUp className="size-4" />
        </span>
        <span className="flex-1">
          <span className="block text-sm font-semibold">How to progress</span>
          <span className="block text-xs text-fg-subtle">Double progression: add reps, then weight</span>
        </span>
        <ChevronRight className="size-4 text-fg-subtle transition-transform duration-200 group-open:rotate-90" />
      </summary>
      <div className="animate-in flex flex-col gap-4 border-t border-line px-5 py-4">
        <ol className="flex flex-col gap-3">
          {STEPS.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm leading-relaxed text-fg-muted">
              <span className="grid size-6 shrink-0 place-items-center rounded-full bg-surface-3 font-mono text-xs text-fg">
                {i + 1}
              </span>
              <span className="pt-0.5">{step}</span>
            </li>
          ))}
        </ol>
        <RuleSources
          text={
            "Adding reps at the same weight built muscle as well as adding weight within a fixed rep range " +
            "(trained lifters, 8 weeks). Combining the two - reps first, then weight at the top of the range " +
            "(double progression) - and the 2.5-5% step are common practice, not tested as such."
          }
          ruleKeys={["hypertrophy_rep_progression"]}
        />
      </div>
    </details>
  );
}
