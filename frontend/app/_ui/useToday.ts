"use client";

import { useSyncExternalStore } from "react";
import { todayISO } from "../_lib/tracker/dates";

// The user's local calendar date, updated just after midnight and whenever
// the tab comes back into view. "" until mounted (no server guess).
function subscribe(onChange: () => void) {
  let timer = 0;
  const schedule = () => {
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 2);
    timer = window.setTimeout(() => {
      onChange();
      schedule();
    }, next.getTime() - now.getTime());
  };
  schedule();
  document.addEventListener("visibilitychange", onChange);
  return () => {
    window.clearTimeout(timer);
    document.removeEventListener("visibilitychange", onChange);
  };
}

export function useToday(): string {
  return useSyncExternalStore(subscribe, todayISO, () => "");
}
