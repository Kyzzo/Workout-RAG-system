# Frontend

Next.js app for Citeset. See the [root README](../README.md)
for what the project does.

The landing page is the **schedule**: the tracked program laid out on a
month calendar, with the selected day's session checklist beside it. The
**program** page holds everything about one program: blocks, days,
exercises and their cited values, weekly sets by muscle, generation and the
manual builder. The **evidence desk** (research chat) and the **new program**
generator open from the bottom rail. Every request goes to the FastAPI
backend with a Clerk session token; this app has no API routes of its own.

## Setup

Create `.env.local` with:

```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=...
CLERK_SECRET_KEY=...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Then:

```bash
npm install
npm run dev     # http://localhost:3000
npm run lint
npm run build
```

The backend must be running for anything beyond the sign-in page. See the
[backend README](../backend/README.md).

## Preview without Clerk or the backend

```bash
npm run preview
```

Runs `next dev` against in-browser fixtures (`app/_preview/`): invented
programs, studies and chat answers, labelled as such, with three weeks of
tracking already logged. Add `?state=guest`, `?state=empty` or
`?state=untracked` to the URL to start from those states. It only works under
`next dev`; production builds leave the fixtures out.

## Tracking storage

Session tracking is saved in the browser (`localStorage`, one key per Clerk
user) and the UI says so. `app/_lib/tracker/store.ts` also has an
`ApiTrackerStore` for the proposed `/tracker` endpoints (spec Appendix C);
set `NEXT_PUBLIC_TRACKER_BACKEND=api` once they exist, and the schedule
settings offer a one-time import of what's on the device.

## Layout

| Path | What's there |
|---|---|
| `app/page.tsx`, `app/_wall/` | Schedule: calendar, session checklist, start tracking, schedule settings |
| `app/program/page.tsx`, `app/_program/` | Program page: blocks, exercises, weekly sets by muscle, builder forms |
| `app/_chat/`, `app/_generator/`, `app/_sources/` | Evidence desk, generator and progress dock, sources panel |
| `app/_state/` | Providers: session (Clerk or preview), programs, tracker, chat, dialogs |
| `app/_lib/` | Pure logic: schedule and checklist maths, evidence questions, chat history, analysis |
| `app/_styles/`, `app/globals.css` | The visual system: concrete, steel, paint |
| `app/useApi.ts`, `app/blockGeneration.ts`, `app/types.ts` | API client (401 retry), block generation, backend types |
