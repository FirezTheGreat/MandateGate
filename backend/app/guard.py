"""Request guard for both services: refuse what a web page in the operator's browser could send.

- Host must be a local name (`ALLOWED_HOSTS`, default localhost / 127.0.0.1 / ::1). Defeats DNS
  rebinding, where an attacker's page points its own domain at 127.0.0.1 but keeps its Host header.
- A state-changing request (anything but GET / HEAD / OPTIONS) that carries an Origin header must
  come from the dashboard. Defeats cross-site form posts to body-less routes such as /admin/reset:
  CORS only hides the response from the attacker's page, the POST itself still runs.
  Requests with no Origin (agents, scripts, the payment service's notifier) are not browsers and pass.

Pure ASGI (no BaseHTTPMiddleware), so the SSE stream passes through untouched.
"""

from collections.abc import Iterable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.models import ErrorResponse

DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def hostname(host_header: str) -> str:
    """"localhost:8000" → "localhost", "[::1]:8000" → "::1"."""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1 : h.find("]")] if "]" in h else ""
    return h.rsplit(":", 1)[0] if ":" in h else h


class RequestGuard:
    def __init__(self, app: ASGIApp, *, origins: Iterable[str]) -> None:
        self.app = app
        self.origins = frozenset(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        problem = self.check(scope)
        if problem is None:
            await self.app(scope, receive, send)
            return
        status, error, detail = problem
        await JSONResponse(status_code=status, content=ErrorResponse(error=error, detail=detail).model_dump())(scope, receive, send)

    def check(self, scope: Scope) -> tuple[int, str, str] | None:
        headers = Headers(scope=scope)
        settings = getattr(getattr(scope.get("app"), "state", None), "settings", None)
        allowed = getattr(settings, "allowed_hosts", DEFAULT_ALLOWED_HOSTS)
        if hostname(headers.get("host", "")) not in allowed:
            return 400, "bad_host", "requests must address this service as a local host (see ALLOWED_HOSTS)"
        origin = headers.get("origin")
        if scope["method"] not in SAFE_METHODS and origin is not None and origin not in self.origins:
            return 403, "bad_origin", "state-changing requests from other web origins are refused"
        return None
