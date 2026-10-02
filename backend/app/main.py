# FastAPI() instance, includes routers
import logging

import inngest.fast_api
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import CLERK_ALLOWED_ORIGINS
from .rag.ingest import ingest_literature_pdf, inngest_client
from .routers import chat, generation, programs, structure

app = FastAPI()
logger = logging.getLogger("uvicorn")


class UnhandledErrorMiddleware(BaseHTTPMiddleware):
    # An unhandled exception normally becomes a 500 built OUTSIDE the CORS
    # middleware, so it has no CORS headers and the browser reports only a
    # bare "Failed to fetch". Catching it here, inside CORS, turns it into a
    # readable JSON 500 the frontend can actually display.
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": f"Server error ({type(exc).__name__}) - see the backend logs for details."},
            )


# Order matters: middleware added later wraps middleware added earlier, so
# CORS (added second) sits outside the error handler and every response,
# including the error ones, gets CORS headers.
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CLERK_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(programs.router)
app.include_router(programs.splits_router)
app.include_router(generation.router)
app.include_router(generation.mesocycle_router)
app.include_router(generation.exercise_slot_router)
app.include_router(chat.router)
app.include_router(structure.router)

inngest.fast_api.serve(app, inngest_client, [ingest_literature_pdf])
