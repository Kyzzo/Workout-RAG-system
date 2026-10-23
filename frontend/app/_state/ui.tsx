"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

// Which overlay sheet is up. One at a time; sources and dialogs sit above.
export type SheetName = "chat" | "new" | null;

type UiValue = {
  sheet: SheetName;
  // Bumped whenever something asks for the chat input to take focus.
  chatFocus: number;
  openChat: (focus?: boolean) => void;
  openNew: () => void;
  closeSheet: () => void;
};

const UiContext = createContext<UiValue | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const [sheet, setSheet] = useState<SheetName>(null);
  const [chatFocus, setChatFocus] = useState(0);

  const openChat = useCallback((focus = false) => {
    setSheet("chat");
    if (focus) setChatFocus((n) => n + 1);
  }, []);
  const openNew = useCallback(() => setSheet("new"), []);
  const closeSheet = useCallback(() => setSheet(null), []);

  const value = useMemo(
    () => ({ sheet, chatFocus, openChat, openNew, closeSheet }),
    [sheet, chatFocus, openChat, openNew, closeSheet],
  );
  return <UiContext value={value}>{children}</UiContext>;
}

export function useUi(): UiValue {
  const value = useContext(UiContext);
  if (!value) throw new Error("useUi outside UiProvider");
  return value;
}
