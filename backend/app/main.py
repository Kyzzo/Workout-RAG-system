# FastAPI() instance, includes routers
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import programs

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(programs.router)
