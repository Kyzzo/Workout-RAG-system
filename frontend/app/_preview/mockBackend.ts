// An in-browser stand-in for the FastAPI backend, for `npm run preview`
// only. It answers the same paths with the same shapes, slowly enough that
// loading states show, and keeps its state in memory for the page's life.

import type { Api, ApiStream } from "../useApi";
import { ApiError } from "../useApi";
import type {
  ChatMessageRequest,
  ChatResponse,
  DayTemplate,
  ExerciseSlot,
  Mesocycle,
  Program,
  ProgramSummary,
  SwapExerciseResponse,
} from "../types";
import {
  buildBlock,
  CITATIONS,
  cites,
  emptyProgram,
  hypertrophyProgram,
  newId,
  resetIds,
  rule,
  RULE_KEYS,
  SPLITS,
  strengthProgram,
} from "./fixtures";

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

type Change = { id: number; status: "pending" | "applied" | "undone" | "cancelled"; apply: () => void; undo: () => void; result?: unknown };

export function createMockBackend(options: { empty?: boolean } = {}) {
  resetIds();
  const programs: Program[] = options.empty ? [] : [hypertrophyProgram(103), strengthProgram(102), emptyProgram(101)];
  const changes = new Map<number, Change>();
  let history: { role: "user" | "assistant"; content: Record<string, unknown>; change_status: string | null }[] = [];

  const find = (id: number) => {
    const p = programs.find((x) => x.id === id);
    if (!p) throw new ApiError(404, "Program not found");
    return p;
  };
  const blocks = () => programs.flatMap((p) => p.mesocycles);
  const days = () => blocks().flatMap((b) => b.day_templates);
  const slots = () => days().flatMap((d) => d.exercise_slots);
  const rxs = () => slots().flatMap((s) => s.weekly_prescriptions);
  const one = <T,>(list: T[], pred: (t: T) => boolean, what: string): T => {
    const hit = list.find(pred);
    if (!hit) throw new ApiError(404, `${what} not found`);
    return hit;
  };
  const blockOf = (slot: ExerciseSlot) => one(blocks(), (b) => b.day_templates.some((d) => d.id === slot.day_template_id), "Block");
  const programOf = (b: Mesocycle) => find(b.program_id);
  const summary = (p: Program): ProgramSummary => ({
    id: p.id,
    goal: p.goal,
    name: p.name,
    volume_preference: p.volume_preference,
    trained: p.trained,
    include_deload: p.include_deload,
  });

  function fill(slot: ExerciseSlot, goal: string) {
    for (const p of slot.weekly_prescriptions) {
      p.reps = goal === "strength" ? "6" : "8-12";
      p.rir = "1-2 RIR";
      p.load = goal === "strength" ? "77.5% 1RM" : "";
      p.reps_citations = cites([502, 506], 1);
      p.rir_citations = cites([504], 1);
      p.load_citations = goal === "strength" ? cites([500, 514], 1) : [];
      if (!p.sets) p.sets = 3;
    }
  }

  function record(apply: () => void, undo: () => void, applied = true): number {
    const id = newId();
    if (applied) apply();
    changes.set(id, { id, status: applied ? "applied" : "pending", apply, undo });
    return id;
  }

  function swapPreview(slot: ExerciseSlot, name: string | null): SwapExerciseResponse {
    const next = name || (slot.muscle_group === "chest" ? "Machine Chest Press" : `Cable ${slot.exercise_name.split(" ").slice(-1)[0]}`);
    if (next.toLowerCase() === slot.exercise_name.toLowerCase()) throw new ApiError(400, "That's the exercise already in this slot.");
    const old = slot.exercise_name;
    const changeList = [
      `${next} - the new exercise: ${slot.weekly_prescriptions[0]?.sets || 3} sets of ${slot.weekly_prescriptions[0]?.reps || "8-12"}, 1-2 RIR`,
      ...(slot.secondary_muscle_groups.length ? [`${slot.secondary_muscle_groups[0]}: weekly sets stay within half a set of before`] : []),
    ];
    const id = record(
      () => {
        slot.exercise_name = next;
      },
      () => {
        slot.exercise_name = old;
      },
      false,
    );
    const preview: SwapExerciseResponse = { slot: clone(slot), old_name: old, new_name: next, changes: changeList, change_id: id, pending: true };
    changes.get(id)!.result = { ...preview, pending: false, slotId: slot.id };
    return preview;
  }

  const routes: [string, RegExp, (m: RegExpMatchArray, body: Record<string, unknown>) => unknown | Promise<unknown>][] = [
    ["GET", /^\/splits\/$/, () => SPLITS],
    ["GET", /^\/programs\/$/, () => programs.map(summary)],
    ["GET", /^\/programs\/(\d+)$/, (m) => find(Number(m[1]))],
    [
      "POST",
      /^\/programs\/generate$/,
      async (_m, body) => {
        await wait(1600);
        const split = SPLITS.find((s) => s.key === body.split) ?? SPLITS[0];
        const n = Number(body.days_per_week);
        if (!split.allowed_days.includes(n)) throw new ApiError(422, `${split.label} allows ${split.allowed_days.join(", ")} days a week.`);
        const id = newId();
        const base = Math.floor((7 - n) / n);
        const counts = new Map<string, number>();
        const dayList = Array.from({ length: n }, (_, i) => {
          const type = split.day_types[i % split.day_types.length];
          counts.set(type, (counts.get(type) ?? 0) + 1);
          const repeats = n / split.day_types.length > 1;
          return {
            name: repeats ? `${type} ${String.fromCharCode(64 + (counts.get(type) ?? 1))}` : type,
            rest: i === 0 ? null : base,
            exercises: [
              { name: `${type} Compound Lift`, muscle: i % 2 ? "quadriceps" : "chest", also: i % 2 ? ["glutes"] : ["triceps"] },
              { name: `${type} Accessory`, muscle: i % 2 ? "hamstrings" : "upper back" },
            ],
          };
        });
        const weeks = Number(body.weeks) || 6;
        const goal = String(body.goal);
        const b = buildBlock(id, `${goal[0].toUpperCase()}${goal.slice(1)} block`, 1, weeks, dayList);
        const taken = programs.filter((p) => p.name?.startsWith(`${split.label} · ${n} days`)).length;
        const program: Program = {
          id,
          user_id: 1,
          goal,
          name: `${split.label} · ${n} days${taken ? ` ${taken + 1}` : ""}`,
          volume_preference: body.volume_preference as Program["volume_preference"],
          trained: !!body.trained,
          include_deload: !!body.include_deload,
          mesocycles: [b],
        };
        programs.unshift(program);
        return program;
      },
    ],
    [
      "POST",
      /^\/programs\/$/,
      (_m, body) => {
        const p = { ...emptyProgram(newId()), goal: String(body.goal), volume_preference: (body.volume_preference ?? "moderate") as Program["volume_preference"] };
        programs.unshift(p);
        return summary(p);
      },
    ],
    [
      "PATCH",
      /^\/programs\/(\d+)$/,
      (m, body) => {
        const p = find(Number(m[1]));
        p.name = String(body.name).trim();
        return summary(p);
      },
    ],
    [
      "DELETE",
      /^\/programs\/(\d+)$/,
      (m) => {
        programs.splice(programs.indexOf(find(Number(m[1]))), 1);
        return undefined;
      },
    ],
    [
      "POST",
      /^\/programs\/(\d+)\/mesocycles$/,
      (m, body) => {
        const p = find(Number(m[1]));
        const s = Number(body.start_week);
        const e = Number(body.end_week);
        const clash = p.mesocycles.find((b) => s <= b.end_week && e >= b.start_week);
        if (clash) throw new ApiError(400, `Weeks ${s}-${e} overlap “${clash.name}” (weeks ${clash.start_week}-${clash.end_week}).`);
        const b = buildBlock(p.id, String(body.name), s, e, []);
        p.mesocycles.push(b);
        return b;
      },
    ],
    [
      "PATCH",
      /^\/mesocycles\/(\d+)$/,
      (m, body) => {
        const b = one(blocks(), (x) => x.id === Number(m[1]), "Block");
        b.name = String(body.name);
        return { id: b.id, name: b.name };
      },
    ],
    [
      "POST",
      /^\/mesocycles\/(\d+)\/days$/,
      (m, body) => {
        const b = one(blocks(), (x) => x.id === Number(m[1]), "Block");
        const d: DayTemplate = { id: newId(), mesocycle_id: b.id, name: String(body.name), order: b.day_templates.length, rest_days_before: (body.rest_days_before as number | null) ?? null, exercise_slots: [] };
        b.day_templates.push(d);
        return d;
      },
    ],
    [
      "PATCH",
      /^\/day-templates\/(\d+)$/,
      (m, body) => {
        const d = one(days(), (x) => x.id === Number(m[1]), "Day");
        d.name = String(body.name);
        return { id: d.id, name: d.name };
      },
    ],
    [
      "DELETE",
      /^\/day-templates\/(\d+)$/,
      (m) => {
        const b = one(blocks(), (x) => x.day_templates.some((d) => d.id === Number(m[1])), "Day");
        b.day_templates = b.day_templates.filter((d) => d.id !== Number(m[1]));
        return undefined;
      },
    ],
    [
      "POST",
      /^\/day-templates\/(\d+)\/exercises$/,
      (m, body) => {
        const d = one(days(), (x) => x.id === Number(m[1]), "Day");
        const b = one(blocks(), (x) => x.id === d.mesocycle_id, "Block");
        const id = newId();
        const slot: ExerciseSlot = {
          id,
          day_template_id: d.id,
          exercise_name: String(body.exercise_name),
          muscle_group: String(body.muscle_group).trim().toLowerCase(),
          secondary_muscle_groups: (body.secondary_muscle_groups as string[]) ?? [],
          order: d.exercise_slots.length,
          weekly_prescriptions: Array.from({ length: b.end_week - b.start_week + 1 }, (_, w) => ({
            id: newId(), exercise_slot_id: id, week_number: b.start_week + w, sets: 0, reps: "", load: "", rir: "",
            sets_grounding_note: null, reps_grounding_note: null, load_grounding_note: null, rir_grounding_note: null, load_fit_note: null,
            sets_citations: [], reps_citations: [], load_citations: [], rir_citations: [],
          })),
        };
        d.exercise_slots.push(slot);
        return slot;
      },
    ],
    [
      "DELETE",
      /^\/exercise-slots\/(\d+)$/,
      (m) => {
        const d = one(days(), (x) => x.exercise_slots.some((s) => s.id === Number(m[1])), "Exercise");
        d.exercise_slots = d.exercise_slots.filter((s) => s.id !== Number(m[1]));
        return undefined;
      },
    ],
    [
      "POST",
      /^\/mesocycles\/(\d+)\/generate-weekly-volume$/,
      async (m, body) => {
        await wait(900);
        const b = one(blocks(), (x) => x.id === Number(m[1]), "Block");
        const muscle = String(body.muscle_group);
        const program = programOf(b);
        const target = program.goal === "strength" ? 4 : 12;
        const own = b.day_templates.flatMap((d) => d.exercise_slots).filter((s) => s.muscle_group === muscle);
        const per = Math.min(program.goal === "strength" ? 5 : 3, Math.max(1, Math.round(target / Math.max(own.length, 1))));
        own.forEach((s) => s.weekly_prescriptions.forEach((p) => (p.sets = per)));
        let volume = b.muscle_group_volumes.find((v) => v.muscle_group === muscle);
        if (!volume) {
          volume = { id: newId(), muscle_group: muscle, weekly_sets: target, grounding_note: null, supporting_citations: cites([500, 502, 510], 1) };
          b.muscle_group_volumes.push(volume);
        }
        return { volume, delivered_weekly_sets: per * own.length, exercises_added: [] };
      },
    ],
    [
      "POST",
      /^\/mesocycles\/(\d+)\/generate-frequency$/,
      async (m, body) => {
        await wait(700);
        const b = one(blocks(), (x) => x.id === Number(m[1]), "Block");
        const muscle = String(body.muscle_group);
        let f = b.muscle_group_frequencies.find((x) => x.muscle_group === muscle);
        if (!f) {
          f = { id: newId(), muscle_group: muscle, frequency: 2, grounding_note: "Preview fixture note.", supporting_citations: cites([514, 502], 1) };
          b.muscle_group_frequencies.push(f);
        }
        return { frequency: f, days_added: [] };
      },
    ],
    [
      "POST",
      /^\/mesocycles\/(\d+)\/generate-progression$/,
      async (m, body) => {
        await wait(700);
        const b = one(blocks(), (x) => x.id === Number(m[1]), "Block");
        const muscle = String(body.muscle_group);
        let s = b.progression_schemes.find((x) => x.muscle_group === muscle);
        if (!s) {
          s = { id: newId(), muscle_group: muscle, scheme: "linear", grounding_note: null, supporting_citations: cites([510], 1) };
          b.progression_schemes.push(s);
        }
        const updated = b.day_templates.flatMap((d) => d.exercise_slots).filter((x) => x.muscle_group === muscle).flatMap((x) => x.weekly_prescriptions);
        return { scheme: s, updated_prescriptions: updated };
      },
    ],
    [
      "POST",
      /^\/exercise-slots\/(\d+)\/generate$/,
      async (m) => {
        await wait(800);
        const slot = one(slots(), (s) => s.id === Number(m[1]), "Exercise");
        if (!slot.weekly_prescriptions.length) throw new ApiError(400, "This exercise has no weeks to generate.");
        fill(slot, programOf(blockOf(slot)).goal);
        return slot;
      },
    ],
    [
      "POST",
      /^\/weekly-prescriptions\/(\d+)\/generate-volume$/,
      async (m) => {
        await wait(700);
        const p = one(rxs(), (x) => x.id === Number(m[1]), "Prescription");
        p.sets = Math.max(1, p.sets || 3);
        p.sets_citations = cites([500, 502], 1);
        return p;
      },
    ],
    [
      "POST",
      /^\/weekly-prescriptions\/(\d+)\/generate-intensity$/,
      async (m) => {
        await wait(700);
        const p = one(rxs(), (x) => x.id === Number(m[1]), "Prescription");
        p.load = p.load || "75% 1RM";
        return p;
      },
    ],
    [
      "POST",
      /^\/weekly-prescriptions\/(\d+)\/rebalance$/,
      async (m, body) => {
        await wait(600);
        const p = one(rxs(), (x) => x.id === Number(m[1]), "Prescription");
        const before = clone(p);
        const id = record(
          () => {
            if (body.apply_field === "reps") p.reps = String(Math.max(1, parseFloat(p.reps) - 1));
            else if (body.apply_field === "rir") p.rir = "2-3 RIR";
            else p.load = "75% 1RM";
            p.load_fit_note = null;
          },
          () => Object.assign(p, before),
        );
        return { prescription: clone(p), change_id: id };
      },
    ],
    [
      "POST",
      /^\/exercise-slots\/(\d+)\/swap$/,
      async (m, body) => {
        await wait(1100);
        const slot = one(slots(), (s) => s.id === Number(m[1]), "Exercise");
        return swapPreview(slot, (body.exercise_name as string | null) ?? null);
      },
    ],
    [
      "POST",
      /^\/changes\/(\d+)\/confirm$/,
      async (m) => {
        await wait(500);
        const c = changes.get(Number(m[1]));
        if (!c || c.status !== "pending") throw new ApiError(409, "This preview was already confirmed or cancelled.");
        c.apply();
        c.status = "applied";
        const { slotId, ...applied } = c.result as SwapExerciseResponse & { slotId: number };
        return { ...applied, slot: one(slots(), (x) => x.id === slotId, "Exercise") };
      },
    ],
    [
      "DELETE",
      /^\/changes\/(\d+)$/,
      (m) => {
        const c = changes.get(Number(m[1]));
        if (!c || c.status !== "pending") throw new ApiError(409, "This change was already applied - undo it instead.");
        c.status = "cancelled";
        return undefined;
      },
    ],
    [
      "POST",
      /^\/changes\/(\d+)\/undo$/,
      async (m) => {
        await wait(500);
        const c = changes.get(Number(m[1]));
        if (!c || c.status !== "applied") throw new ApiError(409, "This change was already undone, or never applied.");
        c.undo();
        c.status = "undone";
        return { id: c.id, kind: "change", description: "", status: "undone" };
      },
    ],
    ["GET", /^\/citations\/(\d+)$/, async (m) => (await wait(350), one([...CITATIONS.values()], (c) => c.id === Number(m[1]), "Citation"))],
    [
      "POST",
      /^\/citations\/summary$/,
      async (_m, body) => {
        await wait(1800);
        const n = (body.citation_ids as number[]).length;
        return {
          summary: `Preview fixture summary across ${n} ${n === 1 ? "study" : "studies"}: this is where the server's single checked, plain-language answer to “${String(body.question)}” appears.`,
        };
      },
    ],
    ["GET", /^\/rules\/([a-z_]+)$/, async (m) => (await wait(500), rule(m[1], Math.max(0, RULE_KEYS.indexOf(m[1]))))],
    ["GET", /^\/chat\/history$/, () => clone(history)],
    [
      "DELETE",
      /^\/chat\/history$/,
      () => {
        history = [];
        return undefined;
      },
    ],
  ];

  async function handle(method: string, path: string, body: unknown) {
    const clean = path.split("?")[0];
    for (const [verb, pattern, fn] of routes) {
      const m = clean.match(pattern);
      if (verb === method && m) {
        await wait(180 + Math.random() * 260);
        return fn(m, (body ?? {}) as Record<string, unknown>);
      }
    }
    throw new ApiError(404, `Preview has no route for ${method} ${clean}`);
  }

  const api: Api = async <T,>(path: string, options: { method?: string; body?: unknown } = {}) => {
    const result = await handle(options.method ?? "GET", path, options.body);
    return clone(result) as T;
  };

  // ---- chat ----

  function answer(req: ChatMessageRequest): ChatResponse {
    const base: ChatResponse = { mode: "answer_general_question", prescription: null, answer: null, citations: [], grounding_note: null, rebalance: null, swap: null, change_id: null };
    const text = req.message.toLowerCase();
    const cited = [500, 502, 510].map((id) => ({ title: CITATIONS.get(id)!.title, snippet: CITATIONS.get(id)!.snippet, field: null }));
    if (req.field_id == null) {
      return {
        ...base,
        answer:
          "Preview fixture answer. The practical summary comes first: a short, direct reply to the question, with numbered references to the studies behind it [1][2].\n\nThe supporting evidence follows, opened on demand. It walks through what each study found and for whom, so the claim never outruns the population that was tested [2][3].",
        citations: cited,
        grounding_note: text.includes("failure") ? "Preview fixture note: most of these trials used trained lifters." : null,
      };
    }
    const p = one(rxs(), (x) => x.id === req.field_id, "Prescription");
    const slot = one(slots(), (s) => s.id === p.exercise_slot_id, "Exercise");
    if (text.includes("swap")) return { ...base, mode: "adjust_prescription", swap: swapPreview(slot, null) };
    if (text.startsWith("why")) {
      return {
        ...base,
        mode: "discuss_prescription",
        prescription: clone(p),
        answer: `Preview fixture: why ${slot.exercise_name} is set this way, with the studies that support it [1] and related evidence [2].`,
        citations: cited.map((c, i) => ({ ...c, field: (["sets", "reps", "rir"] as const)[i] })),
      };
    }
    const before = clone(p);
    let rebalance: ChatResponse["rebalance"] = null;
    const apply = () => {
      if (text.includes("add a set")) p.sets = Math.min(5, p.sets + 1);
      else if (text.includes("remove a set")) p.sets = Math.max(1, p.sets - 1);
      else if (text.includes("closer to failure")) p.rir = "0-1 RIR";
      else if (text.includes("reps in reserve")) p.rir = "2-3 RIR";
      else if (text.includes("heavier") || text.includes("lighter")) {
        p.load = text.includes("heavier") ? "80% 1RM" : "70% 1RM";
        p.load_fit_note = "Preview fixture: reps, load and RIR no longer fit together.";
      }
    };
    if (p.sets >= 3 && text.includes("add a set") && slot.muscle_group === "chest") {
      return { ...base, mode: "adjust_prescription", prescription: clone(p), answer: "Preview fixture: kept as is - this exercise is already at the per-session set cap." };
    }
    const changeId = record(apply, () => Object.assign(p, before));
    if (text.includes("heavier") || text.includes("lighter")) {
      rebalance = {
        prescription_id: p.id,
        changed_field: "load",
        message: "Preview fixture: at this load, the reps and effort no longer fit the reps-to-failure table.",
        options: [
          { field: "reps", value: "5", label: "Lower the reps to 5" },
          { field: "rir", value: "2-3 RIR", label: "Leave 2-3 reps in reserve" },
        ],
      };
    }
    return { ...base, mode: "adjust_prescription", prescription: clone(p), change_id: changeId, rebalance, grounding_note: text.includes("set") ? "Preview fixture note: now above the efficiency tier the program was built on." : null };
  }

  const stream: ApiStream = async (_path, body) => {
    const req = body as ChatMessageRequest;
    const encoder = new TextEncoder();
    const readable = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (event: unknown) => controller.enqueue(encoder.encode(`${JSON.stringify(event)}\n`));
        const cached = req.field_id == null && /how many sets per week should i do/i.test(req.message);
        const stages = cached
          ? ["Found a saved answer"]
          : req.field_id != null
            ? ["Understanding your question", "Reading this prescription's sources", "Working on the change"]
            : ["Understanding your question", "Searching the papers", "Writing the answer", "Checking 6 statements"];
        for (const label of stages) {
          send({ type: "stage", label });
          await wait(cached ? 300 : 900);
        }
        try {
          const response = answer(req);
          history.push({ role: "user", content: { text: req.message, anchor: req.anchor_label }, change_status: null });
          history.push({ role: "assistant", content: response as unknown as Record<string, unknown>, change_status: null });
          send({ type: "result", response });
        } catch (err) {
          send({ type: "error", status: err instanceof ApiError ? err.status : 500, detail: err instanceof Error ? err.message : "Something went wrong." });
        }
        controller.close();
      },
    });
    return new Response(readable, { status: 200, headers: { "Content-Type": "application/x-ndjson" } });
  };

  return { api, stream, programs };
}

export type MockBackend = ReturnType<typeof createMockBackend>;
