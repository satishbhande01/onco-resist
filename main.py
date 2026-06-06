"""
main.py

Entry point for the Oncology Drug Resistance Portal.

Run with:
    uvicorn main:app --reload
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

from app.database import init_db
from app.routers import drugs, targets, search, chat


# ─────────────────────────────────────────────────────────────
# Lifespan
# Runs once on startup, once on shutdown.
# Use it for anything that should happen before requests are served.
# ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # verify database exists and print drug count
    yield  # server runs here — handles all requests
    # anything after yield runs on shutdown


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Oncology Drug Resistance Portal",
    description="FDA-approved oncology drugs, targets, and resistance mutations",
    version="1.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────
# Static files
# Files in app/static/ are served directly at /static/
# e.g. app/static/css/base.css → http://localhost:8000/static/css/base.css
# ─────────────────────────────────────────────────────────────

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "app" / "static")),
    name="static",
)


# ─────────────────────────────────────────────────────────────
# Routers
# Each router file handles one section of the site.
# include_router attaches its routes to the main app.
# ─────────────────────────────────────────────────────────────

app.include_router(drugs.router)
app.include_router(targets.router)
app.include_router(search.router)
app.include_router(chat.router)
