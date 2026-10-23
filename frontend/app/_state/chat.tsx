"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  changeIdOf,
  detailText,
  freshStatus,
  historyFor,
  readNdjson,
  turnId,
  turnsFromHistory,
  type Anchor,
  type AssistantTurn,
  type RebalanceState,
  type Turn,
} from "../_lib/chatModel";
import { findPrescription } from "../_lib/format";
import type {
  ChangeStatus,
  ChatMessageRequest,
  RebalanceField,
  SavedChatTurn,
  SwapExerciseResponse,
  WeeklyPrescription,
} from "../types";
import { errorMessage, readableDetail } from "../useApi";
import { useApp } from "./app";
import { useDialogs } from "./dialogs";
import { useSession } from "./session";
import { useTracker } from "./tracker";
import { useUi } from "./ui";

type ChatValue = {
  turns: Turn[];
  historyError: string | null;
  anchor: Anchor | null;
  anchorTo: (anchor: Anchor) => void;
  clearAnchor: () => void;
  composer: string;
  setComposer: (text: string) => void;
  sending: boolean;
  stage: string | null;
  send: (text: string) => Promise<void>;
  clearHistory: () => Promise<void>;
  confirmSwap: (turnId: string) => Promise<void>;
  cancelSwap: (turnId: string) => Promise<void>;
  undoChange: (turnId: string) => Promise<void>;
  applyRebalance: (turnId: string, field: RebalanceField) => Promise<void>;
  keepRebalance: (turnId: string) => void;
  undoRebalance: (turnId: string) => Promise<void>;
  loadIsPercent: boolean;
  goal: "hypertrophy" | "strength";
};

const ChatContext = createContext<ChatValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const { status, api, stream } = useSession();
  const { programs, selectedId, trees, refreshTree, refreshProgram } = useApp();
  const { regimen } = useTracker();
  const { openChat } = useUi();
  const { confirm } = useDialogs();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [stage, setStage] = useState<string | null>(null);

  // The conversation as of now, for building each request's history.
  const turnsRef = useRef<Turn[]>([]);
  const sendingRef = useRef(false);
  const putTurns = useCallback((update: (t: Turn[]) => Turn[]) => {
    turnsRef.current = update(turnsRef.current);
    setTurns(turnsRef.current);
  }, []);

  useEffect(() => {
    if (status !== "user") return;
    let alive = true;
    api<SavedChatTurn[]>("/chat/history")
      .then((saved) => alive && putTurns((current) => [...turnsFromHistory(saved), ...current]))
      .catch((err) => alive && setHistoryError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [status, api, putTurns]);

  const regimenProgramId = regimen?.programId ?? null;
  // A chat change can touch the selected program or the tracked one.
  const refreshAffected = useCallback(async () => {
    const jobs = [refreshProgram()];
    if (regimenProgramId !== null && regimenProgramId !== selectedId && trees[regimenProgramId]) jobs.push(refreshTree(regimenProgramId));
    await Promise.all(jobs);
  }, [refreshProgram, refreshTree, regimenProgramId, selectedId, trees]);

  const appendError = useCallback(
    (text: string) => putTurns((t) => [...t, { id: turnId("e"), role: "error", text }]),
    [putTurns],
  );

  const updateAssistant = useCallback(
    (id: string, update: (turn: AssistantTurn) => AssistantTurn) =>
      putTurns((t) => t.map((turn) => (turn.id === id && turn.role === "assistant" ? update(turn) : turn))),
    [putTurns],
  );

  const findAssistant = useCallback(
    (id: string) => turnsRef.current.find((t): t is AssistantTurn => t.id === id && t.role === "assistant"),
    [],
  );

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      setStage(null);
      const before = turnsRef.current;
      putTurns((t) => [...t, { id: turnId("u"), role: "user", text: message, anchor: anchor?.label ?? null }]);
      setComposer("");
      const body: ChatMessageRequest = {
        message,
        field_id: anchor?.prescriptionId ?? null,
        history: historyFor(before),
        anchor_label: anchor?.label ?? null,
        this_week_only: anchor?.thisWeekOnly ?? false,
      };
      try {
        const res = await stream("/chat/message/stream", body);
        if (!res.ok) {
          appendError(`Request failed: ${res.status} ${readableDetail(await res.text())}`);
          return;
        }
        let answered = false;
        let adjusted = false;
        await readNdjson(res, (event) => {
          if (event.type === "stage") setStage(event.label);
          else if (event.type === "result") {
            answered = true;
            const response = event.response;
            if (response.mode === "adjust_prescription") adjusted = true;
            putTurns((t) => [
              ...t,
              {
                id: turnId("a"),
                role: "assistant",
                response,
                status: freshStatus(response),
                rebalance: response.rebalance ? { phase: "offered" } : undefined,
              },
            ]);
          } else if (event.type === "error") {
            answered = true;
            appendError(detailText(event.detail));
          }
        });
        if (!answered) appendError("The answer was cut off - please try again.");
        if (adjusted) await refreshAffected();
      } catch (err) {
        appendError(errorMessage(err));
      } finally {
        sendingRef.current = false;
        setSending(false);
        setStage(null);
      }
    },
    [anchor, stream, putTurns, appendError, refreshAffected],
  );

  const setStatus = useCallback(
    (id: string, status: ChangeStatus, extra?: Partial<AssistantTurn>) =>
      updateAssistant(id, (turn) => ({ ...turn, ...extra, status, busy: null })),
    [updateAssistant],
  );

  const confirmSwap = useCallback(
    async (id: string) => {
      const turn = findAssistant(id);
      const changeId = turn?.response.swap?.change_id;
      if (!turn || changeId == null) return;
      updateAssistant(id, (t) => ({ ...t, busy: "confirm" }));
      try {
        const applied = await api<SwapExerciseResponse>(`/changes/${changeId}/confirm`, { method: "POST" });
        setStatus(id, "applied", { response: { ...turn.response, swap: applied } });
        await refreshAffected();
      } catch (err) {
        updateAssistant(id, (t) => ({ ...t, busy: null }));
        appendError(`Couldn't confirm the swap: ${errorMessage(err)}`);
      }
    },
    [api, findAssistant, updateAssistant, setStatus, refreshAffected, appendError],
  );

  const cancelSwap = useCallback(
    async (id: string) => {
      const turn = findAssistant(id);
      const changeId = turn?.response.swap?.change_id;
      if (!turn || changeId == null) return;
      updateAssistant(id, (t) => ({ ...t, busy: "cancel" }));
      try {
        await api<void>(`/changes/${changeId}`, { method: "DELETE" });
        setStatus(id, "cancelled");
      } catch (err) {
        updateAssistant(id, (t) => ({ ...t, busy: null }));
        appendError(`Couldn't cancel the swap: ${errorMessage(err)}`);
      }
    },
    [api, findAssistant, updateAssistant, setStatus, appendError],
  );

  const undoChange = useCallback(
    async (id: string) => {
      const turn = findAssistant(id);
      const changeId = turn ? changeIdOf(turn.response) : null;
      if (!turn || changeId == null) return;
      updateAssistant(id, (t) => ({ ...t, busy: "undo" }));
      try {
        await api(`/changes/${changeId}/undo`, { method: "POST" });
        setStatus(id, "undone");
        await refreshAffected();
      } catch (err) {
        updateAssistant(id, (t) => ({ ...t, busy: null }));
        appendError(`Couldn't undo: ${errorMessage(err)}`);
      }
    },
    [api, findAssistant, updateAssistant, setStatus, refreshAffected, appendError],
  );

  const setRebalance = useCallback(
    (id: string, rebalance: RebalanceState) => updateAssistant(id, (t) => ({ ...t, rebalance })),
    [updateAssistant],
  );

  const applyRebalance = useCallback(
    async (id: string, field: RebalanceField) => {
      const turn = findAssistant(id);
      const offer = turn?.response.rebalance;
      if (!turn || !offer) return;
      setRebalance(id, { phase: "applying", field });
      try {
        const result = await api<{ prescription: WeeklyPrescription; change_id: number }>(
          `/weekly-prescriptions/${offer.prescription_id}/rebalance`,
          { method: "POST", body: { changed_field: offer.changed_field, apply_field: field } },
        );
        setRebalance(id, { phase: "applied", prescription: result.prescription, changeId: result.change_id });
        await refreshAffected();
      } catch (err) {
        setRebalance(id, { phase: "offered", error: errorMessage(err) });
      }
    },
    [api, findAssistant, setRebalance, refreshAffected],
  );

  const keepRebalance = useCallback((id: string) => setRebalance(id, { phase: "kept" }), [setRebalance]);

  const undoRebalance = useCallback(
    async (id: string) => {
      const state = findAssistant(id)?.rebalance;
      if (!state || state.phase !== "applied") return;
      setRebalance(id, { phase: "undoing", prescription: state.prescription, changeId: state.changeId });
      try {
        await api(`/changes/${state.changeId}/undo`, { method: "POST" });
        setRebalance(id, { phase: "undone" });
        await refreshAffected();
      } catch (err) {
        setRebalance(id, { ...state, error: errorMessage(err) });
      }
    },
    [api, findAssistant, setRebalance, refreshAffected],
  );

  const clearHistory = useCallback(async () => {
    const ok = await confirm({
      title: "Clear the conversation?",
      body: <p>The saved conversation is deleted. Changes you made stay in your programs.</p>,
      destructive: true,
      confirmLabel: "Clear history",
    });
    if (!ok) return;
    try {
      await api<void>("/chat/history", { method: "DELETE" });
      putTurns(() => []);
      setHistoryError(null);
    } catch (err) {
      appendError(`Couldn't clear the history: ${errorMessage(err)}`);
    }
  }, [confirm, api, putTurns, appendError]);

  const anchorTo = useCallback(
    (next: Anchor) => {
      setAnchor(next);
      openChat(true);
    },
    [openChat],
  );
  const clearAnchor = useCallback(() => setAnchor(null), []);

  const anchoredPrescription = anchor ? findPrescription(trees[anchor.programId], anchor.prescriptionId) : null;
  const loadIsPercent = !!anchoredPrescription?.load.includes("%");
  const selectedGoal = programs?.find((p) => p.id === selectedId)?.goal;
  const goal = selectedGoal === "strength" ? "strength" : "hypertrophy";

  const value = useMemo<ChatValue>(
    () => ({
      turns,
      historyError,
      anchor,
      anchorTo,
      clearAnchor,
      composer,
      setComposer,
      sending,
      stage,
      send,
      clearHistory,
      confirmSwap,
      cancelSwap,
      undoChange,
      applyRebalance,
      keepRebalance,
      undoRebalance,
      loadIsPercent,
      goal,
    }),
    [turns, historyError, anchor, anchorTo, clearAnchor, composer, sending, stage, send, clearHistory, confirmSwap, cancelSwap, undoChange, applyRebalance, keepRebalance, undoRebalance, loadIsPercent, goal],
  );

  return <ChatContext value={value}>{children}</ChatContext>;
}

export function useChat(): ChatValue {
  const value = useContext(ChatContext);
  if (!value) throw new Error("useChat outside ChatProvider");
  return value;
}
