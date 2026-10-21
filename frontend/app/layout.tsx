import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider, Show, SignInButton, UserButton } from "@clerk/nextjs";
import { Mark } from "./Icons";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Workout Structuring",
  description: "Strength and hypertrophy programs where every number is research-cited.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider>
      <html
        lang="en"
        className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      >
        <body className="flex min-h-full flex-col">
          <header className="sticky top-0 z-40 border-b border-line bg-bg/75 backdrop-blur-xl">
            <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4 sm:px-6 lg:px-8">
              <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-accent to-accent-2 text-white shadow-[0_6px_16px_-6px_var(--accent-ring)]">
                <Mark className="size-[18px]" />
              </span>
              <div className="min-w-0 flex-1 leading-tight">
                <p className="truncate text-sm font-semibold tracking-tight">AI Workout Structuring</p>
                <p className="hidden truncate text-xs text-fg-subtle sm:block">Every number research-cited</p>
              </div>
              <Show when="signed-out">
                <SignInButton>
                  <button type="button" className="btn btn-primary btn-sm">
                    Sign in
                  </button>
                </SignInButton>
              </Show>
              <Show when="signed-in">
                <UserButton />
              </Show>
            </div>
          </header>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
