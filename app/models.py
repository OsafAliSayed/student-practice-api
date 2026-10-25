"""Pydantic response models. These are what /docs and openapi.json describe."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str = Field(description="Machine-readable error code.", examples=["client_not_found"])
    message: str = Field(description="Human-readable explanation.", examples=["No client with id CL-009"])
    request_id: str = Field(description="Same value as the X-Request-ID response header.",
                            examples=["req_483920"])


class ErrorResponse(BaseModel):
    """Envelope used by every error except 422 validation errors."""

    error: ErrorBody


class Health(BaseModel):
    status: Literal["ok"]


# ---------------------------------------------------------------------- clients

class Contact(BaseModel):
    name: str
    email: str


class Client(BaseModel):
    id: str = Field(examples=["CL-001"])
    name: str
    plan: str = Field(description="Subscription plan.", examples=["Enterprise"])
    contact: Contact
    tags: list[str]
    notes: str | None
    created_at: str = Field(description="ISO 8601, UTC.", examples=["2025-02-11T09:00:00Z"])


class ClientList(BaseModel):
    data: list[Client]


# ------------------------------------------------------------------ import jobs

class JobStatus(str, Enum):
    succeeded = "succeeded"
    failed = "failed"
    running = "running"
    queued = "queued"


class JobSort(str, Enum):
    oldest_first = "created_at"
    newest_first = "-created_at"


class ImportJobError(BaseModel):
    code: str = Field(examples=["missing_column"])
    message: str
    row: int = Field(description="Row number in the uploaded file where the import stopped.")


class ImportJob(BaseModel):
    id: str = Field(examples=["IMP-2001"])
    client_id: str
    file_name: str
    status: JobStatus
    rows_total: int | None = Field(description="Rows in the file; null until the file has been read.")
    rows_loaded: int
    created_at: str = Field(description="ISO 8601, UTC.")
    finished_at: str | None = Field(description="ISO 8601, UTC. Null unless succeeded or failed.")
    error: ImportJobError | None = Field(description="Null unless the job failed.")


class ImportJobCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"client_id": "CL-001", "file_name": "contacts_nov.csv"}]})

    client_id: str = Field(description="The client the file belongs to.")
    file_name: str = Field(description="Name of the file to import.")


class Page(BaseModel):
    page: int
    page_size: int
    total: int = Field(description="Number of items matching the filters, across all pages.")
    total_pages: int


class ImportJobPage(Page):
    data: list[ImportJob]


# ---------------------------------------------------------------------- records

class RecordSource(BaseModel):
    system: Literal["csv_upload", "crm_sync", "api"]
    file_name: str | None = Field(description="Set only when system is csv_upload.")


class Record(BaseModel):
    id: str = Field(examples=["REC-0001"])
    client_id: str
    type: Literal["contact", "company", "deal"]
    contact_email: str | None
    updated_at: str = Field(description="When the record last changed, as received from the source system.")
    source: RecordSource


class RecordPage(Page):
    data: list[Record]


# ------------------------------------------------------------------ sync errors

class SyncErrorCode(str, Enum):
    crm_auth_expired = "crm_auth_expired"
    rate_limited = "rate_limited"
    timeout = "timeout"


class SyncError(BaseModel):
    id: str = Field(examples=["SE-0001"])
    client_id: str
    code: SyncErrorCode
    message: str
    occurred_at: str = Field(description="ISO 8601, UTC.")
    resolved: bool


class SyncErrorPage(Page):
    data: list[SyncError]


# ---------------------------------------------------------------------- reports

class MonthlyReport(BaseModel):
    client_id: str
    client_name: str
    month: str = Field(examples=["2026-09"])
    imports_total: int
    imports_succeeded: int
    imports_failed: int
    rows_loaded: int
    sync_errors: int
