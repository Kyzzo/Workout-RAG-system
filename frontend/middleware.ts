import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

// `npm run preview` renders the UI against in-browser fixtures, with no Clerk
// keys; it only ever runs under `next dev`.
const preview = process.env.NODE_ENV === "development" && process.env.NEXT_PUBLIC_CITESET_PREVIEW === "1";

export default preview ? () => NextResponse.next() : clerkMiddleware();

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js|jpe?g|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
