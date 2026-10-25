"""The error envelope shared by every non-422 error."""

from fastapi.responses import JSONResponse


class APIError(Exception):
    """Raised by routes and dependencies; rendered as the error envelope."""

    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


def error_response(status_code: int, code: str, message: str, request_id: str,
                   headers: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": request_id}}
    return JSONResponse(body, status_code=status_code, headers=headers)


def api_error_response(err: APIError, request_id: str) -> JSONResponse:
    return error_response(err.status_code, err.code, err.message, request_id, err.headers)
