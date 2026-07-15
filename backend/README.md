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
