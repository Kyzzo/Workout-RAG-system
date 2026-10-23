"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";
import { API_URL } from "./apiUrl";

// Attaches the Clerk session token to a request against the FastAPI backend
// and turns a non-2xx response into a thrown Error, so callers can use a
// single try/catch instead of checking res.ok at every call site.
export function useApi() {
  const { getToken } = useAuth();

  return useCallback(
    async <T,>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> => {
      const send = async (fresh: boolean) =>
        fetch(`${API_URL}${path}`, {
          method: options.method ?? "GET",
          headers: {
            Authorization: `Bearer ${await getToken(fresh ? { skipCache: true } : undefined)}`,
            ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
          },
          body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
        });
      // Clerk session tokens last 60s. A request that waited in line (the
      // browser's per-host connection limit, a busy server) can arrive with
      // its token already expired: retry once with a freshly minted one.
      // Six block-generation steps failed this way on Oct 20, 2026.
      let res = await send(false);
      if (res.status === 401) res = await send(true);

      if (!res.ok) {
        throw new Error(`Request failed: ${res.status} ${await res.text()}`);
      }
      // 204 No Content (deletes) has no body to parse.
      return res.status === 204 ? (undefined as T) : res.json();
    },
    [getToken],
  );
}
