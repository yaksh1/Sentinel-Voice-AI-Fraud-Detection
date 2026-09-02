"""agent — FastAPI surface for the voice pipeline.

    uv run uvicorn sentinel_agent.main:app --port <port>

/health is the liveness probe and /metrics is Prometheus text (PLAN 0.6).
/api/offer is the WebRTC signalling endpoint the browser negotiates against
(PLAN 1.1). Everything else this service does arrives in later phases — see
services/agent/README.md.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sentinel_agent.echo import run_echo_bot

# The Deepgram and Cartesia keys live in the repo-root .env (PLAN 0.2), and
# uvicorn does not read it. Must happen before the pipeline reads os.environ.
load_dotenv()

SERVICE = "agent"

# Without a STUN server the agent only ever offers host candidates, which is
# fine on localhost and fails the moment the browser is on another network —
# the Wi-Fi risk called out in PLAN Phase 1.
ICE_SERVER = os.getenv("ICE_SERVERS", "stun:stun.l.google.com:19302")

# demo-web is served from another origin, so the browser preflights the offer
# POST before it will send it. Only signalling crosses origins — WebRTC media
# is not subject to CORS at all.
DEMO_WEB_ORIGIN = os.getenv("DEMO_WEB_ORIGIN", "http://localhost:3000")

webrtc = SmallWebRTCRequestHandler(ice_servers=[IceServer(urls=ICE_SERVER)])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Close any peer connections still open when the server stops."""
    yield
    await webrtc.close()


app = FastAPI(title=SERVICE, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[DEMO_WEB_ORIGIN],
    allow_methods=["POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE}


@app.get("/metrics")
def metrics() -> Response:
    # A route, not a mounted sub-app: mounting serves /metrics/ and answers
    # /metrics itself with a 307, which not every scraper follows.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/offer")
async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Answer a browser's SDP offer and start a pipeline behind it.

    The pipeline is a background task so the answer is on the wire before it
    starts; the browser cannot connect until it has the answer anyway. In 3.8
    this is where the single-use, call_id-bound token gets validated.
    """

    async def start_pipeline(connection: SmallWebRTCConnection) -> None:
        background_tasks.add_task(run_echo_bot, connection)

    # Raises rather than returning None when no answer can be produced, so
    # there is no empty-answer case to handle here.
    return await webrtc.handle_web_request(request, start_pipeline)


@app.patch("/api/offer")
async def ice_candidate(request: SmallWebRTCPatchRequest) -> dict[str, str]:
    """Accept trickled ICE candidates for an offer already answered."""
    await webrtc.handle_patch_request(request)
    return {"status": "success"}
