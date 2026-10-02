import type { Program } from "./types";

type Api = <T>(path: string, options?: { method?: string; body?: unknown }) => Promise<T>;

export type BlockGenerationResult = { failures: string[]; cancelled: boolean };

// Requests in flight at once for the independent phases. Each request is
// several seconds of retrieval, generation and verification.
const CONCURRENCY = 3;

// Weekly volume is split across a muscle's exercises after crediting the
// half-sets other exercises give it as a secondary, so muscles that receive
// that credit go AFTER the ones that provide it: compound-dominant muscles
// first (a row's sets must exist before lats can count half of them).
const VOLUME_ORDER = [
  "chest", "upper back", "lats", "quadriceps", "glutes", "hamstrings", "lower back",
  "front delts", "side delts", "rear delts", "triceps", "biceps", "calves", "abs",
];

function volumeRank(group: string) {
  const i = VOLUME_ORDER.indexOf(group);
  return i === -1 ? VOLUME_ORDER.length : i; // unknown/legacy names (e.g. "back") last
}

// Fills in every number for one block, as many small requests driven from
// the browser (progress is visible, nothing hits a request timeout):
//   1. frequency per muscle group - research comparison only, never adds
//      days: the user committed to their own days per week
//   2. weekly volume per muscle group - the cited weekly total, split
//      across that muscle's exercises (capped per exercise)
//   3. reps, effort (RIR) and - strength only - load per exercise,
//      applied to every week
//   4. progression per muscle group, strength programs only
export async function runBlockGeneration(
  api: Api,
  programId: number,
  mesocycleId: number,
  hooks: { onProgress: (label: string) => void; onStepDone: () => void; isCancelled: () => boolean },
): Promise<BlockGenerationResult> {
  // The run lives in this tab: reloading or closing it stops generation
  // partway (finished steps are kept). Ask the browser to confirm first.
  const warnBeforeLeaving = (e: BeforeUnloadEvent) => e.preventDefault();
  window.addEventListener("beforeunload", warnBeforeLeaving);
  try {
    return await runSteps(api, programId, mesocycleId, hooks);
  } finally {
    window.removeEventListener("beforeunload", warnBeforeLeaving);
  }
}

async function runSteps(
  api: Api,
  programId: number,
  mesocycleId: number,
  hooks: { onProgress: (label: string) => void; onStepDone: () => void; isCancelled: () => boolean },
): Promise<BlockGenerationResult> {
  const failures: string[] = [];

  async function step(label: string, path: string, body?: unknown) {
    if (hooks.isCancelled()) return;
    try {
      await api(path, { method: "POST", body });
    } catch (err) {
      failures.push(`${label}: ${err instanceof Error ? err.message : String(err)}`);
    }
    hooks.onStepDone();
  }

  // Runs independent steps, up to CONCURRENCY at a time.
  async function runParallel(steps: (() => Promise<void>)[]) {
    let next = 0;
    async function worker() {
      while (next < steps.length && !hooks.isCancelled()) await steps[next++]();
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, steps.length) }, worker));
  }

  const program = await api<Program>(`/programs/${programId}`);
  const block = program.mesocycles.find((m) => m.id === mesocycleId);
  if (!block) throw new Error("Block not found");
  const slots = block.day_templates.flatMap((d) => d.exercise_slots);
  const groups = [...new Set(slots.map((s) => s.muscle_group))].sort((a, b) => volumeRank(a) - volumeRank(b));

  let done = 0;
  const counted = (phase: string, total: number, run: () => Promise<void>) => async () => {
    await run();
    done++;
    hooks.onProgress(`${phase} ${done}/${total}`);
  };

  done = 0;
  hooks.onProgress(`Frequency 0/${groups.length}`);
  await runParallel(groups.map((group) => counted("Frequency", groups.length, () =>
    step(`Frequency (${group})`, `/mesocycles/${mesocycleId}/generate-frequency`, { muscle_group: group, add_days: false }),
  )));

  // Sequential, in VOLUME_ORDER, so each muscle's split sees the secondary
  // credit from muscles already split.
  done = 0;
  hooks.onProgress(`Weekly volume 0/${groups.length}`);
  for (const group of groups) {
    await counted("Weekly volume", groups.length, () =>
      step(`Weekly volume (${group})`, `/mesocycles/${mesocycleId}/generate-weekly-volume`, { muscle_group: group }),
    )();
  }

  done = 0;
  hooks.onProgress(`Reps & effort 0/${slots.length}`);
  await runParallel(slots.map((slot) => counted("Reps & effort", slots.length, () =>
    step(`Reps & effort (${slot.exercise_name})`, `/exercise-slots/${slot.id}/generate`),
  )));

  if (program.goal === "strength") {
    done = 0;
    hooks.onProgress(`Progression 0/${groups.length}`);
    await runParallel(groups.map((group) => counted("Progression", groups.length, () =>
      step(`Progression (${group})`, `/mesocycles/${mesocycleId}/generate-progression`, { muscle_group: group }),
    )));
  }

  return { failures, cancelled: hooks.isCancelled() };
}
