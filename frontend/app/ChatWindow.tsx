"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useRef, useState } from "react";
import { API_URL } from "./apiUrl";
import type { WeeklyPrescription } from "./types";

type Citation = { title: string; snippet: string };

type ChatResponse = {
  mode: "adjust_prescription" | "discuss_prescription" | "answer_general_question";
  prescription: WeeklyPrescription | null;
  answer: string | null;
  citations: Citation[];
  grounding_note: string | null;
};

type ChatTurn =
  | { role: "user"; text: string }
  | { role: "assistant"; response: ChatResponse }
  | { role: "error"; text: string };

export default function ChatWindow({
  fieldId,
  anchorLabel,
  onClearAnchor,
}: {
  // Structural context (phase6_chat_routing_concepts.txt section 2): set by
  // clicking "ask about this" on a rendered prescription in ProgramTree, not
  // typed in by hand - the parent workspace owns this so the anchor survives
  // across messages in the same thread and can show a real label, not just
  // a bare id.
  fieldId: number | null;
  anchorLabel: string | null;
  onClearAnchor: () => void;
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
    setTurns((prev) => [...prev, { role: "user", text: sentMessage }]);
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
    <div className="flex flex-col gap-4 p-8 w-full max-w-lg">
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
          Not anchored to a specific exercise - click &quot;ask about this&quot; on a
          prescription above, or just ask a general research question below.
        </p>
      )}

      <div className="flex flex-col gap-3 min-h-40 max-h-[28rem] overflow-y-auto border rounded p-4 bg-zinc-50 dark:bg-zinc-900">
        {turns.length === 0 && (
          <p className="text-sm text-zinc-500">
            Ask about a prescription (click &quot;ask about this&quot; above to
            anchor the conversation to it), or ask a general research
            question.
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
          placeholder="Ask a question or request a change..."
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
        <p className="font-medium">Updated prescription #{p.id}</p>
        <p>
          {p.sets} sets - {p.reps} reps - {p.load}
        </p>
        {p.grounding_note ? (
          <p className="text-amber-600 text-xs mt-1">{p.grounding_note}</p>
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
        </li>
      ))}
    </ul>
  );
}
