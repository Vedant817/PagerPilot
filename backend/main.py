import logging
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.session import SessionManager
from backend.orchestrator import AgentGraph
from backend.connectors import pagerduty

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pagerpilot")

session_manager = SessionManager()
agent_graph = AgentGraph(session_manager)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PagerPilot AI SRE Investigator starting up")
    yield
    logger.info("PagerPilot shutting down")


app = FastAPI(
    title="PagerPilot - AI SRE Investigator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = Path(__file__).resolve().parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/ui", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


class InvestigateRequest(BaseModel):
    incident_id: str


class BriefResponse(BaseModel):
    session_id: str
    status: str
    incident_id: str
    brief: Optional[dict] = None
    logs: list[dict] = []


@app.get("/")
async def root():
    return RedirectResponse(url="/ui")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pagerpilot"}


@app.post("/api/v1/investigate", response_model=BriefResponse)
async def investigate_incident(req: InvestigateRequest):
    if not req.incident_id:
        raise HTTPException(status_code=400, detail="incident_id is required")

    result = await agent_graph.run(req.incident_id)

    brief = result.get("brief")
    return BriefResponse(
        session_id=result["session_id"],
        status=result["status"],
        incident_id=result.get("incident_id", req.incident_id),
        brief=brief and {
            "incident_id": brief.incident_id,
            "title": brief.title,
            "service": brief.service,
            "severity": brief.severity.value,
            "status": brief.status,
            "summary": brief.summary,
            "timeline": brief.timeline,
            "hypotheses": [
                {
                    "rank": h.rank,
                    "title": h.title,
                    "description": h.description,
                    "confidence": h.confidence,
                    "supporting_evidence": h.supporting_evidence,
                    "source_signals": [s.value for s in h.source_signals],
                }
                for h in brief.root_cause_hypotheses
            ],
            "recommended_action": brief.recommended_action,
            "evidence_sources": [s.value for s in brief.evidence_sources],
            "generated_at": brief.generated_at,
            "confidence_score": brief.confidence_score,
            "service_impact": {
                "affected_service": brief.service_impact.affected_service,
                "downstream_services": brief.service_impact.downstream_services,
                "external_dependencies_impacted": brief.service_impact.external_dependencies_impacted,
                "customer_facing": brief.service_impact.customer_facing,
                "estimated_blast_percentage": brief.service_impact.estimated_blast_percentage,
                "affected_endpoints": brief.service_impact.affected_endpoints,
            } if brief.service_impact else None,
        },
        logs=result.get("logs", []),
    )


@app.get("/api/v1/incidents")
async def list_incidents(service: Optional[str] = None):
    return {"incidents": await pagerduty.list_incidents(service)}


@app.get("/api/v1/sessions")
async def list_sessions(namespace: Optional[str] = None):
    sessions = await session_manager.list_sessions(namespace)
    return {
        "sessions": [
            {
                "id": s.id,
                "namespace": s.namespace,
                "incident_id": s.incident_id,
                "status": s.status,
                "created_at": s.created_at,
            }
            for s in sessions
        ]
    }


@app.get("/api/v1/sessions/{session_id}")
async def get_session(session_id: str):
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": session.id,
        "namespace": session.namespace,
        "incident_id": session.incident_id,
        "status": session.status,
        "created_at": session.created_at,
        "logs": session.logs,
    }


@app.post("/api/v1/sessions/{session_id}/close")
async def close_session(session_id: str):
    if await session_manager.close_session(session_id):
        return {"status": "closed"}
    raise HTTPException(status_code=404, detail="Session not found")
