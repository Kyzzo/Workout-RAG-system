import { RuleSources } from "./RuleSources";

// How to progress a hypertrophy program week to week. Hypertrophy programs
// don't schedule progression into the numbers (strength programs do, via
// their cited scheme): it depends on how each session actually goes, so
// it's given as a principle the lifter applies, i.e. double progression.
// Adding reps at a fixed load is cited (Plotkin et al. 2022); combining it
// with load increases at the top of the range is labeled as convention.
export default function ProgressionGuide() {
  return (
    <details className="w-full border rounded p-3 text-xs bg-zinc-50 dark:bg-zinc-900">
      <summary className="font-medium text-sm cursor-pointer">How to progress</summary>
      <ol className="list-decimal list-inside flex flex-col gap-1 mt-2 text-zinc-700 dark:text-zinc-300">
        <li>
          Pick a weight that lets you hit the{" "}
          <span className="font-medium">bottom</span>{" "}
          of each exercise&apos;s rep range, around its prescribed effort (RIR).
        </li>
        <li>
          Session to session, try to{" "}
          <span className="font-medium">add reps</span>{" "}
          at the same weight.
        </li>
        <li>
          Once you reach the{" "}
          <span className="font-medium">top of the range on every set</span>
          , increase the weight by the smallest step available (often about 2.5-5%) and work back up from the
          bottom of the range.
        </li>
        <li>
          Keep your form consistent: if reps only go up because your form breaks down, that isn&apos;t progress.
        </li>
        <li>
          Stalling for a few sessions is a normal part of progressing. Sleep, recovery and nutrition all play a
          role in how quickly your lifts move.
        </li>
      </ol>
      <div className="mt-2">
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
