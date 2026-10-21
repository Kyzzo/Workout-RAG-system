"use client";

import { useAuth } from "@clerk/nextjs";
import Image from "next/image";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { API_URL } from "./apiUrl";
import { CaveatNote } from "./Citations";
import { useDialogs } from "./Dialogs";
import { ArrowUp, Book, Check, ChevronDown, ChevronRight, Close, Message, Sparkles, Trash, Undo } from "./Icons";
import { swapSummary, type SwapResult } from "./ProgramTree";
import type { WeeklyPrescription } from "./types";
import { Spinner } from "./ui";

type Citation = { title: string; snippet: string; field: "sets" | "reps" | "load" | "rir" | null };

type RebalanceField = "reps" | "load" | "rir";

// Offered when a change to reps, load or RIR leaves the three not fitting:
// each option keeps one of the other two and recalculates the last.
type Rebalance = {
  prescription_id: number;
  changed_field: RebalanceField;
  message: string;
  options: { field: RebalanceField; value: string; label: string }[];
};

type ChatResponse = {
  mode: "adjust_prescription" | "discuss_prescription" | "answer_general_question";
  prescription: WeeklyPrescription | null;
  answer: string | null;
  citations: Citation[];
  grounding_note: string | null;
  rebalance: Rebalance | null;
  // A swap: a preview (pending) until confirmed, with everything it changes.
  swap: SwapResult | null;
  // Set when the message changed the program - undoable.
  change_id: number | null;
};

// A change's state: a swap preview awaiting confirm, applied (undoable),
// undone, or a cancelled preview.
type ChangeStatus = "pending" | "applied" | "undone" | "cancelled";

function changeIdOf(r: ChatResponse): number | null {
  return r.change_id ?? r.swap?.change_id ?? null;
}

type ChatTurn =
  // anchor: which prescription the message was about when sent, so the
  // history stays unambiguous if the user re-anchors mid-conversation.
  | { role: "user"; text: string; anchor: string | null }
  | { role: "assistant"; response: ChatResponse; status: ChangeStatus | null }
  | { role: "error"; text: string };

type HistoryTurn = { role: "user" | "assistant"; content: string };

// Recent turns sent with each message so follow-ups ("ok lower it") can be
// resolved; the backend uses them purely as context for routing. The whole
// conversation is also saved server-side and reloaded on open.
const HISTORY_TURNS = 10;
const MAX_TURN_CHARS = 2000; // matches the backend's ChatTurn limit

// Suggested prompts: one click sends them into the same chat (retrieved,
// verified and cited like a typed message). Anchored to an exercise: ask
// about or change its values - load prompts only for a %1RM load. Not
// anchored: general research questions.
const GENERAL_PROMPTS: Record<string, string[]> = {
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

function anchoredPrompts(hasPercentLoad: boolean): { ask: string[]; change: string[] } {
  return {
    ask: [
      "Why this many sets?",
      "Why this rep range?",
      "Why this effort (RIR)?",
      ...(hasPercentLoad ? ["Why this load?"] : []),
    ],
    change: [
      "Add a set",
      "Remove a set",
      "Take it closer to failure",
      "Leave more reps in reserve",
      ...(hasPercentLoad ? ["Make it heavier", "Make it lighter"] : []),
      "Swap this exercise",
    ],
  };
}

type StreamEvent =
  | { type: "stage"; label: string }
  | { type: "result"; response: ChatResponse }
  | { type: "error"; status: number; detail: string };

// Reads the chat stream (one JSON object per line), reporting each stage,
// and returns the response - or throws with the server's error.
async function readStream(body: ReadableStream<Uint8Array>, onStage: (label: string) => void): Promise<ChatResponse> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffered += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffered.split("\n");
    buffered = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as StreamEvent;
      if (event.type === "stage") onStage(event.label);
      else if (event.type === "result") return event.response;
      else throw new Error(event.detail);
    }
    if (done) throw new Error("The answer was cut off - please try again.");
  }
}

function describe(p: WeeklyPrescription): string {
  return [`${p.sets} sets`, `${p.reps || "n/a"} reps`, ...(p.load ? [p.load] : []), p.rir || "effort n/a"].join(", ");
}

function summarizeResponse(r: ChatResponse): string {
  const p = r.prescription;
  const values = p ? describe(p) : "";
  if (r.mode === "adjust_prescription" && r.swap) {
    return r.swap.pending ? `Previewed swapping ${r.swap.old_name} for ${r.swap.new_name}.` : swapSummary(r.swap);
  }
  if (r.mode === "adjust_prescription") {
    return r.answer ? `Kept as is: ${r.answer}` : `Updated it to ${values}.${r.grounding_note ? ` ${r.grounding_note}` : ""}`;
  }
  if (r.mode === "discuss_prescription") return `${r.answer ?? ""} (Current: ${values}.)`;
  return r.answer ?? "";
}

function toHistory(turns: ChatTurn[]): HistoryTurn[] {
  return turns
    .flatMap((t): HistoryTurn[] => {
      if (t.role === "user") return [{ role: "user", content: t.anchor ? `[about ${t.anchor}] ${t.text}` : t.text }];
      if (t.role === "assistant") return [{ role: "assistant", content: summarizeResponse(t.response) }];
      return []; // failed requests carry nothing to resolve against
    })
    .slice(-HISTORY_TURNS)
    .map((t) => ({ ...t, content: t.content.slice(0, MAX_TURN_CHARS) }));
}

// The composer grows with its text up to this height, then scrolls.
const COMPOSER_MAX_HEIGHT = 200;

export default function ChatWindow({
  fieldId,
  anchorLabel,
  thisWeekOnly = false,
  anchorHasPercentLoad = false,
  goal = null,
  onClearAnchor,
  onPrescriptionUpdated,
}: {
  // Structural context (phase6_chat_routing_concepts.txt section 2): set by
  // clicking "Ask" on a rendered prescription in ProgramTree, not typed in
  // by hand - the parent workspace owns this so the anchor survives across
  // messages in the same thread and can show a real label, not a bare id.
  fieldId: number | null;
  anchorLabel: string | null;
  // Anchored to one picked week of a hypertrophy exercise: a change applies
  // to that week only (the backend otherwise applies it to every week).
  thisWeekOnly?: boolean;
  // For suggested prompts: the anchored value has a %1RM load, and the
  // selected program's goal (general questions differ by goal).
  anchorHasPercentLoad?: boolean;
  goal?: string | null;
  onClearAnchor: () => void;
  // Lets the program view refetch after an adjust changes a stored value.
  onPrescriptionUpdated?: () => void;
}) {
  const { getToken } = useAuth();
  const dialogs = useDialogs();
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  // What the server is doing right now ("Checking 9 statements..."), from
  // the streamed stages.
  const [stage, setStage] = useState<string | null>(null);
  const messageInputRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  // Saved history, loaded once on open (each change with its current state,
  // so Undo / Confirm buttons are right after a reload).
  useEffect(() => {
    let stale = false;
    (async () => {
      try {
        const saved = await call<{ role: string; content: Record<string, unknown>; change_status: ChangeStatus | null }[]>(
          "/chat/history", "GET",
        );
        if (stale) return;
        setTurns(saved.map((t): ChatTurn =>
          t.role === "user"
            ? { role: "user", text: String(t.content.text ?? ""), anchor: (t.content.anchor as string | null) ?? null }
            : { role: "assistant", response: t.content as unknown as ChatResponse, status: t.change_status },
        ));
      } catch {
        // No saved history (or it couldn't load): start empty.
      }
    })();
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function call<T>(path: string, method: string, body?: unknown): Promise<T> {
    const token = await getToken();
    const res = await fetch(`${API_URL}${path}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.detail ?? `Request failed: ${res.status}`);
    }
    return (res.status === 204 ? null : await res.json()) as T;
  }

  function updateTurn(index: number, update: (turn: ChatTurn & { role: "assistant" }) => ChatTurn) {
    setTurns((prev) => prev.map((t, i) => (i === index && t.role === "assistant" ? update(t) : t)));
  }

  async function changeAction(index: number, action: "undo" | "confirm" | "cancel", changeId: number) {
    try {
      if (action === "undo") {
        await call(`/changes/${changeId}/undo`, "POST");
        updateTurn(index, (t) => ({ ...t, status: "undone" }));
      } else if (action === "confirm") {
        const applied = await call<SwapResult>(`/changes/${changeId}/confirm`, "POST");
        updateTurn(index, (t) => ({ ...t, status: "applied", response: { ...t.response, swap: applied } }));
      } else {
        await call(`/changes/${changeId}`, "DELETE");
        updateTurn(index, (t) => ({ ...t, status: "cancelled" }));
      }
      if (action !== "cancel") onPrescriptionUpdated?.();
    } catch (err) {
      setTurns((prev) => [...prev, { role: "error", text: err instanceof Error ? err.message : String(err) }]);
    }
  }

  async function clearHistory() {
    const ok = await dialogs.confirm({
      title: "Clear the chat history?",
      body: "The saved conversation is deleted. Changes you made stay in your programs.",
      confirmLabel: "Clear history",
      danger: true,
    });
    if (!ok) return;
    try {
      await call("/chat/history", "DELETE");
      setTurns([]);
    } catch (err) {
      setTurns((prev) => [...prev, { role: "error", text: err instanceof Error ? err.message : String(err) }]);
    }
  }

  // Keep the newest message in view.
  useEffect(() => {
    const box = messagesRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [turns, sending]);

  // Phones: the on-screen keyboard covers the bottom of the page rather than
  // shrinking it, so the composer could end up hidden behind it. While the
  // composer has focus, scroll just enough to keep it above the keyboard
  // (the visual viewport is the part of the page left visible).
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const revealComposer = () => {
      const composer = composerRef.current;
      if (!composer || document.activeElement !== messageInputRef.current) return;
      const hidden = composer.getBoundingClientRect().bottom - (viewport.offsetTop + viewport.height) + 12;
      if (hidden > 0) window.scrollBy({ top: hidden, behavior: "smooth" });
    };
    viewport.addEventListener("resize", revealComposer);
    return () => viewport.removeEventListener("resize", revealComposer);
  }, []);

  useEffect(() => {
    if (fieldId === null) return;
    // Focus without the browser's own jump, then glide the chat into view
    // where it sits below the program (narrow screens); wide screens keep
    // it beside the program already.
    messageInputRef.current?.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 1023px)").matches) {
      composerRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    }
  }, [fieldId]);

  // Grow the composer with its text (also shrinks it back after sending);
  // past the max height it scrolls instead.
  useLayoutEffect(() => {
    const box = messageInputRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, COMPOSER_MAX_HEIGHT)}px`;
    box.style.overflowY = box.scrollHeight > COMPOSER_MAX_HEIGHT ? "auto" : "hidden";
  }, [message]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    await send(message);
  }

  // Enter sends, Shift+Enter adds a line (not while an IME is composing).
  function handleComposerKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(message);
    }
  }

  async function send(text: string) {
    if (!text.trim() || sending) return;
    setSending(true);

    const sentMessage = text;
    const sentAnchor = fieldId !== null ? (anchorLabel ?? `prescription #${fieldId}`) : null;
    const history = toHistory(turns); // the conversation BEFORE this message
    setTurns((prev) => [...prev, { role: "user", text: sentMessage, anchor: sentAnchor }]);
    setMessage("");

    try {
      const token = await getToken();
      // Streamed: stage lines while it works, then the result (see
      // stream_chat_message in backend/app/routers/chat.py).
      const res = await fetch(`${API_URL}/chat/message/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: sentMessage,
          field_id: fieldId,
          history,
          anchor_label: sentAnchor,
          this_week_only: fieldId !== null && thisWeekOnly,
        }),
      });

      if (!res.ok || !res.body) {
        const detail = await res.text();
        setTurns((prev) => [
          ...prev,
          { role: "error", text: `Request failed: ${res.status} ${detail}` },
        ]);
        return;
      }

      const data = await readStream(res.body, setStage);
      const status: ChangeStatus | null = data.swap?.pending ? "pending" : changeIdOf(data) ? "applied" : null;
      setTurns((prev) => [...prev, { role: "assistant", response: data, status }]);
      if (data.mode === "adjust_prescription") onPrescriptionUpdated?.();
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        { role: "error", text: err instanceof Error ? err.message : String(err) },
      ]);
    } finally {
      setSending(false);
      setStage(null);
    }
  }

  // Applies one rebalance option; the server recalculates it from the stored
  // values. Returns the updated values, or throws with the server's reason.
  async function applyRebalance(rebalance: Rebalance, field: RebalanceField): Promise<RebalanceResult> {
    const result = await call<RebalanceResult>(
      `/weekly-prescriptions/${rebalance.prescription_id}/rebalance`, "POST",
      { changed_field: rebalance.changed_field, apply_field: field },
    );
    onPrescriptionUpdated?.();
    return result;
  }

  async function undoChange(changeId: number) {
    await call(`/changes/${changeId}/undo`, "POST");
    onPrescriptionUpdated?.();
  }

  return (
    <section className="card flex h-full flex-col overflow-hidden" aria-label="Evidence assistant">
      <header className="flex items-center gap-3 border-b border-line px-4 py-3.5">
        <Image
          src="/chat-icon.jpg"
          alt=""
          width={32}
          height={32}
          className="size-8 shrink-0 rounded-lg object-cover ring-1 ring-line-strong"
        />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Evidence assistant</h2>
          <p className="truncate text-xs text-fg-subtle">Answers and changes cite the papers</p>
        </div>
        {turns.length > 0 && (
          <button type="button" onClick={clearHistory} className="icon-btn" aria-label="Clear chat history" title="Clear chat history">
            <Trash className="size-4" />
          </button>
        )}
      </header>

      <div
        ref={messagesRef}
        className="scroll-thin flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
        aria-live="polite"
      >
        {turns.length === 0 && !sending && (
          <div className="m-auto flex max-w-sm flex-col items-center gap-3 py-6 text-center">
            <span className="grid size-11 place-items-center rounded-2xl bg-evidence-soft text-evidence">
              <Book className="size-5" />
            </span>
            <p className="font-medium">Ask the evidence</p>
            <p className="text-sm leading-relaxed text-fg-muted">
              Press <span className="font-medium text-fg">Ask</span>{" "}on any prescription, or ask below. Answers link
              their studies.
            </p>
            <div className="mt-3">
              <SuggestedPrompts
                anchored={fieldId !== null}
                hasPercentLoad={anchorHasPercentLoad}
                goal={goal}
                disabled={sending}
                onPick={send}
                centered
              />
            </div>
          </div>
        )}
        {turns.map((turn, i) => {
          if (turn.role === "user") {
            return (
              <div key={i} className="flex max-w-[85%] flex-col items-end gap-1 self-end">
                {turn.anchor && (
                  <span className="flex items-center gap-1 text-[11px] text-fg-subtle">
                    <Message className="size-3" />
                    {turn.anchor}
                  </span>
                )}
                <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm text-accent-fg">
                  {turn.text}
                </div>
              </div>
            );
          }
          if (turn.role === "error") {
            return (
              <div key={i} className="max-w-[92%] self-start rounded-2xl bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
                {turn.text}
              </div>
            );
          }
          const changeId = changeIdOf(turn.response);
          return (
            <ChatTurnResult
              key={i}
              response={turn.response}
              status={turn.status}
              onChange={changeId === null ? undefined : (action) => changeAction(i, action, changeId)}
              onApplyRebalance={applyRebalance}
              onUndoRebalance={undoChange}
            />
          );
        })}
        {sending && (
          <div className="flex items-center gap-2.5 self-start rounded-2xl rounded-bl-md bg-surface-2 px-3.5 py-2.5 text-sm text-fg-muted">
            <span className="flex gap-1" aria-hidden="true">
              {[0, 1, 2].map((d) => (
                <span
                  key={d}
                  className="size-1.5 rounded-full bg-fg-muted animate-[typing_1.2s_ease-in-out_infinite]"
                  style={{ animationDelay: `${d * 160}ms` }}
                />
              ))}
            </span>
            <span key={stage ?? ""} className="animate-in">
              {stage ? `${stage}...` : "Reading the research..."}
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2.5 border-t border-line bg-surface px-3 pb-3 pt-3">
        {fieldId !== null && (
          <div className="animate-in flex items-center gap-2 rounded-xl bg-accent-soft py-1.5 pe-1.5 ps-3 text-sm">
            <Message className="size-3.5 shrink-0 text-accent-text" />
            <span className="min-w-0 flex-1 truncate">
              <span className="text-fg-muted">Asking about </span>
              <span className="font-medium text-fg">{anchorLabel ?? `prescription #${fieldId}`}</span>
            </span>
            <button type="button" onClick={onClearAnchor} className="icon-btn size-7" aria-label="Stop asking about this exercise">
              <Close className="size-3.5" />
            </button>
          </div>
        )}

        {/* With a conversation on screen the suggestions fold behind a
            toggle (an empty chat shows them in the message area). */}
        {turns.length > 0 && (
          <div className="flex flex-col gap-2">
            <button
              type="button"
              onClick={() => setShowSuggestions((v) => !v)}
              aria-expanded={showSuggestions}
              className="inline-flex items-center gap-1 self-start rounded-md px-1 text-xs font-medium text-fg-subtle hover:text-fg"
            >
              <Sparkles className="size-3.5" />
              Suggestions{fieldId !== null ? " for this exercise" : ""}
              <ChevronDown className={`size-3.5 transition-transform duration-200 ${showSuggestions ? "rotate-180" : ""}`} />
            </button>
            {showSuggestions && (
              <div className="animate-in scroll-thin max-h-44 overflow-y-auto px-1">
                <SuggestedPrompts
                  anchored={fieldId !== null}
                  hasPercentLoad={anchorHasPercentLoad}
                  goal={goal}
                  disabled={sending}
                  onPick={(p) => {
                    setShowSuggestions(false);
                    void send(p);
                  }}
                />
              </div>
            )}
          </div>
        )}

        <form
          ref={composerRef}
          onSubmit={handleSend}
          className="flex items-end gap-2 rounded-2xl border border-line-control bg-surface-2 p-1.5 ps-3.5 transition-[border-color,box-shadow] duration-150 focus-within:border-[var(--accent-ring)] focus-within:shadow-[0_0_0_3px_var(--accent-soft)]"
        >
          <textarea
            ref={messageInputRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleComposerKey}
            rows={1}
            aria-label="Message"
            placeholder={
              fieldId !== null
                ? 'e.g. "make it 10-12 reps" or "why 3 sets?"'
                : "Ask the evidence..."
            }
            className="scroll-thin min-h-9 flex-1 resize-none bg-transparent py-1.5 text-base leading-6 text-fg outline-none placeholder:text-fg-subtle sm:py-2 sm:text-sm sm:leading-5"
          />
          <button
            type="submit"
            disabled={sending || !message.trim()}
            aria-label="Send"
            className="btn btn-primary size-9 shrink-0 rounded-xl p-0"
          >
            {sending ? <Spinner className="size-4" /> : <ArrowUp className="size-4" />}
          </button>
        </form>
        <p className="hidden px-1 text-[11px] text-fg-subtle sm:block">
          Enter to send · Shift+Enter for a new line
        </p>
      </div>
    </section>
  );
}

function SuggestedPrompts({
  anchored,
  hasPercentLoad,
  goal,
  disabled,
  onPick,
  centered = false,
}: {
  anchored: boolean;
  hasPercentLoad: boolean;
  goal: string | null;
  disabled: boolean;
  onPick: (prompt: string) => void;
  centered?: boolean;
}) {
  const groups: [string, string[]][] = anchored
    ? Object.entries(anchoredPrompts(hasPercentLoad)).map(([k, v]) => [k === "ask" ? "Ask" : "Change", v])
    : [["Try asking", GENERAL_PROMPTS[goal ?? ""] ?? GENERAL_PROMPTS.hypertrophy]];
  // Every prompt visible, wrapped, under its group's label.
  return (
    <div className={`flex flex-col gap-3 ${centered ? "items-center" : ""}`}>
      {groups.map(([label, prompts]) => (
        <div key={label} className={`flex flex-col gap-1.5 ${centered ? "items-center" : ""}`}>
          <span className="text-[11px] font-medium uppercase tracking-wide text-fg-subtle">{label}</span>
          <div className={`flex flex-wrap gap-1.5 ${centered ? "justify-center" : ""}`}>
            {prompts.map((p) => (
              <button
                key={p}
                type="button"
                disabled={disabled}
                onClick={() => onPick(p)}
                className="min-h-7 rounded-full border border-line bg-surface-2 px-2.5 py-1 text-start text-xs text-fg-muted transition-[background-color,border-color,color,transform] duration-150 hover:border-accent-ring/55 hover:bg-accent-soft hover:text-accent-text active:scale-[0.97] disabled:opacity-50"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

type ChangeAction = "undo" | "confirm" | "cancel";

// Undo for an applied change; Confirm / Cancel for a swap preview.
function ChangeControls({ status, onChange }: { status: ChangeStatus | null; onChange?: (a: ChangeAction) => void }) {
  const [busy, setBusy] = useState(false);
  if (!onChange || status === null) return null;
  const act = async (a: ChangeAction) => {
    setBusy(true);
    try {
      await onChange(a);
    } finally {
      setBusy(false);
    }
  };
  if (status === "pending") {
    return (
      <div className="mt-3 flex gap-2">
        <button type="button" disabled={busy} onClick={() => act("confirm")} className="btn btn-primary btn-sm">
          <Check className="size-3.5" />
          Confirm swap
        </button>
        <button type="button" disabled={busy} onClick={() => act("cancel")} className="btn btn-ghost btn-sm">
          Cancel
        </button>
      </div>
    );
  }
  if (status === "applied") {
    return (
      <button type="button" disabled={busy} onClick={() => act("undo")} className="btn btn-secondary btn-sm mt-3">
        <Undo className="size-3.5" />
        Undo
      </button>
    );
  }
  return (
    <p className="mt-2.5 text-xs text-fg-subtle">{status === "undone" ? "Undone." : "Cancelled - nothing changed."}</p>
  );
}

// The prescription's values as compact chips.
function ValueChips({ p }: { p: WeeklyPrescription }) {
  const values = [`${p.sets} sets`, `${p.reps || "n/a"} reps`, ...(p.load ? [p.load] : []), p.rir || "effort n/a"];
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((v) => (
        <span key={v} className="rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs font-medium tabular-nums text-fg">
          {v}
        </span>
      ))}
    </div>
  );
}

const assistantBubble = "self-start max-w-[94%] rounded-2xl rounded-bl-md bg-surface-2 px-3.5 py-3 text-sm leading-relaxed";

function ChatTurnResult({
  response,
  status,
  onChange,
  onApplyRebalance,
  onUndoRebalance,
}: {
  response: ChatResponse;
  status: ChangeStatus | null;
  onChange?: (action: ChangeAction) => void;
  onApplyRebalance: (rebalance: Rebalance, field: RebalanceField) => Promise<RebalanceResult>;
  onUndoRebalance: (changeId: number) => Promise<void>;
}) {
  if (response.mode === "adjust_prescription" && response.swap) {
    const { old_name, new_name, changes } = response.swap;
    const preview = status === "pending" || status === "cancelled";
    const others = changes.filter((c) => !c.includes(" - the new exercise:"));
    const own = changes.filter((c) => c.includes(" - the new exercise:"));
    return (
      <div className={assistantBubble}>
        <p className="font-medium">
          <span className="text-fg-subtle">{preview ? "Swap " : "Swapped "}</span>
          {old_name}
          <span className="text-fg-subtle"> → </span>
          {new_name}
          {preview && "?"}
        </p>
        {own.length > 0 && (
          <ul className="mt-1.5 flex flex-col gap-0.5 text-xs text-fg-muted">
            {own.map((c) => <li key={c}>{c.replace(/^.* - the new exercise: /, "")}</li>)}
          </ul>
        )}
        {others.length > 0 ? (
          <div className="mt-2.5 rounded-xl bg-warn-soft px-3 py-2 text-xs text-warn">
            <p className="mb-1 font-medium">{preview ? "This would also change" : "Also changed"}</p>
            <ul className="flex list-disc flex-col gap-0.5 ps-4">
              {others.map((c) => <li key={c}>{c}</li>)}
            </ul>
          </div>
        ) : (
          <p className="mt-2 text-xs text-fg-subtle">
            {preview ? "Nothing else in the block would change." : "Nothing else in the block changed."}
          </p>
        )}
        <ChangeControls status={status} onChange={onChange} />
      </div>
    );
  }

  if (response.mode === "adjust_prescription" && response.prescription) {
    const p = response.prescription;
    return (
      <div className={assistantBubble}>
        {/* An answer on an adjust means the requested direction couldn't be
            honored and the value was kept - see chat.py _handle_adjust. */}
        <p className="mb-2 flex items-center gap-1.5 font-medium">
          {response.answer ? (
            "Kept as is"
          ) : (
            <>
              <Check className="size-4 text-evidence" />
              Updated
            </>
          )}
        </p>
        {response.answer && <p className="mb-2 text-fg-muted">{response.answer}</p>}
        <ValueChips p={p} />
        {response.answer ? null : response.grounding_note ? (
          <CaveatNote className="mt-2 text-xs">{response.grounding_note}</CaveatNote>
        ) : (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-evidence">
            <Book className="size-3.5" />
            Fully supported by cited research.
          </p>
        )}
        <ChangeControls status={status} onChange={onChange} />
        {response.rebalance && status !== "undone" && (
          <RebalancePrompt rebalance={response.rebalance} onApply={onApplyRebalance} onUndo={onUndoRebalance} />
        )}
      </div>
    );
  }

  if (response.mode === "discuss_prescription" && response.prescription) {
    const p = response.prescription;
    return (
      <div className={assistantBubble}>
        <p>{response.answer}</p>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-fg-subtle">Current</span>
          <ValueChips p={p} />
        </div>
        {response.grounding_note && <CaveatNote className="mt-2 text-xs">{response.grounding_note}</CaveatNote>}
        <CitationList citations={response.citations} />
      </div>
    );
  }

  return (
    <div className={assistantBubble}>
      <AnswerText answer={response.answer ?? ""} />
      {response.grounding_note && <CaveatNote className="mt-2 text-xs">{response.grounding_note}</CaveatNote>}
      <CitationList citations={response.citations} />
    </div>
  );
}

// "Rebalance?": the change left reps, load and RIR not fitting together, so
// offer the two table-calculated fixes, or keeping it as is.
type RebalanceResult = { prescription: WeeklyPrescription; change_id: number };

function RebalancePrompt({
  rebalance,
  onApply,
  onUndo,
}: {
  rebalance: Rebalance;
  onApply: (rebalance: Rebalance, field: RebalanceField) => Promise<RebalanceResult>;
  onUndo: (changeId: number) => Promise<void>;
}) {
  const [state, setState] = useState<
    | { kind: "open" }
    | { kind: "busy" }
    | { kind: "done"; text: string; changeId: number }
    | { kind: "kept" }
    | { kind: "undone" }
    | { kind: "error"; text: string }
  >({ kind: "open" });

  async function choose(field: RebalanceField) {
    setState({ kind: "busy" });
    try {
      const result = await onApply(rebalance, field);
      setState({ kind: "done", text: describe(result.prescription), changeId: result.change_id });
    } catch (err) {
      setState({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    }
  }

  async function undo(changeId: number) {
    try {
      await onUndo(changeId);
      setState({ kind: "undone" });
    } catch (err) {
      setState({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-line bg-surface p-3 text-xs">
      <CaveatNote>{rebalance.message}</CaveatNote>
      {state.kind === "done" ? (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-evidence">
          <Check className="size-3.5" />
          Rebalanced: {state.text}.
          <button type="button" onClick={() => undo(state.changeId)} className="btn btn-secondary btn-sm h-7">
            <Undo className="size-3.5" />
            Undo
          </button>
        </p>
      ) : state.kind === "undone" ? (
        <p className="mt-2 text-fg-subtle">Rebalance undone.</p>
      ) : state.kind === "kept" ? (
        <p className="mt-2 text-fg-subtle">Kept as is.</p>
      ) : (
        <>
          <p className="mb-1.5 mt-2.5 font-medium text-fg">Rebalance?</p>
          <div className="flex flex-wrap gap-1.5">
            {rebalance.options.map((o) => (
              <button
                key={o.field}
                type="button"
                disabled={state.kind === "busy"}
                onClick={() => choose(o.field)}
                className="btn btn-secondary btn-sm h-7"
              >
                {o.label}
              </button>
            ))}
            <button
              type="button"
              disabled={state.kind === "busy"}
              onClick={() => setState({ kind: "kept" })}
              className="btn btn-ghost btn-sm h-7"
            >
              Keep as is
            </button>
          </div>
          {state.kind === "error" && <p className="mt-1.5 text-danger">{state.text}</p>}
        </>
      )}
    </div>
  );
}

// A general answer leads with its practical summary; the individual
// findings behind it follow after a blank line and start folded away.
function AnswerText({ answer }: { answer: string }) {
  const split = answer.indexOf("\n\n");
  if (split === -1) return <p className="whitespace-pre-line">{answer}</p>;
  return (
    <>
      <p className="whitespace-pre-line">{answer.slice(0, split)}</p>
      <details className="group mt-2.5">
        <summary className="inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-accent-text select-none">
          <ChevronRight className="size-3.5 transition-transform duration-200 group-open:rotate-90" />
          Show the evidence
        </summary>
        <p className="animate-in mt-2 whitespace-pre-line border-s-2 border-line-strong ps-3 text-fg-muted">
          {answer.slice(split + 2)}
        </p>
      </details>
    </>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  // Folded by default: the answer and its evidence come first, the source
  // list opens on demand.
  return (
    <details className="group/sources mt-3 border-t border-line pt-2.5">
      <summary className="inline-flex cursor-pointer items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-subtle transition-colors duration-150 select-none hover:text-fg">
        <ChevronRight className="size-3 transition-transform duration-200 group-open/sources:rotate-90" />
        <Book className="size-3 text-evidence" />
        {citations.length} source{citations.length === 1 ? "" : "s"}
      </summary>
      <ol className="animate-in mt-1.5 flex flex-col gap-1.5">
        {citations.map((c, i) => (
          <li key={i} title={c.snippet} className="flex gap-2 text-xs text-fg-muted">
            <span className="font-mono text-fg-subtle">{i + 1}</span>
            <span className="min-w-0">
              {c.title}
              {c.field && (
                <span className="ms-1.5 rounded bg-surface-3 px-1 py-px text-[11px] text-fg-subtle">
                  {c.field === "rir" ? "effort" : c.field}
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}
