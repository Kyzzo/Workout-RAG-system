# Backend — AI Workout Structuring App

FastAPI backend. See `../design.txt` and `../PROJECT_CONTEXT.md` for full project context.

## Setup

Dependencies are managed with [uv](https://github.com/astral-sh/uv), installed into a local venv (rather than a global/system `uv` install).

### Git Bash (MINGW64)

```bash
# from the backend/ directory
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip uv
uv --version
```

Note: once the venv is active (prompt shows `(.venv)`), use `python -m pip ...` rather than pip's own suggested upgrade command — that suggestion is Windows-path-formatted and breaks in bash if your path contains spaces.

### PowerShell

```powershell
# from the backend/ directory
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip uv
uv --version
```

If activation is blocked by PowerShell's execution policy:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Installing project dependencies

Once `uv` is available in the activated venv:

```powershell
uv sync
```

This installs everything pinned in `pyproject.toml` / `uv.lock`.

## Environment variables

```powershell
# from the backend/ directory
copy .env.example .env
```

Then fill in real values in `.env` (never commit this file — it's gitignored):

- `CLERK_PUBLISHABLE_KEY` — from your Clerk dashboard (not secret, safe to
  share, but still kept out of git per this project's env-file policy)
- `CLERK_ALLOWED_ORIGINS` — comma-separated list of frontend origins
  allowed to call this API (e.g. `http://localhost:3000` locally)
- `DATABASE_URL` — see "Database setup" below; the example file's value
  matches that section's `docker-compose.yml` port (`15432`, not the
  Postgres default `5432` — see that section for why)
- `QDRANT_URL` / `QDRANT_API_KEY` — from your Qdrant Cloud cluster
- `OPENAI_API_KEY` — from your OpenAI account (used for embeddings; only
  needed if you're running ingestion, see "Ingesting research papers")

## Database setup

Postgres runs via Docker Compose (defined at the repo root, one level up):

```powershell
# from the repo root, NOT backend/
docker compose up -d
docker compose ps  # confirm it's actually running before continuing
```

Note: this project's `docker-compose.yml` maps Postgres to host port
**15432**, not the default 5432 — Windows/Hyper-V had reserved a large
chunk of the 5000s port range (including 5432 itself), causing silent
connection hangs rather than a clear error. If `docker compose ps`
doesn't show the port mapping in its PORTS column, or connections hang
rather than fail fast, that's the likely cause — see
`../notes/phase2/phase2_rag_ingestion_concepts.txt` for the full story.

Once Postgres is running, apply migrations to create/update the schema:

```powershell
# from the backend/ directory
uv run alembic upgrade head
```

If you change `app/models.py` later, generate a new migration rather
than hand-writing SQL:

```powershell
uv run alembic revision --autogenerate -m "describe the change"
```

Then **read the generated file in `alembic/versions/`** before applying
it — autogenerate is a good first draft, not something to trust blindly
— then run `uv run alembic upgrade head` again.

## Running the app

```powershell
uv run uvicorn app.main:app --port 8000 --reload
```

(Not `fastapi dev app/main.py` — that CLI command requires the
`fastapi[standard]` extra, which isn't installed here; `fastapi` and
`uvicorn[standard]` were added as separate dependencies instead.)

Once running: API docs (Swagger UI) at http://localhost:8000/docs.

## Ingesting research papers (RAG corpus)

Three processes need to be running simultaneously, in separate terminals:

```powershell
# Terminal 1 — FastAPI app
uv run uvicorn app.main:app --port 8000 --reload

# Terminal 2 — Inngest dev server (requires Node.js/npm)
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest
```

Once both are up, ingest a PDF into the shared `literature` Qdrant collection:

```powershell
uv run python -m scripts.ingest_literature "<path-to-pdf>" <category> [source_id]
```

- `<category>` must be one of: `volume`, `frequency`, `intensity`, `progression`
- `source_id` is optional (defaults to the PDF path) — worth naming something readable, since it's what shows up as the source in retrieval results
- Check ingestion run status/logs at the Inngest dev server's dashboard: http://localhost:8288

### Wiping a collection

If the ingested payload shape changes (e.g. adding a subcategory field),
it's simpler to wipe and re-ingest everything than to backfill old
points. This permanently deletes all points in the given collection:

```powershell
uv run python -m scripts.reset_collection <literature|user_context>
```

Requires typing the collection name again as a confirmation prompt —
there's no undo.
