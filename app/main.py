"""App factory, the core middleware, exception handlers and OpenAPI settings."""

import logging
import os
import secrets
import sys
import time

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import data  # noqa: F401  (importing runs the seed-data checks)
from app.auth import API_KEY_HEADER, auth_error, key_label, permission_error
from app.errors import APIError, api_error_response, error_response
from app.models import Health
from app.ratelimit import SlidingWindowLimiter
from app.routers import clients, import_jobs, records, reports, sync_errors
from app.routers.common import REQUEST_ID_HEADER

DESCRIPTION = """
Practice API for a fictional data-management product. It manages **clients**, the
**import jobs** that load their files, the **records** those imports create, errors from the
CRM **sync**, and **monthly reports**.

**Authentication:** send your API key in the `X-API-Key` header on every request under `/v1`.
In these docs, click **Authorize** and paste your key.

**Rate limit:** 30 requests per rolling 60 seconds per key. Every `/v1` response carries
`X-RateLimit-Limit` and `X-RateLimit-Remaining`; a 429 response carries `Retry-After`.

**Errors** use this shape, except 422 validation errors, which use FastAPI's `{"detail": [...]}`:

```json
{"error": {"code": "client_not_found", "message": "No client with id CL-009", "request_id": "req_483920"}}
```

Every response has an `X-Request-ID` header. Quote it when you contact support.
"""

TAGS = [
    {"name": "clients", "description": "Client accounts."},
    {"name": "import-jobs", "description": "File imports for a client."},
    {"name": "records", "description": "Contacts, companies and deals loaded for each client."},
    {"name": "sync-errors", "description": "Errors from the CRM sync."},
    {"name": "reports", "description": "Monthly summaries per client."},
    {"name": "health", "description": "Service status. No API key needed."},
]

INTERNAL_ERROR_MESSAGE = "Something went wrong on our side. Quote the request ID when you contact support."
RATE_LIMITED_MESSAGE = "Too many requests. Wait the number of seconds in Retry-After, then try again."

logger = logging.getLogger("course_api")


def _configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def new_request_id() -> str:
    return f"req_{secrets.randbelow(1_000_000):06d}"


def is_v1(path: str) -> bool:
    return path == "/v1" or path.startswith("/v1/")


def create_app(rate_limit: int = 30) -> FastAPI:
    _configure_logging()
    public_base_url = os.environ.get("PUBLIC_BASE_URL")
    app = FastAPI(
        title="Course Practice API",
        version="1.0.0",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        servers=[{"url": public_base_url}] if public_base_url else None,
        root_path_in_servers=False,
    )
    app.state.limiter = SlidingWindowLimiter(limit=rate_limit)
    app.state.posted_jobs = import_jobs.PostedJobs()

    @app.middleware("http")
    async def core_middleware(request: Request, call_next):
        """Request ID, auth, rate limit, permission, the 500 envelope and the request log.

        Order follows the error precedence: 401, then 429, then 403; everything else
        (422/400/404) is decided by the routes. Exceptions from routes are caught here
        rather than in an exception handler so the 500 keeps its headers.
        """
        request_id = new_request_id()
        request.scope["request_id"] = request_id
        started = time.perf_counter()
        label = key_label(request.headers.get(API_KEY_HEADER))
        extra_headers: dict[str, str] = {}
        response = None

        if is_v1(request.url.path):
            err = auth_error(label)
            if err is None:
                decision = app.state.limiter.hit(label)
                extra_headers["X-RateLimit-Limit"] = str(decision.limit)
                extra_headers["X-RateLimit-Remaining"] = str(decision.remaining)
                if not decision.allowed:
                    err = APIError(429, "rate_limited", RATE_LIMITED_MESSAGE,
                                   headers={"Retry-After": str(decision.retry_after)})
                else:
                    err = permission_error(label, request.method)
            if err is not None:
                response = api_error_response(err, request_id)

        if response is None:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("request_id=%s unhandled error on %s %s",
                                 request_id, request.method, request.url.path)
                response = error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE, request_id)

        response.headers["X-Request-ID"] = request_id
        for name, value in extra_headers.items():
            response.headers[name] = value

        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info("request_id=%s key=%s %s %s status=%s duration_ms=%.0f",
                    request_id, label, request.method, path, response.status_code, duration_ms)
        return response

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        return api_error_response(exc, request.scope.get("request_id") or new_request_id())

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        # Covers routing errors (unknown path, wrong method) as well as FastAPI's HTTPException.
        request_id = request.scope.get("request_id") or new_request_id()
        if exc.status_code == 404:
            code, message = "not_found", f"No endpoint at {request.url.path}"
        elif exc.status_code == 405:
            code, message = "method_not_allowed", f"{request.method} is not allowed on {request.url.path}"
        else:
            code, message = "http_error", str(exc.detail)
        return error_response(exc.status_code, code, message, request_id, getattr(exc, "headers", None))

    @app.get(
        "/health",
        tags=["health"],
        response_model=Health,
        summary="Health check",
        description='Returns `{"status": "ok"}` when the service is up. No API key needed and not rate limited.',
        responses={200: {"headers": REQUEST_ID_HEADER}},
    )
    async def health():
        return {"status": "ok"}

    for router in (clients.router, import_jobs.router, records.router, sync_errors.router, reports.router):
        app.include_router(router)

    return app


app = create_app()
