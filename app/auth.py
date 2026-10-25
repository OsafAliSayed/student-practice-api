"""API keys: the one key table used by both the middleware and the route dependencies."""

from fastapi import Security
from fastapi.security import APIKeyHeader

from app.errors import APIError

API_KEY_HEADER = "X-API-Key"

# Fake, hard-coded keys. Logs only ever show the label.
KEYS = {
    "demo_key_rw_4K9P": "rw",
    "demo_key_ro_7M2Q": "ro",
    "demo_key_rw_inst_5H8D": "inst",
    "demo_key_expired_1X0Z": "expired",
}
VALID_LABELS = {"rw", "ro", "inst"}
READ_ONLY_LABELS = {"ro"}

api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="Your API key. Every endpoint under /v1 needs it.",
)


def key_label(raw_key: str | None) -> str:
    """Map a raw header value to a label that is safe to log."""
    if raw_key is None or raw_key == "":
        return "none"
    return KEYS.get(raw_key, "invalid")


def auth_error(label: str) -> APIError | None:
    """The 401 for this key label, or None if the key is valid."""
    if label in VALID_LABELS:
        return None
    if label == "expired":
        return APIError(401, "api_key_expired", "API key expired on 2026-10-01. Generate a new key.")
    if label == "none":
        return APIError(401, "missing_api_key", "Send your API key in the X-API-Key header.")
    return APIError(401, "invalid_api_key", "This API key is not valid.")


def permission_error(label: str, method: str) -> APIError | None:
    """The 403 for a read-only key on a write method, or None."""
    if label in READ_ONLY_LABELS and method.upper() == "POST":
        return APIError(403, "forbidden", "This API key is read-only")
    return None


async def require_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Route dependency: makes Swagger show the padlock and returns the key label.

    The middleware has already rejected bad keys before routing; this re-check keeps
    the routes safe if they are ever mounted without it.
    """
    label = key_label(api_key)
    err = auth_error(label)
    if err:
        raise err
    return label


async def require_write(api_key: str | None = Security(api_key_header)) -> str:
    label = await require_api_key(api_key)
    err = permission_error(label, "POST")
    if err:
        raise err
    return label
