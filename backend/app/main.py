# FastAPI() instance, includes routers
import inngest.fast_api
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import CLERK_ALLOWED_ORIGINS
from .rag.ingest import ingest_literature_pdf, inngest_client
from .routers import programs
from .routers import generation

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CLERK_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(programs.router)
app.include_router(generation.router)

inngest.fast_api.serve(app, inngest_client, [ingest_literature_pdf])
