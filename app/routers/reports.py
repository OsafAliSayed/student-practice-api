import asyncio
import os
import re

from fastapi import APIRouter, Depends, Query

from app.auth import require_api_key
from app.data import IMPORT_JOBS, SYNC_ERRORS
from app.errors import APIError
from app.models import MonthlyReport
from app.routers.clients import get_client_or_404
from app.routers.common import v1_responses

router = APIRouter(prefix="/v1/reports", tags=["reports"], dependencies=[Depends(require_api_key)])

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SLOW_CLIENT = "CL-003"


def report_delay(client_id: str) -> float:
    if client_id == SLOW_CLIENT:
        return float(os.environ.get("SLOW_REPORT_SECONDS", "15"))
    return float(os.environ.get("REPORT_SECONDS", "1"))


@router.get(
    "/monthly",
    response_model=MonthlyReport,
    summary="Monthly client report",
    description=(
        "Summarises one client's imports and sync errors for one month. Reports are computed on "
        "request and can take several seconds, so set a generous client timeout. "
        "A `month` that is not YYYY-MM returns 400 `invalid_month`; an unknown client returns 404 "
        "`client_not_found`. Months with no activity return zeros."
    ),
    responses=v1_responses(400, 404),
)
async def monthly_report(
    client_id: str = Query(description="Client id.", examples=["CL-001"]),
    month: str = Query(description="Month as YYYY-MM.", examples=["2026-09"]),
):
    if not MONTH_RE.match(month):
        raise APIError(400, "invalid_month", f"month must be in YYYY-MM format, got '{month}'")
    client = get_client_or_404(client_id)

    await asyncio.sleep(report_delay(client_id))  # never time.sleep: one worker serves everyone

    jobs = [j for j in IMPORT_JOBS if j["client_id"] == client_id and j["created_at"].startswith(month)]
    return {
        "client_id": client_id,
        "client_name": client["name"],
        "month": month,
        "imports_total": len(jobs),
        "imports_succeeded": sum(j["status"] == "succeeded" for j in jobs),
        "imports_failed": sum(j["status"] == "failed" for j in jobs),
        "rows_loaded": sum(j["rows_loaded"] for j in jobs),
        "sync_errors": sum(e["client_id"] == client_id and e["occurred_at"].startswith(month)
                           for e in SYNC_ERRORS),
    }
