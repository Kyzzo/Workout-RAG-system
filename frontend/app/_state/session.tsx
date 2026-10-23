"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { Api, ApiStream } from "../useApi";

// Who is here and how to reach the backend. Backed by Clerk in the real app
// and by in-browser fixtures in the development-only preview.
export type SessionValue = {
  status: "loading" | "guest" | "user";
  userId: string | null;
  api: Api;
  stream: ApiStream;
  openSignIn: () => void;
  account: ReactNode;
  preview: boolean;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ value, children }: { value: SessionValue; children: ReactNode }) {
  return <SessionContext value={value}>{children}</SessionContext>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession outside SessionProvider");
  return value;
}

export function useApi(): Api {
  return useSession().api;
}
