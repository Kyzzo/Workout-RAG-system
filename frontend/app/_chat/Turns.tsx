"use client";

import { Fragment, useState } from "react";
import { changeIdOf, splitAnswer, splitSwapChanges, type AssistantTurn, type Turn } from "../_lib/chatModel";
import { paperOf, prettyRange, titleDetails } from "../_lib/format";
import { Caveat } from "../_sources/RuleSources";
import { useChat } from "../_state/chat";
import { Icon } from "../_ui/Icon";
import type { ChatCitation, WeeklyPrescription } from "../types";

export function TurnView({ turn }: { turn: Turn }) {
  if (turn.role === "user") {
    return (
      <div className="turn turn-user">
        <span className="turn-who label">You</span>
        <div className="turn-body">
          {turn.anchor && <span className="tag turn-about">About {turn.anchor}</span>}
          <p className="turn-text">{turn.text}</p>
        </div>
      </div>
    );
  }
  if (turn.role === "error") {
    return (
      <div className="turn turn-error">
        <span className="turn-who label">Error</span>
        <div className="turn-body">
          <p className="error-text">{turn.text}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="turn turn-desk">
      <span className="turn-who label">Desk</span>
      <div className="turn-body">
        <DeskTurn turn={turn} />
      </div>
    </div>
  );
}

function DeskTurn({ turn }: { turn: AssistantTurn }) {
  const r = turn.response;
  if (r.mode === "adjust_prescription" && r.swap) return <SwapTurn turn={turn} />;
  if (r.mode === "adjust_prescription") return <AdjustTurn turn={turn} />;
  if (r.mode === "discuss_prescription") {
    return (
      <Cited citations={r.citations} turnId={turn.id}>
        {(cite) => (
          <>
            {r.answer && <AnswerText text={r.answer} onCite={cite} />}
            {r.prescription && (
              <div className="turn-values">
                <span className="label">Current</span>
                <Values p={r.prescription} />
              </div>
            )}
            {r.grounding_note && <Caveat text={r.grounding_note} />}
          </>
        )}
      </Cited>
    );
  }
  return <GeneralTurn turn={turn} />;
}

function GeneralTurn({ turn }: { turn: AssistantTurn }) {
  const r = turn.response;
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const { summary, evidence } = splitAnswer(r.answer ?? "");
  return (
    <Cited citations={r.citations} turnId={turn.id}>
      {(cite) => (
        <>
          <AnswerText text={summary} onCite={cite} lead />
          {evidence && (
            <div className="turn-evidence">
              <button type="button" className="rule-toggle" aria-expanded={evidenceOpen} onClick={() => setEvidenceOpen((o) => !o)}>
                <Icon name="layers" size={14} /> Supporting evidence <Icon name={evidenceOpen ? "up" : "down"} size={12} />
              </button>
              {evidenceOpen && evidence.split(/\n{2,}/).map((para, i) => <AnswerText key={i} text={para} onCite={cite} />)}
            </div>
          )}
          {r.grounding_note && <Caveat text={r.grounding_note} />}
        </>
      )}
    </Cited>
  );
}

// Answer text whose [n] markers point at citations[n-1].
function AnswerText({ text, onCite, lead = false }: { text: string; onCite: (n: number) => void; lead?: boolean }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className={lead ? "answer answer-lead" : "answer"}>
      {parts.map((part, i) => {
        const m = /^\[(\d+)\]$/.exec(part);
        if (!m) return <Fragment key={i}>{part}</Fragment>;
        return (
          <button key={i} type="button" className="cite-ref" aria-label={`Citation ${m[1]}`} onClick={() => onCite(Number(m[1]))}>
            {m[1]}
          </button>
        );
      })}
    </p>
  );
}

function Cited({
  citations,
  turnId,
  children,
}: {
  citations: ChatCitation[];
  turnId: string;
  children: (cite: (n: number) => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const cite = (n: number) => {
    if (n < 1 || n > citations.length) return;
    setOpen(n);
    requestAnimationFrame(() => document.getElementById(`${turnId}-c${n}`)?.scrollIntoView({ block: "nearest" }));
  };
  return (
    <>
      {children(cite)}
      {citations.length > 0 && (
        <ol className="cites" aria-label="Citations">
          {citations.map((c, i) => {
            const n = i + 1;
            const isOpen = open === n;
            return (
              <li key={n} id={`${turnId}-c${n}`} className="cite" data-open={isOpen || undefined}>
                <button type="button" className="cite-head" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : n)}>
                  <span className="cite-n mono">{n}</span>
                  <span className="cite-title">
                    <span className="cite-paper">{paperOf(c.title)}</span>
                    {titleDetails(c.title) && <span className="cite-details"> · {titleDetails(c.title)}</span>}
                  </span>
                  {c.field && <span className="tag">{c.field === "rir" ? "effort" : c.field}</span>}
                </button>
                {isOpen && <blockquote className="excerpt">{c.snippet}</blockquote>}
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}

function Values({ p }: { p: WeeklyPrescription }) {
  return (
    <span className="values">
      <span className="vchip">{p.sets === 1 ? "1 set" : `${p.sets} sets`}</span>
      {p.reps && <span className="vchip">{prettyRange(p.reps)} reps</span>}
      {p.load && <span className="vchip">{p.load}</span>}
      {p.rir && <span className="vchip">{prettyRange(p.rir)}</span>}
    </span>
  );
}

function valuesText(p: WeeklyPrescription) {
  return [p.sets === 1 ? "1 set" : `${p.sets} sets`, p.reps && `${p.reps} reps`, p.load, p.rir].filter(Boolean).join(", ");
}

function UndoLine({ turn }: { turn: AssistantTurn }) {
  const chat = useChat();
  if (changeIdOf(turn.response) == null) return null;
  if (turn.status === "undone") return <p className="turn-state">Undone.</p>;
  if (turn.status !== "applied") return null;
  return (
    <div className="turn-actions">
      <button type="button" className="btn btn-small" disabled={!!turn.busy} onClick={() => void chat.undoChange(turn.id)}>
        <Icon name="undo" size={14} /> {turn.busy === "undo" ? "Undoing..." : "Undo"}
      </button>
    </div>
  );
}

function AdjustTurn({ turn }: { turn: AssistantTurn }) {
  const r = turn.response;
  if (r.answer) {
    return (
      <>
        <p className="turn-kind">Kept as is</p>
        <p className="answer">{r.answer}</p>
        <UndoLine turn={turn} />
      </>
    );
  }
  return (
    <>
      <p className="turn-kind">Updated</p>
      {r.prescription && <Values p={r.prescription} />}
      {r.grounding_note ? <Caveat text={r.grounding_note} /> : <p className="turn-supported">Fully supported by cited research.</p>}
      <UndoLine turn={turn} />
      {r.rebalance && turn.status !== "undone" && <Rebalance turn={turn} />}
    </>
  );
}

function Rebalance({ turn }: { turn: AssistantTurn }) {
  const chat = useChat();
  const offer = turn.response.rebalance!;
  const state = turn.rebalance ?? { phase: "offered" as const };
  return (
    <div className="rebalance">
      <p className="rebalance-why">
        <span className="caveat-mark">
          <Icon name="warning" size={12} /> Fit
        </span>
        {offer.message}
      </p>
      {state.phase === "offered" && (
        <>
          <div className="turn-actions">
            {offer.options.map((o) => (
              <button key={o.field} type="button" className="btn btn-small" onClick={() => void chat.applyRebalance(turn.id, o.field)}>
                {o.label}
              </button>
            ))}
            <button type="button" className="btn btn-quiet btn-small" onClick={() => chat.keepRebalance(turn.id)}>
              Keep as is
            </button>
          </div>
          {state.error && <p className="error-text">{state.error}</p>}
        </>
      )}
      {state.phase === "applying" && <p className="turn-state scanline">Rebalancing...</p>}
      {(state.phase === "applied" || state.phase === "undoing") && (
        <>
          <p className="turn-state">Rebalanced: {valuesText(state.prescription)}.</p>
          <div className="turn-actions">
            <button type="button" className="btn btn-small" disabled={state.phase === "undoing"} onClick={() => void chat.undoRebalance(turn.id)}>
              <Icon name="undo" size={14} /> {state.phase === "undoing" ? "Undoing..." : "Undo"}
            </button>
          </div>
          {state.phase === "applied" && state.error && <p className="error-text">{state.error}</p>}
        </>
      )}
      {state.phase === "undone" && <p className="turn-state">Rebalance undone.</p>}
      {state.phase === "kept" && <p className="turn-state">Kept as is.</p>}
    </div>
  );
}

function SwapTurn({ turn }: { turn: AssistantTurn }) {
  const chat = useChat();
  const swap = turn.response.swap!;
  const { own, other } = splitSwapChanges(swap.changes);
  const applied = turn.status === "applied" || turn.status === "undone";
  return (
    <>
      <p className="turn-kind">
        {applied ? "Swapped" : "Swap"} {swap.old_name} <span aria-hidden>→</span>
        <span className="sr-only">for</span> {swap.new_name}
        {applied ? "" : "?"}
      </p>
      {own.length > 0 && (
        <ul className="changes">
          {own.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      {other.length > 0 ? (
        <>
          <p className="label changes-head">{applied ? "Also changed" : "This would also change"}</p>
          <ul className="changes changes-other">
            {other.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="turn-supported">{applied ? "Nothing else in the block changed." : "Nothing else in the block would change."}</p>
      )}
      {turn.status === "pending" && (
        <div className="turn-actions">
          <button type="button" className="btn btn-steel btn-small" disabled={!!turn.busy} onClick={() => void chat.confirmSwap(turn.id)}>
            <Icon name="swap" size={14} /> {turn.busy === "confirm" ? "Swapping..." : "Confirm swap"}
          </button>
          <button type="button" className="btn btn-small" disabled={!!turn.busy} onClick={() => void chat.cancelSwap(turn.id)}>
            {turn.busy === "cancel" ? "Cancelling..." : "Cancel"}
          </button>
        </div>
      )}
      {turn.status === "applied" && <UndoLine turn={turn} />}
      {turn.status === "undone" && <p className="turn-state">Undone.</p>}
      {turn.status === "cancelled" && <p className="turn-state">Cancelled - nothing changed.</p>}
    </>
  );
}
