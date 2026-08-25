import os
import time
import logging
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
MAX_REQUESTS = 5

LIMITED_PATHS = {"/login", "/setup", "/mfa/verify", "/mfa/verify/recovery", "/settings/mfa/setup", "/settings/mfa/disable", "/settings/mfa/recovery/regenerate"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, window_seconds: int | None = None,
                 max_requests: int | None = None, limited_paths: set = None):
        super().__init__(app)
        self.window_seconds = window_seconds if window_seconds is not None else \
            int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", WINDOW_SECONDS))
        self.max_requests = max_requests if max_requests is not None else \
            int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", MAX_REQUESTS))
        self.limited_paths = limited_paths or LIMITED_PATHS
        self._attempts: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method != "POST" or request.url.path not in self.limited_paths:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{request.url.path}"
        now = time.monotonic()
        self._attempts[key] = [t for t in self._attempts[key] if now - t < self.window_seconds]

        if len(self._attempts[key]) >= self.max_requests:
            logger.warning("Rate limit hit for %s (%d attempts)", key, len(self._attempts[key]))
            return Response(
                content="Too many attempts. Please try again in a minute.",
                status_code=429,
                media_type="text/plain",
            )

        self._attempts[key].append(now)
        return await call_next(request)
