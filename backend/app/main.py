# FastAPI() instance, includes routers
from fastapi import FastAPI

from .routers import programs

app = FastAPI()

app.include_router(programs.router)
