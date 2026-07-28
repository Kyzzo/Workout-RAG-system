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

### Running the app

```powershell
uv run fastapi dev app/main.py
```

## Environment variables

Copy `.env.example` to `.env` and fill in real values (DB connection string, OpenAI key, Clerk secret key, etc.) once those are added.

## Ingesting research papers (RAG corpus)

Three processes need to be running simultaneously, in separate terminals:

```powershell
# Terminal 1 — FastAPI app
uv run fastapi dev app/main.py

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
