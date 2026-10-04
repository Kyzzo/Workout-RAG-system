// How to progress a hypertrophy program week to week. Hypertrophy programs
// don't schedule progression into the numbers (strength programs do, via
// their cited linear scheme): it depends on how each session actually goes,
// so it's given as a principle the lifter applies, i.e. double progression.
// Deliberately labeled as general guidance - unlike every number in the
// program, this box isn't tied to a cited source.
export default function ProgressionGuide() {
  return (
    <details open className="w-full border rounded p-3 text-xs bg-zinc-50 dark:bg-zinc-900">
      <summary className="font-medium text-sm cursor-pointer">How to progress</summary>
      <ol className="list-decimal list-inside flex flex-col gap-1 mt-2 text-zinc-700 dark:text-zinc-300">
        <li>
          Pick a weight that lets you hit the <span className="font-medium">bottom</span> of each exercise&apos;s rep
          range at its prescribed effort (RIR).
        </li>
        <li>
          Session to session, try to <span className="font-medium">add reps</span> at the same weight and effort.
        </li>
        <li>
          Once you reach the <span className="font-medium">top of the range on every set</span> at the prescribed RIR,
          increase the weight by the smallest step available (often about 2.5-5%) and work back up from the bottom of
          the range.
        </li>
        <li>
          Keep the effort honest: if reps only go up because sets drift further from failure than prescribed, that
          isn&apos;t progress.
        </li>
        <li>
          If a lift stalls for a few sessions in a row despite good sleep and recovery, consider a lighter week before
          pushing again.
        </li>
      </ol>
      <p className="mt-2 text-zinc-500">
        General guidance based on common hypertrophy principles (double progression) - not tied to a specific study,
        unlike the sets, reps and effort above it.
      </p>
    </details>
  );
}
