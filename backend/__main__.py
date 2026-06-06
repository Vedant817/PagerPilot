import os

import uvicorn


def _reload_enabled() -> bool:
    return os.environ.get("UVICORN_RELOAD", "false").strip().lower() in {"1", "true", "yes", "on"}


def _port() -> int:
    try:
        return int(os.environ.get("PORT", "8000"))
    except ValueError:
        return 8000


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=_port(),
        reload=_reload_enabled(),
    )
