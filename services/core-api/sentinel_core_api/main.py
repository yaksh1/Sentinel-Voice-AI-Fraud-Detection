"""core-api — system of record and the agent's tool endpoints.

    uv run uvicorn sentinel_core_api.main:app --port <port>

/health is the liveness probe and /metrics is Prometheus text (PLAN 0.6).
/tools/* are the five tools the agent calls (PLAN 2.3). Checkout, the call-row
endpoints and SSE arrive in Phase 3 — see services/core-api/README.md.
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sentinel_core_api import db
from sentinel_core_api.tools import router as tools_router

# DATABASE_URL lives in the repo-root .env (PLAN 0.2); uvicorn does not read it.
load_dotenv()

SERVICE = "core-api"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Hold one Neon pool for the life of the process."""
    await db.connect()
    yield
    await db.close()


app = FastAPI(title=SERVICE, lifespan=lifespan)
app.include_router(tools_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE}


@app.get("/metrics")
def metrics() -> Response:
    # A route, not a mounted sub-app: mounting serves /metrics/ and answers
    # /metrics itself with a 307, which not every scraper follows.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
