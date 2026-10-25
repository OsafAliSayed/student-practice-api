from datetime import datetime

from fastapi import APIRouter, Depends

from app.auth import require_api_key
from app.data import RECORDS
from app.models import RecordPage
from app.routers.common import client_id_filter, page_param, page_size_param, paginate, v1_responses

router = APIRouter(prefix="/v1/records", tags=["records"], dependencies=[Depends(require_api_key)])

DATE_FORMATS = ("%Y-%m-%dT%H:%M:%SZ", "%d/%m/%Y", "%b %d, %Y")


def normalise_date(value: str) -> datetime:
    """Parse any of the three updated_at formats the source systems send."""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date: {value!r}")


@router.get(
    "",
    response_model=RecordPage,
    summary="List records",
    description="Returns client records (contacts, companies and deals) sorted by id, one page at a time. "
                "Filter by `client_id`.",
    responses=v1_responses(),
)
async def list_records(
    client_id: str | None = client_id_filter(),
    page: int = page_param(),
    page_size: int = page_size_param(50),
):
    records = RECORDS if client_id is None else [r for r in RECORDS if r["client_id"] == client_id]
    result = paginate(records, page, page_size)
    for record in result["data"]:
        normalise_date(record["updated_at"])
    return result
