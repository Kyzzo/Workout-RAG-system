"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef, useState } from "react";
import { API_URL } from "./apiUrl";
import type { WeeklyPrescription } from "./types";

type Citation = { title: string; snippet: string; field: "sets" | "load" | null };

type ChatResponse = {
  mode: "adjust_prescription" | "discuss_prescription" | "answer_general_question";
  prescription: WeeklyPrescription | null;
  answer: string | null;
  citations: Citation[];
  grounding_note: string | null;
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

function summarizeResponse(r: ChatResponse): string {
  const p = r.prescription;
  const values = p ? `${p.sets} sets, ${p.reps || "reps n/a"}, ${p.load || "load n/a"}` : "";
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
  onClearAnchor: () => void;
  // Lets the program view refetch after an adjust changes a stored value.
  onPrescriptionUpdated?: () => void;
}) {
  const { getToken } = useAuth();
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const messageInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (fieldId !== null) messageInputRef.current?.focus();
  }, [fieldId]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim()) return;
    setSending(true);

    const sentMessage = message;
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

  return (
    <div className="flex flex-col gap-4 w-full">
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

      <div className="flex flex-col gap-3 min-h-40 max-h-[28rem] overflow-y-auto border rounded p-4 bg-zinc-50 dark:bg-zinc-900">
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
          return <ChatTurnResult key={i} response={turn.response} />;
        })}
      </div>

      <form onSubmit={handleSend} className="flex gap-2">
        <input
          ref={messageInputRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={
            fieldId !== null
              ? 'e.g. "make it 4 sets", "add more volume", "why this load?"'
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

function ChatTurnResult({ response }: { response: ChatResponse }) {
  if (response.mode === "adjust_prescription" && response.prescription) {
    const p = response.prescription;
    return (
      <div className="self-start bg-white dark:bg-zinc-800 border rounded px-3 py-2 max-w-[90%] text-sm">
        {/* An answer on an adjust means the requested direction couldn't be
            honored and the value was kept - see chat.py _handle_adjust. */}
        <p className="font-medium">{response.answer ? "Kept as is" : "Updated"}</p>
        {response.answer && <p>{response.answer}</p>}
        <p className={response.answer ? "text-zinc-500 text-xs mt-1" : ""}>
          {p.sets} sets - {p.reps || "reps n/a"} - {p.load || "load n/a"}
        </p>
        {response.answer ? null : response.grounding_note ? (
          <p className="text-amber-600 text-xs mt-1">{response.grounding_note}</p>
        ) : (
          <p className="text-green-700 dark:text-green-500 text-xs mt-1">
            Fully supported by cited research.
          </p>
        )}
      </div>
    );
  }

  if (response.mode === "discuss_prescription" && response.prescription) {
    const p = response.prescription;
    return (
      <div className="self-start bg-white dark:bg-zinc-800 border rounded px-3 py-2 max-w-[90%] text-sm">
        <p>{response.answer}</p>
        <p className="text-zinc-500 text-xs mt-2">
          Current: {p.sets} sets, {p.reps} reps, {p.load}.
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
      <p>{response.answer}</p>
      <CitationList citations={response.citations} />
    </div>
  );
}

function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <ul className="mt-2 text-xs text-zinc-500 list-disc list-inside">
      {citations.map((c, i) => (
        <li key={i} title={c.snippet}>
          {c.title}
          {c.field && <span className="text-zinc-400"> (backs {c.field})</span>}
        </li>
      ))}
    </ul>
  );
}
