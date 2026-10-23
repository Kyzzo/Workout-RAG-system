"use client";

import dynamic from "next/dynamic";
import type { ReactNode } from "react";
import { Shell } from "../_ui/Shell";
import { AppProvider } from "./app";
import { ChatProvider } from "./chat";
import { ClerkSession } from "./ClerkSession";
import { DialogsProvider } from "./dialogs";
import { useSession } from "./session";
import { SourcesProvider } from "./sources";
import { TrackerProvider } from "./tracker";
import { UiProvider } from "./ui";

// Development-only fixture backend (`npm run preview`). The condition is a
// build-time constant, so production bundles never include it.
const PREVIEW = process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_CITESET_PREVIEW === "1";
const PreviewSession = PREVIEW ? dynamic(() => import("../_preview/PreviewSession"), { ssr: false }) : null;

export function Providers({ children }: { children: ReactNode }) {
  if (PreviewSession) {
    return (
      <PreviewSession>
        <Scoped>{children}</Scoped>
      </PreviewSession>
    );
  }
  return (
    <ClerkSession>
      <Scoped>{children}</Scoped>
    </ClerkSession>
  );
}

// Everything per-user lives under one key: when Clerk signs out or switches
// accounts without a reload, the whole subtree remounts empty before it can
// render the previous user's programs, chat or tracking.
function Scoped({ children }: { children: ReactNode }) {
  const { status, userId } = useSession();
  return <UserScope key={userId ?? status}>{children}</UserScope>;
}

function UserScope({ children }: { children: ReactNode }) {
  return (
    <DialogsProvider>
      <UiProvider>
        <AppProvider>
          <TrackerProvider>
            <ChatProvider>
              <SourcesProvider>
                <Shell>{children}</Shell>
              </SourcesProvider>
            </ChatProvider>
          </TrackerProvider>
        </AppProvider>
      </UiProvider>
    </DialogsProvider>
  );
}
