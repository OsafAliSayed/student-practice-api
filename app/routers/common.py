"""Helpers shared by the routers: pagination and the OpenAPI `responses` maps."""

import math

from fastapi import Query

from app.models import ErrorResponse

REQUEST_ID_HEADER = {
    "X-Request-ID": {
        "description": "Unique ID for this request (req_ + 6 digits). Quote it when you contact support.",
        "schema": {"type": "string", "example": "req_483920"},
    }
}
RATE_LIMIT_HEADERS = {
    "X-RateLimit-Limit": {
        "description": "Requests allowed per rolling 60 seconds for this key.",
        "schema": {"type": "integer", "example": 30},
    },
    "X-RateLimit-Remaining": {
        "description": "Requests left in the current window.",
        "schema": {"type": "integer", "example": 29},
    },
}
V1_HEADERS = {**REQUEST_ID_HEADER, **RATE_LIMIT_HEADERS}

ERROR_DESCRIPTIONS = {
    400: "Bad request: a parameter has the wrong format.",
    401: "Missing, invalid or expired API key.",
    403: "This API key is not allowed to do this.",
    404: "The requested item does not exist.",
    429: "Rate limit exceeded. Wait the number of seconds in Retry-After.",
    500: "Unexpected server error.",
}


def v1_responses(*extra_codes: int, success: int = 200, success_headers: dict | None = None) -> dict:
    """The `responses=` map for a /v1 endpoint: 401, 429 and 500 always, plus `extra_codes`."""
    responses: dict = {success: {"headers": {**V1_HEADERS, **(success_headers or {})}}}
    for code in sorted({401, 429, 500, *extra_codes}):
        headers = dict(V1_HEADERS)
        if code == 401:
            headers = dict(REQUEST_ID_HEADER)  # rejected keys are not rate limited
        if code == 429:
            headers["Retry-After"] = {
                "description": "Seconds to wait before trying again.",
                "schema": {"type": "integer", "example": 12},
            }
        responses[code] = {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code], "headers": headers}
    return responses


def page_param(default: int = 1):
    return Query(default, ge=1, description="Page number, starting at 1.", examples=[1])


def page_size_param(default: int):
    return Query(default, ge=1, le=100, description=f"Items per page (1-100). Default {default}.",
                 examples=[default])


def client_id_filter():
    return Query(None, description="Only items for this client.", examples=["CL-001"])


def paginate(items: list, page: int, page_size: int) -> dict:
    total = len(items)
    start = (page - 1) * page_size
    return {
        "data": items[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }
