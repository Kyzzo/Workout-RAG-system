import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
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

// Display face for titles only (.display); body text stays Geist.
const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
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
    <ClerkProvider
      // Clerk's sign-in screens in the app's tokens, so they follow light
      // and dark mode with the rest of the page.
      appearance={{
        variables: {
          colorPrimary: "#5b4ff5",
          colorPrimaryForeground: "#ffffff",
          colorBackground: "var(--surface)",
          colorForeground: "var(--fg)",
          colorMutedForeground: "var(--fg-muted)",
          colorInput: "var(--surface-2)",
          colorInputForeground: "var(--fg)",
          borderRadius: "0.75rem",
          fontFamily: "var(--font-geist-sans)",
        },
        elements: {
          headerTitle: "!font-display !text-[1.6rem] !font-normal !tracking-normal",
          // Clerk's box is a fixed ~25rem: let it shrink inside the page
          // padding on phones instead of scrolling the page sideways.
          rootBox: "w-full max-w-[25rem]",
          cardBox: "!w-full !max-w-full",
        },
      }}
    >
      <html
        lang="en"
        className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} h-full antialiased`}
      >
        <body className="flex min-h-full flex-col">
          <header className="sticky top-0 z-40 border-b border-line bg-bg/70 backdrop-blur-xl">
            <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4 sm:px-6 lg:px-8">
              <span className="glyph size-8 rounded-[10px]">
                <Mark className="size-[18px]" />
              </span>
              <div className="flex min-w-0 flex-1 items-baseline gap-3">
                <p className="display truncate text-[1.3rem]">
                  AI Workout <em className="text-fg-muted">Structuring</em>
                </p>
                <p className="eyebrow hidden truncate sm:block">Every number research-cited</p>
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
