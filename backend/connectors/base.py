import asyncio
import logging
from functools import wraps

import httpx

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    pass


class RetryableError(ConnectorError):
    pass


class NonRetryableError(ConnectorError):
    pass


_SHARED_CLIENT: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _SHARED_CLIENT


async def close_http_client():
    global _SHARED_CLIENT
    if _SHARED_CLIENT and not _SHARED_CLIENT.is_closed:
        await _SHARED_CLIENT.aclose()
        _SHARED_CLIENT = None


def retry_once(max_attempts=2, delay=1.0):
    if max_attempts <= 0:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except RetryableError as e:
                    last_exc = e
                    if attempt < max_attempts:
                        logger.warning(
                            f"Retryable error in {func.__name__} "
                            f"(attempt {attempt}/{max_attempts}): {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All retries exhausted for {func.__name__}: {e}"
                        )
                except NonRetryableError:
                    raise
                except Exception as e:
                    raise ConnectorError(f"Unexpected error in {func.__name__}: {e}") from e
            raise last_exc
        return wrapper
    return decorator
