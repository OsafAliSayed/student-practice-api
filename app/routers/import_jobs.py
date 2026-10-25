import re
from collections import OrderedDict
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.auth import require_api_key, require_write
from app.data import IMPORT_JOBS, IMPORT_JOBS_BY_ID, iso
from app.errors import APIError
from app.models import ImportJob, ImportJobCreate, ImportJobPage, JobSort, JobStatus
from app.routers.clients import get_client_or_404
from app.routers.common import client_id_filter, page_param, page_size_param, paginate, v1_responses

router = APIRouter(prefix="/v1/import-jobs", tags=["import-jobs"])

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIRST_POSTED_JOB = 9001
MAX_POSTED_JOBS = 200


class PostedJobs:
    """Jobs created through POST. Kept apart from the seed data so list results never change."""

    def __init__(self):
        self.jobs: OrderedDict[str, dict] = OrderedDict()
        self.next_number = FIRST_POSTED_JOB

    def add(self, client_id: str, file_name: str) -> dict:
        job = {
            "id": f"IMP-{self.next_number}",
            "client_id": client_id,
            "file_name": file_name,
            "status": "queued",
            "rows_total": None,
            "rows_loaded": 0,
            "created_at": iso(datetime.now(timezone.utc)),
            "finished_at": None,
            "error": None,
        }
        self.next_number += 1
        self.jobs[job["id"]] = job
        while len(self.jobs) > MAX_POSTED_JOBS:
            self.jobs.popitem(last=False)
        return job


def parse_created_after(value: str) -> date:
    try:
        if not DATE_RE.match(value):
            raise ValueError(value)
        return date.fromisoformat(value)
    except ValueError:
        raise APIError(400, "invalid_date",
                       f"created_after must be a date in YYYY-MM-DD format, got '{value}'") from None


@router.get(
    "",
    response_model=ImportJobPage,
    summary="List import jobs",
    description=(
        "Returns import jobs, newest first by default, one page at a time. "
        "Filter by `status`, `client_id` and `created_after`. "
        "A `created_after` value that is not a YYYY-MM-DD date returns 400 `invalid_date`. "
        "Jobs you create with POST are not included here; fetch them by id."
    ),
    responses=v1_responses(400),
    dependencies=[Depends(require_api_key)],
)
async def list_import_jobs(
    status: JobStatus | None = Query(None, description="Only jobs with this status.", examples=["failed"]),
    client_id: str | None = client_id_filter(),
    created_after: str | None = Query(
        None,
        description="Only jobs created on or after this day (UTC), as YYYY-MM-DD.",
        examples=["2026-10-01"],
    ),
    sort: JobSort = Query(JobSort.newest_first, description="`created_at` (oldest first) or `-created_at` (newest first)."),
    page: int = page_param(),
    page_size: int = page_size_param(20),
):
    jobs = IMPORT_JOBS
    if created_after is not None:
        since = parse_created_after(created_after)
        jobs = [j for j in jobs if date.fromisoformat(j["created_at"][:10]) >= since]
    if status is not None:
        jobs = [j for j in jobs if j["status"] == status.value]
    if client_id is not None:
        jobs = [j for j in jobs if j["client_id"] == client_id]
    jobs = sorted(jobs, key=lambda j: j["created_at"], reverse=sort == JobSort.newest_first)
    return paginate(jobs, page, page_size)


@router.get(
    "/{job_id}",
    response_model=ImportJob,
    summary="Get one import job",
    description="Returns a single import job by id, including jobs created with POST. "
                "An unknown id returns 404 `job_not_found`.",
    responses=v1_responses(404),
    dependencies=[Depends(require_api_key)],
)
async def get_import_job(request: Request, job_id: str = Path(description="Import job id.", examples=["IMP-2001"])):
    job = IMPORT_JOBS_BY_ID.get(job_id) or request.app.state.posted_jobs.jobs.get(job_id)
    if job is None:
        raise APIError(404, "job_not_found", f"No import job with id {job_id}")
    return job


@router.post(
    "",
    status_code=201,
    response_model=ImportJob,
    summary="Create an import job",
    description=(
        "Queues a new import job for a client and returns it with status `queued`. "
        "The `Location` header gives the new job's URL. Needs a read-write key: a read-only "
        "key returns 403 `forbidden`. An unknown `client_id` returns 404 `client_not_found`. "
        "Created jobs can be fetched by id but do not appear in the job list."
    ),
    responses=v1_responses(403, 404, success=201, success_headers={
        "Location": {"description": "URL of the new job.", "schema": {"type": "string",
                                                                     "example": "/v1/import-jobs/IMP-9001"}},
    }),
    dependencies=[Depends(require_write)],
)
async def create_import_job(body: ImportJobCreate, request: Request, response: Response):
    get_client_or_404(body.client_id)
    job = request.app.state.posted_jobs.add(body.client_id, body.file_name)
    response.headers["Location"] = f"/v1/import-jobs/{job['id']}"
    return job
