from fastapi import APIRouter, Depends, Query

from app.auth import require_api_key
from app.data import SYNC_ERRORS
from app.models import SyncErrorCode, SyncErrorPage
from app.routers.common import client_id_filter, page_param, page_size_param, paginate, v1_responses

router = APIRouter(prefix="/v1/sync-errors", tags=["sync-errors"], dependencies=[Depends(require_api_key)])


@router.get(
    "",
    response_model=SyncErrorPage,
    summary="List sync errors",
    description="Returns errors from the CRM sync, newest first, one page at a time. "
                "Filter by `client_id` and `code`.",
    responses=v1_responses(),
)
async def list_sync_errors(
    client_id: str | None = client_id_filter(),
    code: SyncErrorCode | None = Query(None, description="Only errors with this code.", examples=["timeout"]),
    page: int = page_param(),
    page_size: int = page_size_param(20),
):
    errors = SYNC_ERRORS
    if client_id is not None:
        errors = [e for e in errors if e["client_id"] == client_id]
    if code is not None:
        errors = [e for e in errors if e["code"] == code.value]
    return paginate(errors, page, page_size)
