import type { Program } from "./types";

type Api = <T>(path: string, options?: { method?: string; body?: unknown }) => Promise<T>;

export type BlockGenerationResult = { failures: string[]; cancelled: boolean };

// Requests in flight at once. Each exercise is ~10-15s of retrieval,
// generation and verification, so a 30-exercise block runs ~3x faster.
const CONCURRENCY = 3;

// Fills in every number for one block, as many small requests driven from
// the browser (progress is visible, nothing hits a request timeout):
//   1. frequency per muscle group - research comparison only, never adds
//      days: the user committed to their own days per week
//   2. sets + load once per exercise, applied to every week
//   3. progression per muscle group, strength programs only
// Exercises sharing a muscle group run one after another, in day order,
// because each is told its siblings' sets (a shared weekly budget);
// different muscle groups are independent and run in parallel.
export async function runBlockGeneration(
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

  // Runs each queue's steps in order, up to CONCURRENCY queues at a time.
  async function runQueues(queues: (() => Promise<void>)[][]) {
    let next = 0;
    async function worker() {
      while (next < queues.length && !hooks.isCancelled()) {
        const queue = queues[next++];
        for (const run of queue) await run();
      }
    }
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, queues.length) }, worker));
  }

  const program = await api<Program>(`/programs/${programId}`);
  const block = program.mesocycles.find((m) => m.id === mesocycleId);
  if (!block) throw new Error("Block not found");
  const slots = block.day_templates.flatMap((d) => d.exercise_slots);
  const groups = [...new Set(slots.map((s) => s.muscle_group))].sort();

  let done = 0;
  const progress = (phase: string, total: number) => hooks.onProgress(`${phase} ${done}/${total}`);

  done = 0;
  progress("Frequency", groups.length);
  await runQueues(groups.map((group) => [async () => {
    await step(`Frequency (${group})`, `/mesocycles/${mesocycleId}/generate-frequency`, {
      muscle_group: group,
      add_days: false,
    });
    done++;
    progress("Frequency", groups.length);
  }]));

  done = 0;
  progress("Exercises", slots.length);
  await runQueues(groups.map((group) =>
    slots
      .filter((s) => s.muscle_group === group)
      .map((slot) => async () => {
        await step(slot.exercise_name, `/exercise-slots/${slot.id}/generate`);
        done++;
        progress("Exercises", slots.length);
      }),
  ));

  if (program.goal === "strength") {
    done = 0;
    progress("Progression", groups.length);
    await runQueues(groups.map((group) => [async () => {
      await step(`Progression (${group})`, `/mesocycles/${mesocycleId}/generate-progression`, { muscle_group: group });
      done++;
      progress("Progression", groups.length);
    }]));
  }

  return { failures, cancelled: hooks.isCancelled() };
}
