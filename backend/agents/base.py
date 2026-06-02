import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AgentResult:
    def __init__(self, success: bool, data: Any = None, error: Optional[str] = None):
        self.success = success
        self.data = data
        self.error = error


class BaseAgent:
    name: str = "base"

    async def run(self, context: dict) -> AgentResult:
        raise NotImplementedError
