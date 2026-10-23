"use client";

import { UserButton, useAuth, useClerk } from "@clerk/nextjs";
import { useMemo, type ReactNode } from "react";
import { createApiClient } from "../useApi";
import { SessionProvider, type SessionValue } from "./session";

export function ClerkSession({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, userId, getToken } = useAuth();
  const clerk = useClerk();

  // Clerk memoizes getToken per Clerk instance, so this client (and every
  // effect keyed on it) stays stable for the page's lifetime.
  const client = useMemo(() => createApiClient(getToken), [getToken]);

  const value = useMemo<SessionValue>(
    () => ({
      status: !isLoaded ? "loading" : isSignedIn ? "user" : "guest",
      userId: isSignedIn ? (userId ?? null) : null,
      api: client.api,
      stream: client.stream,
      openSignIn: () => clerk.openSignIn(),
      account: <UserButton />,
      preview: false,
    }),
    [isLoaded, isSignedIn, userId, client, clerk],
  );

  return <SessionProvider value={value}>{children}</SessionProvider>;
}
