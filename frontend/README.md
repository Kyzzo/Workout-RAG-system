# Frontend

Next.js app for the AI Workout Tracker. See the [root README](../README.md)
for what the project does.

It renders programs with a citation badge on each value, runs the program
wizard and research chat, and sends every request to the FastAPI backend
with a Clerk session token. All program logic lives in the backend. This
app has no API routes of its own.

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
