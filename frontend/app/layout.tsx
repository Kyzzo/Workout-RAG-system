import { ClerkProvider } from "@clerk/nextjs";
import { Analytics } from "@vercel/analytics/next";
import type { Metadata, Viewport } from "next";
import { Newsreader, Overpass_Mono } from "next/font/google";
import { Providers } from "./_state/Providers";
import "./globals.css";
import "./_styles/wall.css";
import "./_styles/program.css";
import "./_styles/panels.css";
import "./_styles/chat.css";

const serif = Newsreader({ subsets: ["latin"], variable: "--font-newsreader", style: ["normal", "italic"], axes: ["opsz"], display: "swap" });
const mono = Overpass_Mono({ subsets: ["latin"], variable: "--font-overpass-mono", display: "swap" });

export const metadata: Metadata = {
  title: "Citeset",
  description: "Strength and hypertrophy programs where every number is research-cited.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#121211",
  colorScheme: "dark",
  interactiveWidget: "resizes-content",
};

// The fixture preview (`npm run preview`) runs without Clerk; never in a
// production build.
const PREVIEW = process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_CITESET_PREVIEW === "1";

const clerkAppearance = {
  variables: {
    colorPrimary: "#d9dadb",
    colorPrimaryForeground: "#151515",
    colorBackground: "#1d1d1c",
    colorForeground: "#e7e6e2",
    colorMuted: "#262625",
    colorMutedForeground: "#9d9c98",
    colorNeutral: "#e7e6e2",
    colorInput: "#121212",
    colorInputForeground: "#e7e6e2",
    colorBorder: "#3b3b3a",
    colorRing: "#c9cdd0",
    colorModalBackdrop: "rgba(6, 6, 6, 0.78)",
    borderRadius: "2px",
    fontFamily: "var(--font-overpass-mono), ui-monospace, monospace",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const fonts = `${serif.variable} ${mono.variable}`;
  const body = (
    <html lang="en" className={fonts}>
      <body>
        <Providers>{children}</Providers>
        <Analytics />
      </body>
    </html>
  );
  return PREVIEW ? body : <ClerkProvider appearance={clerkAppearance}>{body}</ClerkProvider>;
}
