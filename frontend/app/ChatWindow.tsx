"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef, useState } from "react";
import { API_URL } from "./apiUrl";
import { swapSummary } from "./ProgramTree";
import type { WeeklyPrescription } from "./types";

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
  // A swap: the old and new exercise and everything else it changed.
  swap: { old_name: string; new_name: string; changes: string[] } | null;
};

type ChatTurn =
  // anchor: which prescription the message was about when sent, so the
  // history stays unambiguous if the user re-anchors mid-conversation.
  | { role: "user"; text: string; anchor: string | null }
  | { role: "assistant"; response: ChatResponse }
  | { role: "error"; text: string };

type HistoryTurn = { role: "user" | "assistant"; content: string };

// Recent turns sent with each message so follow-ups ("ok lower it") can be
// resolved. Session-only: history lives in this component's state and is
// gone on refresh. The backend uses it purely as context for routing.
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

function describe(p: WeeklyPrescription): string {
  return [`${p.sets} sets`, `${p.reps || "n/a"} reps`, ...(p.load ? [p.load] : []), p.rir || "effort n/a"].join(", ");
}

function summarizeResponse(r: ChatResponse): string {
  const p = r.prescription;
  const values = p ? describe(p) : "";
  if (r.mode === "adjust_prescription" && r.swap) return swapSummary(r.swap);
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

export default function ChatWindow({
  fieldId,
  anchorLabel,
  anchorHasPercentLoad = false,
  goal = null,
  onClearAnchor,
  onPrescriptionUpdated,
}: {
  // Structural context (phase6_chat_routing_concepts.txt section 2): set by
  // clicking "ask about this" on a rendered prescription in ProgramTree, not
  // typed in by hand - the parent workspace owns this so the anchor survives
  // across messages in the same thread and can show a real label, not just
  // a bare id.
  fieldId: number | null;
  anchorLabel: string | null;
  // For suggested prompts: the anchored value has a %1RM load, and the
  // selected program's goal (general questions differ by goal).
  anchorHasPercentLoad?: boolean;
  goal?: string | null;
  onClearAnchor: () => void;
  // Lets the program view refetch after an adjust changes a stored value.
  onPrescriptionUpdated?: () => void;
}) {
  const { getToken } = useAuth();
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const messageInputRef = useRef<HTMLInputElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  // Keep the newest message in view.
  useEffect(() => {
    const box = messagesRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [turns, sending]);

  useEffect(() => {
    if (fieldId !== null) messageInputRef.current?.focus();
  }, [fieldId]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    await send(message);
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
      const res = await fetch(`${API_URL}/chat/message`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: sentMessage,
          field_id: fieldId,
          history,
        }),
      });

      if (!res.ok) {
        const detail = await res.text();
        setTurns((prev) => [
          ...prev,
          { role: "error", text: `Request failed: ${res.status} ${detail}` },
        ]);
        return;
      }

      const data: ChatResponse = await res.json();
      setTurns((prev) => [...prev, { role: "assistant", response: data }]);
      if (data.mode === "adjust_prescription") onPrescriptionUpdated?.();
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        { role: "error", text: err instanceof Error ? err.message : String(err) },
      ]);
    } finally {
      setSending(false);
    }
  }

  // Applies one rebalance option; the server recalculates it from the stored
  // values. Returns the updated values, or throws with the server's reason.
  async function applyRebalance(rebalance: Rebalance, field: RebalanceField): Promise<WeeklyPrescription> {
    const token = await getToken();
    const res = await fetch(`${API_URL}/weekly-prescriptions/${rebalance.prescription_id}/rebalance`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ changed_field: rebalance.changed_field, apply_field: field }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.detail ?? `Request failed: ${res.status}`);
    }
    onPrescriptionUpdated?.();
    return res.json();
  }

  return (
    <div className="flex flex-col gap-4 w-full h-full">
      {fieldId !== null ? (
        <div className="flex items-center justify-between gap-2 border rounded px-3 py-2 text-sm bg-indigo-50 dark:bg-indigo-950">
          <span>
            Asking about: <span className="font-medium">{anchorLabel ?? `prescription #${fieldId}`}</span>
          </span>
          <button type="button" onClick={onClearAnchor} className="text-xs underline shrink-0">
            clear
          </button>
        </div>
      ) : (
        <p className="text-xs text-zinc-500">
          Not anchored to a specific exercise - click &quot;ask / adjust&quot; on a
          prescription above to ask about it or change it, or just ask a general
          research question below.
        </p>
      )}

      {/* Stacked (narrow): a fixed-height box. Side panel (wide): fills the
          panel's remaining height, so only the messages scroll. */}
      <div
        ref={messagesRef}
        className="flex flex-col gap-3 min-h-40 max-h-[28rem] lg:max-h-none lg:flex-1 overflow-y-auto border rounded p-4 bg-zinc-50 dark:bg-zinc-900"
      >
        {turns.length === 0 && (
          <p className="text-sm text-zinc-500">
            Click &quot;ask / adjust&quot; on a prescription above, then ask about
            it (&quot;why this load?&quot;) or change it (&quot;make it 4 sets&quot;,
            &quot;add more volume&quot;, &quot;go lighter&quot;). Or ask a general
            research question.
          </p>
        )}
        {turns.map((turn, i) => {
          if (turn.role === "user") {
            return (
              <div
                key={i}
                className="self-end bg-black text-white dark:bg-white dark:text-black rounded px-3 py-2 max-w-[85%] text-sm"
              >
                {turn.text}
              </div>
            );
          }
          if (turn.role === "error") {
            return (
              <div key={i} className="self-start text-red-600 text-sm">
                {turn.text}
              </div>
            );
          }
          return (
            <ChatTurnResult key={i} response={turn.response} onApplyRebalance={applyRebalance} />
          );
        })}
      </div>

      <SuggestedPrompts
        anchored={fieldId !== null}
        hasPercentLoad={anchorHasPercentLoad}
        goal={goal}
        disabled={sending}
        onPick={send}
      />

      <form onSubmit={handleSend} className="flex gap-2">
        <input
          ref={messageInputRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={
            fieldId !== null
              ? 'e.g. "make it 10-12 reps", "take it closer to failure", "why 3 sets?"'
              : "Ask a general research question..."
          }
          className="border rounded px-3 py-2 flex-1"
          required
        />
        <button
          type="submit"
          disabled={sending}
          className="rounded bg-black text-white px-4 py-2 disabled:opacity-50 dark:bg-white dark:text-black"
        >
          {sending ? "Sending..." : "Send"}
        </button>
      </form>
    </div>
  );
}

function SuggestedPrompts({
  anchored,
  hasPercentLoad,
  goal,
  disabled,
  onPick,
}: {
  anchored: boolean;
  hasPercentLoad: boolean;
  goal: string | null;
  disabled: boolean;
  onPick: (prompt: string) => void;
}) {
  const groups: [string, string[]][] = anchored
    ? Object.entries(anchoredPrompts(hasPercentLoad)).map(([k, v]) => [k === "ask" ? "Ask" : "Change", v])
    : [["Ask the research", GENERAL_PROMPTS[goal ?? ""] ?? GENERAL_PROMPTS.hypertrophy]];
  return (
    <div className="flex flex-col gap-1 text-xs">
      {groups.map(([label, prompts]) => (
        <div key={label} className="flex flex-wrap items-center gap-1">
          <span className="text-zinc-500 mr-1">{label}:</span>
          {prompts.map((p) => (
            <button
              key={p}
              type="button"
              disabled={disabled}
              onClick={() => onPick(p)}
              className="border rounded-full px-2 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50"
            >
              {p}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

function ChatTurnResult({
  response,
  onApplyRebalance,
}: {
  response: ChatResponse;
  onApplyRebalance: (rebalance: Rebalance, field: RebalanceField) => Promise<WeeklyPrescription>;
}) {
  if (response.mode === "adjust_prescription" && response.swap) {
    const { old_name, new_name, changes } = response.swap;
    const others = changes.filter((c) => !c.includes(" - the new exercise:"));
    const own = changes.filter((c) => c.includes(" - the new exercise:"));
    return (
      <div className="self-start bg-white dark:bg-zinc-800 border rounded px-3 py-2 max-w-[90%] text-sm">
        <p className="font-medium">
          Swapped {old_name} for {new_name}
        </p>
        {response.prescription && <p>{describe(response.prescription)}</p>}
        {own.length > 0 && (
          <ul className="text-xs text-zinc-500 mt-1 list-disc list-inside">
            {own.map((c) => <li key={c}>{c.replace(/^.* - the new exercise: /, "")}</li>)}
          </ul>
        )}
        <p className="text-xs mt-2 font-medium">{others.length > 0 ? "Also changed:" : "Nothing else in the block changed."}</p>
        {others.length > 0 && (
          <ul className="text-xs text-amber-700 dark:text-amber-500 list-disc list-inside">
            {others.map((c) => <li key={c}>{c}</li>)}
          </ul>
        )}
      </div>
    );
  }

  if (response.mode === "adjust_prescription" && response.prescription) {
    const p = response.prescription;
    return (
      <div className="self-start bg-white dark:bg-zinc-800 border rounded px-3 py-2 max-w-[90%] text-sm">
        {/* An answer on an adjust means the requested direction couldn't be
            honored and the value was kept - see chat.py _handle_adjust. */}
        <p className="font-medium">{response.answer ? "Kept as is" : "Updated"}</p>
        {response.answer && <p>{response.answer}</p>}
        <p className={response.answer ? "text-zinc-500 text-xs mt-1" : ""}>
          {describe(p)}
        </p>
        {response.answer ? null : response.grounding_note ? (
          <p className="text-amber-600 text-xs mt-1">{response.grounding_note}</p>
        ) : (
          <p className="text-green-700 dark:text-green-500 text-xs mt-1">
            Fully supported by cited research.
          </p>
        )}
        {response.rebalance && <RebalancePrompt rebalance={response.rebalance} onApply={onApplyRebalance} />}
      </div>
    );
  }

  if (response.mode === "discuss_prescription" && response.prescription) {
    const p = response.prescription;
    return (
      <div className="self-start bg-white dark:bg-zinc-800 border rounded px-3 py-2 max-w-[90%] text-sm">
        <p>{response.answer}</p>
        <p className="text-zinc-500 text-xs mt-2">
          Current: {describe(p)}.
        </p>
        {response.grounding_note && (
          <p className="text-amber-600 text-xs mt-1">{response.grounding_note}</p>
        )}
        <CitationList citations={response.citations} />
      </div>
    );
  }

  return (
    <div className="self-start bg-white dark:bg-zinc-800 border rounded px-3 py-2 max-w-[90%] text-sm">
      <AnswerText answer={response.answer ?? ""} />
      {response.grounding_note && (
        <p className="text-amber-600 text-xs mt-1">{response.grounding_note}</p>
      )}
      <CitationList citations={response.citations} />
    </div>
  );
}

// "Rebalance?": the change left reps, load and RIR not fitting together, so
// offer the two table-calculated fixes, or keeping it as is.
function RebalancePrompt({
  rebalance,
  onApply,
}: {
  rebalance: Rebalance;
  onApply: (rebalance: Rebalance, field: RebalanceField) => Promise<WeeklyPrescription>;
}) {
  const [state, setState] = useState<
    { kind: "open" } | { kind: "busy" } | { kind: "done"; text: string } | { kind: "kept" } | { kind: "error"; text: string }
  >({ kind: "open" });

  async function choose(field: RebalanceField) {
    setState({ kind: "busy" });
    try {
      const updated = await onApply(rebalance, field);
      setState({ kind: "done", text: describe(updated) });
    } catch (err) {
      setState({ kind: "error", text: err instanceof Error ? err.message : String(err) });
    }
  }

  return (
    <div className="mt-2 border-t pt-2 text-xs">
      <p className="text-amber-600">{rebalance.message}</p>
      {state.kind === "done" ? (
        <p className="mt-1 text-green-700 dark:text-green-500">Rebalanced: {state.text}.</p>
      ) : state.kind === "kept" ? (
        <p className="mt-1 text-zinc-500">Kept as is.</p>
      ) : (
        <>
          <p className="mt-1 font-medium">Rebalance?</p>
          <div className="flex flex-wrap gap-2 mt-1">
            {rebalance.options.map((o) => (
              <button
                key={o.field}
                type="button"
                disabled={state.kind === "busy"}
                onClick={() => choose(o.field)}
                className="border rounded px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-700 disabled:opacity-50"
              >
                {o.label}
              </button>
            ))}
            <button
              type="button"
              disabled={state.kind === "busy"}
              onClick={() => setState({ kind: "kept" })}
              className="underline disabled:opacity-50"
            >
              Keep as is
            </button>
          </div>
          {state.kind === "error" && <p className="text-red-600 mt-1">{state.text}</p>}
        </>
      )}
    </div>
  );
}

// A general answer leads with its practical summary; the individual
// findings behind it follow after a blank line and start folded away.
function AnswerText({ answer }: { answer: string }) {
  const split = answer.indexOf("\n\n");
  if (split === -1) return <p>{answer}</p>;
  return (
    <>
      <p>{answer.slice(0, split)}</p>
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-zinc-500">Show the evidence</summary>
        <p className="mt-1">{answer.slice(split + 2)}</p>
      </details>
    </>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <ul className="mt-2 text-xs text-zinc-500 list-disc list-inside">
      {citations.map((c, i) => (
        <li key={i} title={c.snippet}>
          {c.title}
          {c.field && <span className="text-zinc-400"> (backs {c.field === "rir" ? "effort (RIR)" : c.field})</span>}
        </li>
      ))}
    </ul>
  );
}
