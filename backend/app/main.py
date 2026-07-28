# FastAPI() instance, includes routers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import CLERK_ALLOWED_ORIGINS
from .routers import programs

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CLERK_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(programs.router)
