"""agent — health and metrics scaffold (PLAN 0.6).

    uv run uvicorn sentinel_agent.main:app --port <port>

/health is the liveness probe; /metrics is Prometheus text. Everything this
service actually does arrives in later phases — see services/agent/README.md.
"""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

SERVICE = "agent"

app = FastAPI(title=SERVICE)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE}


@app.get("/metrics")
def metrics() -> Response:
    # A route, not a mounted sub-app: mounting serves /metrics/ and answers
    # /metrics itself with a 307, which not every scraper follows.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
