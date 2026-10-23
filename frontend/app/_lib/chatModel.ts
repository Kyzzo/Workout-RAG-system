import type {
  ChangeStatus,
  ChatMessageRequest,
  ChatResponse,
  RebalanceOut,
  SavedChatTurn,
  SwapExerciseResponse,
  WeeklyPrescription,
} from "../types";
import { valuesSentence } from "./format";

export type Anchor = {
  prescriptionId: number;
  programId: number; // which program's tree to re-read after a change (not sent)
  // "Barbell Bench Press" for an every-week row, "Barbell Bench Press, week 2"
  // for one week. Saved with the message.
  label: string;
  thisWeekOnly: boolean;
};

export type RebalanceState =
  | { phase: "offered"; error?: string }
  | { phase: "applying"; field: string }
  | { phase: "applied"; prescription: WeeklyPrescription; changeId: number; error?: string }
  | { phase: "undoing"; prescription: WeeklyPrescription; changeId: number }
  | { phase: "undone" }
  | { phase: "kept" };

export type UserTurn = { id: string; role: "user"; text: string; anchor: string | null };
export type AssistantTurn = {
  id: string;
  role: "assistant";
  response: ChatResponse;
  status: ChangeStatus | null;
  busy?: "confirm" | "cancel" | "undo" | null;
  rebalance?: RebalanceState;
};
export type ErrorTurn = { id: string; role: "error"; text: string };
export type Turn = UserTurn | AssistantTurn | ErrorTurn;

// ---- Suggested prompts. The general questions are server cache keys:
// sent verbatim, or every user pays for a fresh ~20 s answer. ----

export const GENERAL_QUESTIONS: Record<"hypertrophy" | "strength", string[]> = {
  hypertrophy: [
    "How many sets per week should I do per muscle?",
    "How close to failure should I train?",
    "Does training a muscle 3x a week beat 2x?",
    "Should I add reps or add weight to progress?",
  ],
  strength: [
    "How many sets per week build strength?",
    "Do I need to train to failure to get stronger?",
    "Is undulating periodization better than linear?",
    "Should I take a deload week?",
  ],
};

export function askPrompts(loadIsPercent: boolean): string[] {
  return ["Why this many sets?", "Why this rep range?", "Why this effort (RIR)?", ...(loadIsPercent ? ["Why this load?"] : [])];
}

export function changePrompts(loadIsPercent: boolean): string[] {
  return [
    "Add a set",
    "Remove a set",
    "Take it closer to failure",
    "Leave more reps in reserve",
    ...(loadIsPercent ? ["Make it heavier", "Make it lighter"] : []),
    "Swap this exercise",
  ];
}

// ---- Responses ----

export function freshStatus(r: ChatResponse): ChangeStatus | null {
  if (r.swap?.pending) return "pending";
  if ((r.change_id ?? r.swap?.change_id) != null) return "applied";
  return null;
}

export function changeIdOf(r: ChatResponse): number | null {
  return r.change_id ?? r.swap?.change_id ?? null;
}

const NEW_EXERCISE_MARK = " - the new exercise:";

// The swap's changes to the new exercise itself (marker prefix removed), and
// its side effects on the rest of the block.
export function splitSwapChanges(changes: string[]): { own: string[]; other: string[] } {
  const own: string[] = [];
  const other: string[] = [];
  for (const change of changes) {
    const i = change.indexOf(NEW_EXERCISE_MARK);
    if (i === -1) other.push(change);
    else own.push(change.slice(i + NEW_EXERCISE_MARK.length).trim());
  }
  return { own, other };
}

function stripStop(text: string) {
  return text.replace(/[.\s]+$/, "");
}

// `Swapped "<old>" for "<new>".` plus the other changes, or that nothing
// else changed.
export function swapSummary(swap: SwapExerciseResponse): string {
  const { other } = splitSwapChanges(swap.changes);
  const tail = other.length ? ` Also changed: ${other.map(stripStop).join("; ")}.` : " Nothing else in the block changed.";
  return `Swapped "${swap.old_name}" for "${swap.new_name}".${tail}`;
}

// A blank line splits a general answer into its practical summary and the
// supporting evidence behind it.
export function splitAnswer(answer: string): { summary: string; evidence: string | null } {
  const i = answer.indexOf("\n\n");
  if (i === -1) return { summary: answer, evidence: null };
  return { summary: answer.slice(0, i), evidence: answer.slice(i + 2).trim() || null };
}

// ---- History sent with each message: context for follow-ups ("ok lower
// it"), never a source of ids or authority on the server. ----

function assistantLine(r: ChatResponse): string {
  if (r.mode === "adjust_prescription" && r.swap) {
    return r.swap.pending ? `Previewed swapping ${r.swap.old_name} for ${r.swap.new_name}.` : swapSummary(r.swap);
  }
  if (r.mode === "adjust_prescription") {
    if (r.answer) return `Kept as is: ${r.answer}`;
    if (r.prescription) {
      return `Updated it to ${valuesSentence(r.prescription)}.${r.grounding_note ? ` ${r.grounding_note}` : ""}`;
    }
    return "";
  }
  if (r.mode === "discuss_prescription") {
    const current = r.prescription ? ` (Current: ${valuesSentence(r.prescription)}.)` : "";
    return `${r.answer ?? ""}${current}`;
  }
  return r.answer ?? "";
}

export function historyFor(turns: Turn[]): ChatMessageRequest["history"] {
  return turns
    .filter((t): t is UserTurn | AssistantTurn => t.role !== "error")
    .map((t) =>
      t.role === "user"
        ? { role: "user" as const, content: t.anchor ? `[about ${t.anchor}] ${t.text}` : t.text }
        : { role: "assistant" as const, content: assistantLine(t.response) },
    )
    .slice(-10)
    .map((h) => ({ ...h, content: h.content.slice(0, 2000) }));
}

// ---- Saved history ----

let counter = 0;
export function turnId(prefix = "t"): string {
  counter += 1;
  return `${prefix}${counter}`;
}

function asResponse(content: Record<string, unknown>): ChatResponse {
  const c = content as Partial<ChatResponse>;
  return {
    mode: c.mode ?? "answer_general_question",
    prescription: c.prescription ?? null,
    answer: c.answer ?? null,
    citations: c.citations ?? [],
    grounding_note: c.grounding_note ?? null,
    rebalance: (c.rebalance as RebalanceOut | null) ?? null,
    swap: c.swap ?? null,
    change_id: c.change_id ?? null,
  };
}

export function turnsFromHistory(saved: SavedChatTurn[]): Turn[] {
  return saved.map((s): Turn => {
    if (s.role === "user") {
      const text = typeof s.content.text === "string" ? s.content.text : "";
      const anchor = typeof s.content.anchor === "string" ? s.content.anchor : null;
      return { id: turnId("h"), role: "user", text, anchor };
    }
    const response = asResponse(s.content);
    return {
      id: turnId("h"),
      role: "assistant",
      response,
      status: s.change_status ?? null,
      rebalance: response.rebalance ? { phase: "offered" } : undefined,
    };
  });
}

// ---- NDJSON stream ----

export type StreamEvent =
  | { type: "stage"; label: string }
  | { type: "result"; response: ChatResponse }
  | { type: "error"; status: number; detail: unknown };

export async function readNdjson(res: Response, onEvent: (e: StreamEvent) => void): Promise<void> {
  if (!res.body) {
    for (const line of (await res.text()).split("\n")) if (line.trim()) onEvent(JSON.parse(line));
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as StreamEvent);
      newline = buffer.indexOf("\n");
    }
    if (done) break;
  }
  const rest = (buffer + decoder.decode()).trim();
  if (rest) onEvent(JSON.parse(rest) as StreamEvent);
}

export function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
      .join("; ");
  }
  return detail == null ? "Something went wrong." : JSON.stringify(detail);
}
