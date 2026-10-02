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
      const token = await getToken();
      const res = await fetch(`${API_URL}${path}`, {
        method: options.method ?? "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      });

      if (!res.ok) {
        throw new Error(`Request failed: ${res.status} ${await res.text()}`);
      }
      // 204 No Content (deletes) has no body to parse.
      return res.status === 204 ? (undefined as T) : res.json();
    },
    [getToken],
  );
}
