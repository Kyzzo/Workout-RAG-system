"use client";

import { useMemo, useState, type ReactNode } from "react";
import { applyChange, checklistItems } from "../_lib/tracker/checklist";
import { addDays, todayISO, weekday } from "../_lib/tracker/dates";
import { buildSessions } from "../_lib/tracker/schedule";
import { localKey } from "../_lib/tracker/store";
import type { Regimen, SessionLog } from "../_lib/tracker/types";
import { SessionProvider, type SessionValue } from "../_state/session";
import type { Program } from "../types";
import { createMockBackend } from "./mockBackend";

// `npm run preview`: the real UI against in-browser fixtures, no Clerk and
// no backend. ?state=guest | empty | untracked picks the starting point.

function seedTracking(userId: string, program: Program) {
  try {
    if (window.localStorage.getItem(localKey(userId))) return;
    const today = todayISO();
    const monday = addDays(today, -weekday(today));
    const regimen: Regimen = { programId: program.id, startDate: addDays(monday, -14), dayOffsets: {}, updatedAt: new Date().toISOString() };
    const past = buildSessions(program, regimen, {}, today).filter((s) => s.date < today);
    const logs: Record<string, SessionLog> = {};
    past.forEach((session, i) => {
      if (i === 3) return; // one missed session
      const items = checklistItems(session);
      const stamp = new Date().toISOString();
      let log =
        i === 5
          ? applyChange(session, items, { kind: "toggle", itemId: items[0].id, done: true }, stamp)
          : i === 6
            ? applyChange(session, items, { kind: "skip", skipped: true }, stamp)
            : applyChange(session, items, { kind: "all" }, stamp);
      if (log && log.status === "completed") {
        log = {
          ...log,
          entries: log.entries.map((e, k) => (k === 0 ? { ...e, achieved: { weight: `${60 + i * 2.5} kg`, reps: "10, 9, 9" } } : e)),
          ...(i === 1 ? { notes: "Felt flat. Slept badly." } : {}),
        };
      }
      if (log) logs[log.key] = log;
    });
    window.localStorage.setItem(localKey(userId), JSON.stringify({ version: 1, regimen, logs }));
  } catch {
    // Preview only: a blocked storage just means an untracked start.
  }
}

export default function PreviewSession({ children }: { children: ReactNode }) {
  const [setup] = useState(() => {
    const state = new URLSearchParams(window.location.search).get("state") ?? "tracked";
    const backend = createMockBackend({ empty: state === "empty" });
    const userId = `preview-${state}`;
    if (state === "tracked") seedTracking(userId, backend.programs[0]);
    return { state, backend, userId };
  });

  const value = useMemo<SessionValue>(
    () => ({
      status: setup.state === "guest" ? "guest" : "user",
      userId: setup.state === "guest" ? null : setup.userId,
      api: setup.backend.api,
      stream: setup.backend.stream,
      openSignIn: () => {
        const w = window as unknown as { __previewSignIn?: number };
        w.__previewSignIn = (w.__previewSignIn ?? 0) + 1;
      },
      account: (
        <span className="tag" title="Fixture preview: no Clerk, no backend">
          Preview
        </span>
      ),
      preview: true,
    }),
    [setup],
  );

  return <SessionProvider value={value}>{children}</SessionProvider>;
}
