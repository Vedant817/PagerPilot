import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.guardrails import redact_sensitive
from backend.config import SESSION_MAX_AGE_SECONDS, SESSION_MAX_LOGS, SESSION_MAX_SESSIONS

logger = logging.getLogger(__name__)


class Session:
    def __init__(self, incident_id: str, session_namespace: str = "default"):
        self.id = str(uuid.uuid4())
        self.namespace = session_namespace
        self.incident_id = incident_id
        self.status = "created"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.thread_id: Optional[str] = None
        self.context: dict = {
            "incident_id": incident_id,
            "session_id": self.id,
        }
        self.logs: list[dict] = []

    def add_log(self, agent: str, action: str, detail: str = ""):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "action": action,
            "detail": redact_sensitive(detail),
        }
        self.logs.append(entry)
        if len(self.logs) > SESSION_MAX_LOGS:
            self.logs.pop(0)
        logger.info(f"[Session {self.id[:8]}] {agent}: {action}")


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, incident_id: str, session_namespace: str = "default") -> Session:
        async with self._lock:
            self._evict_stale()
            session = Session(incident_id, session_namespace)
            self.sessions[session.id] = session
            logger.info(f"Created session {session.id[:8]} for incident {incident_id}")
            return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            self._evict_stale()
            return self.sessions.get(session_id)

    async def list_sessions(self, session_namespace: Optional[str] = None) -> list[Session]:
        async with self._lock:
            self._evict_stale()
            sessions = list(self.sessions.values())
            if session_namespace:
                sessions = [s for s in sessions if s.namespace == session_namespace]
            return sorted(sessions, key=lambda s: s.created_at, reverse=True)

    async def close_session(self, session_id: str) -> bool:
        async with self._lock:
            session = self.sessions.get(session_id)
            if session:
                session.status = "closed"
                return True
            return False

    async def delete_session(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                return True
            return False

    def _evict_stale(self):
        now = datetime.now(timezone.utc)
        stale_ids = []
        for sid, s in self.sessions.items():
            try:
                created = datetime.fromisoformat(s.created_at)
                age = (now - created).total_seconds()
                if age > SESSION_MAX_AGE_SECONDS:
                    stale_ids.append(sid)
            except (ValueError, TypeError):
                stale_ids.append(sid)
        for sid in stale_ids:
            del self.sessions[sid]

        if len(self.sessions) > SESSION_MAX_SESSIONS:
            sorted_sessions = sorted(
                self.sessions.values(), key=lambda s: s.created_at
            )
            excess = len(sorted_sessions) - SESSION_MAX_SESSIONS
            for s in sorted_sessions[:excess]:
                del self.sessions[s.id]
