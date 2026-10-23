"use client";

import { useCallback } from "react";
import { programTitle } from "../types";
import { useApp } from "./app";
import { useChat } from "./chat";
import { useTracker } from "./tracker";

// Flows that cross providers: switching and deleting a program also clear
// the chat anchor, and deleting one takes its tracking history with it.
export function useProgramActions() {
  const app = useApp();
  const tracker = useTracker();
  const chat = useChat();
  const { select: selectProgram, deleteProgram: removeProgram, programs } = app;
  const { countLogs, regimen, deleteProgramData, store } = tracker;
  const { clearAnchor } = chat;

  const select = useCallback(
    (id: number | null) => {
      selectProgram(id);
      clearAnchor();
    },
    [selectProgram, clearAnchor],
  );

  const remove = useCallback(
    async (id: number) => {
      const logged = await countLogs(id);
      const tracked = regimen?.programId === id;
      const where = store?.kind === "api" ? "" : " on this device";
      const history = logged ? `its tracking history (${logged} logged session${logged === 1 ? "" : "s"})${where}` : null;
      const note = tracked
        ? `You're tracking this program: tracking stops${history ? ` and ${history} is deleted` : ""}.`
        : history
          ? `${history[0].toUpperCase()}${history.slice(1)} is deleted too.`
          : null;
      const deleted = await removeProgram(id, note);
      if (!deleted) return false;
      clearAnchor();
      if (logged > 0 || tracked) await deleteProgramData(id);
      return true;
    },
    [countLogs, regimen, store, removeProgram, clearAnchor, deleteProgramData],
  );

  const titleOf = useCallback(
    (id: number) => {
      const p = programs?.find((x) => x.id === id);
      return p ? programTitle(p) : `Program #${id}`;
    },
    [programs],
  );

  return { select, remove, titleOf };
}
