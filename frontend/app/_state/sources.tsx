"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import type { SourcesRequest } from "../_lib/evidence";

type SourcesValue = {
  request: SourcesRequest | null;
  openSources: (request: SourcesRequest) => void;
  closeSources: () => void;
};

const SourcesContext = createContext<SourcesValue | null>(null);

export function SourcesProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<SourcesRequest | null>(null);
  const opener = useRef<Element | null>(null);

  const openSources = useCallback((next: SourcesRequest) => {
    opener.current = document.activeElement;
    setRequest(next);
  }, []);

  const closeSources = useCallback(() => {
    setRequest(null);
    const back = opener.current;
    window.setTimeout(() => {
      const lost = !document.activeElement || document.activeElement === document.body;
      if (lost && back instanceof HTMLElement && back.isConnected) back.focus({ preventScroll: true });
    }, 0);
  }, []);

  const value = useMemo(() => ({ request, openSources, closeSources }), [request, openSources, closeSources]);
  return <SourcesContext value={value}>{children}</SourcesContext>;
}

export function useSources(): SourcesValue {
  const value = useContext(SourcesContext);
  if (!value) throw new Error("useSources outside SourcesProvider");
  return value;
}
