import logging
from typing import Optional

from backend.agents.base import BaseAgent, AgentResult
from backend.agents.router import RouterAgent
from backend.agents.source_fetch import SourceFetchAgent
from backend.agents.analyst import AnalystAgent
from backend.agents.reporter import ReporterAgent
from backend.session import Session, SessionManager

logger = logging.getLogger(__name__)


class AgentGraph:
    def __init__(self, session_manager: SessionManager):
        self.router = RouterAgent()
        self.source_fetch = SourceFetchAgent()
        self.analyst = AnalystAgent()
        self.reporter = ReporterAgent()
        self.session_manager = session_manager

    async def run(self, incident_id: str, session_namespace: str = "default") -> dict:
        session = await self.session_manager.create_session(incident_id, session_namespace)
        session.status = "running"
        session.add_log("system", "Graph started", f"incident={incident_id}")

        stages = [
            ("router", self.router),
            ("source_fetch", self.source_fetch),
            ("analyst", self.analyst),
            ("reporter", self.reporter),
        ]

        results = {}
        for stage_name, agent in stages:
            try:
                session.add_log(agent.name, f"Running {stage_name} agent")
                result: AgentResult = await agent.run(session.context)
                results[stage_name] = {
                    "success": result.success,
                    "data": result.data if result.success else None,
                    "error": result.error if not result.success else None,
                }
                if not result.success:
                    session.add_log(
                        agent.name, f"Agent failed", result.error
                    )
                    session.status = "failed"
                    return {
                        "session_id": session.id,
                        "status": "failed",
                        "incident_id": incident_id,
                        "stage": stage_name,
                        "error": result.error,
                        "results": results,
                        "logs": session.logs,
                        "fetch_errors": session.context.get("fetch_errors", []),
                    }
                session.add_log(agent.name, "Agent completed")
            except Exception as e:
                logger.exception(f"Unexpected error in {stage_name}")
                session.add_log(agent.name, "Exception", str(e))
                session.status = "failed"
                return {
                    "session_id": session.id,
                    "status": "failed",
                    "incident_id": incident_id,
                    "stage": stage_name,
                    "error": str(e),
                    "results": results,
                    "logs": session.logs,
                    "fetch_errors": session.context.get("fetch_errors", []),
                }

        session.status = "completed"
        session.add_log("system", "Graph completed", "All agents finished")

        brief = session.context.get("brief")
        return {
            "session_id": session.id,
            "status": "completed",
            "incident_id": incident_id,
            "incident": session.context.get("incident"),
            "evidence": session.context.get("evidence"),
            "hypotheses": session.context.get("hypotheses"),
            "brief": brief,
            "logs": session.logs,
            "fetch_errors": session.context.get("fetch_errors", []),
        }
