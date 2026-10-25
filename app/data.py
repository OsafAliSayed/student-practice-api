"""Deterministic seed data.

Every dataset is built from explicit counts first (lists of labels that add up to the
required totals), then shuffled and decorated with a dedicated random.Random(42).
Faker (seeded 42) only supplies names, emails and filler file names. No timestamp
depends on the current time. The checks at the bottom run on import: if any count is
off, the import fails and the app does not start.
"""

import random
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from faker import Faker

rng = random.Random(42)
fake = Faker("en_US")
fake.seed_instance(42)

UTC = timezone.utc
SEED_START = datetime(2026, 9, 1, tzinfo=UTC)
SEED_END = datetime(2026, 10, 14, 23, 59, 59, tzinfo=UTC)


def _require(condition: bool, message: str) -> None:
    # Explicit raise rather than `assert`, so the checks survive `python -O`.
    if not condition:
        raise AssertionError(f"seed data check failed: {message}")


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _expand(counts: dict[str, int]) -> list[str]:
    return [label for label, n in counts.items() for _ in range(n)]


def _random_minute(start: datetime = SEED_START, days: int = 44) -> datetime:
    return start + timedelta(minutes=rng.randrange(days * 24 * 60))


# --------------------------------------------------------------------------- clients

CLIENT_ROWS = [
    ("CL-001", "Bluepeak Health", "Enterprise", ["priority", "renewal"], None, "2025-02-11T09:00:00Z"),
    ("CL-002", "Orchard Retail", "Growth", ["retail"], "Prefers email over phone.", "2025-03-04T14:30:00Z"),
    ("CL-003", "Kestrel Finance", "Enterprise", ["priority"], None, "2025-05-19T10:15:00Z"),
    ("CL-004", "Lumen Education", "Starter", [], None, "2025-07-08T08:45:00Z"),
    ("CL-005", "Northwind Logistics", "Growth", ["renewal"], None, "2025-09-22T16:00:00Z"),
]

CLIENTS = [
    {
        "id": cid,
        "name": name,
        "plan": plan,
        "contact": {"name": fake.name(), "email": fake.safe_email()},
        "tags": tags,
        "notes": notes,
        "created_at": created_at,
    }
    for cid, name, plan, tags, notes, created_at in CLIENT_ROWS
]
CLIENTS_BY_ID = {c["id"]: c for c in CLIENTS}
CLIENT_IDS = list(CLIENTS_BY_ID)

# ----------------------------------------------------------------------- import jobs

JOB_TOTALS_BY_CLIENT = {"CL-001": 34, "CL-002": 33, "CL-003": 31, "CL-004": 28, "CL-005": 24}
JOB_FAILED_BY_CLIENT = {"CL-001": 12, "CL-002": 10, "CL-003": 9, "CL-004": 7, "CL-005": 5}
JOB_STATUS_TOTALS = {"succeeded": 88, "failed": 43, "running": 11, "queued": 8}
JOB_ERROR_CODE_TOTALS = {
    "date_parse_error": 15,
    "missing_column": 11,
    "file_too_large": 7,
    "duplicate_rows": 6,
    "timeout": 4,
}
FIXED_JOB_ID = "IMP-2114"
FIXED_JOB_CLIENT = "CL-004"
FIXED_JOB_ERROR = {"code": "date_parse_error", "message": "date '31/13/2026' could not be parsed", "row": 214}

BAD_DATES = ["2026-02-30", "13/31/2026", "32/09/2026", "Sept 31 2026", "00/10/2026", "2026/10/7"]
MISSING_COLUMNS = ["email", "first_name", "company_id", "created_date", "country"]


def _build_import_jobs() -> list[dict]:
    # 1. One (client, status) slot per job, straight from the count tables.
    failed = [(c, "failed") for c in _expand(JOB_FAILED_BY_CLIENT)]
    not_failed = _expand({c: JOB_TOTALS_BY_CLIENT[c] - JOB_FAILED_BY_CLIENT[c] for c in CLIENT_IDS})
    rng.shuffle(not_failed)
    n_run, n_queue = JOB_STATUS_TOTALS["running"], JOB_STATUS_TOTALS["queued"]
    pending = [(c, "running") for c in not_failed[:n_run]]
    pending += [(c, "queued") for c in not_failed[n_run:n_run + n_queue]]
    succeeded = [(c, "succeeded") for c in not_failed[n_run + n_queue:]]

    # 2. Finished jobs take the older ids, pending (running/queued) the newest.
    finished = failed + succeeded
    rng.shuffle(finished)
    rng.shuffle(pending)
    fixed_index = int(FIXED_JOB_ID.split("-")[1]) - 2001
    if finished[fixed_index] != (FIXED_JOB_CLIENT, "failed"):
        swap = next(i for i, s in enumerate(finished) if s == (FIXED_JOB_CLIENT, "failed"))
        finished[fixed_index], finished[swap] = finished[swap], finished[fixed_index]
    slots = finished + pending

    # 3. Error codes for the failed slots, with the fixed job pinned to date_parse_error.
    codes = _expand(JOB_ERROR_CODE_TOTALS)
    rng.shuffle(codes)
    failed_indices = [i for i, (_, status) in enumerate(slots) if status == "failed"]
    code_for = dict(zip(failed_indices, codes))
    if code_for[fixed_index] != "date_parse_error":
        swap = next(i for i in failed_indices if code_for[i] == "date_parse_error" and i != fixed_index)
        code_for[fixed_index], code_for[swap] = code_for[swap], code_for[fixed_index]

    # 4. Details. Finished jobs: 1 Sep – 8 Oct, 7 h apart; pending: 10 – 14 Oct, 6 h apart.
    jobs = []
    for i, (client_id, status) in enumerate(slots):
        if i < len(finished):
            created = datetime(2026, 9, 1, 8, tzinfo=UTC) + timedelta(hours=7 * i, minutes=rng.randint(0, 120))
        else:
            k = i - len(finished)
            created = datetime(2026, 10, 10, 6, tzinfo=UTC) + timedelta(hours=6 * k, minutes=rng.randint(0, 59))
        job = {
            "id": f"IMP-{2001 + i}",
            "client_id": client_id,
            "file_name": f"{fake.word()}_{created.strftime('%b').lower()}.csv",
            "status": status,
            "rows_total": rng.randint(120, 4800),
            "rows_loaded": 0,
            "created_at": iso(created),
            "finished_at": None,
            "error": None,
        }
        if status == "succeeded":
            job["rows_loaded"] = job["rows_total"]
            job["finished_at"] = iso(created + timedelta(minutes=rng.randint(2, 45)))
        elif status == "failed":
            job["error"] = _job_error(code_for[i], job["rows_total"])
            job["finished_at"] = iso(created + timedelta(minutes=30 if code_for[i] == "timeout" else rng.randint(1, 20)))
        elif status == "running":
            job["rows_loaded"] = rng.randint(0, job["rows_total"] - 1)
        else:  # queued: nothing read yet
            job["rows_total"] = None

        if job["id"] == FIXED_JOB_ID:
            job["file_name"] = "students_oct.csv"
            job["rows_total"] = rng.randint(400, 1500)
            job["error"] = dict(FIXED_JOB_ERROR)
        if status == "failed":
            job["rows_loaded"] = job["error"]["row"] - 1  # loaded everything before the bad row
        jobs.append(job)
    return jobs


def _job_error(code: str, rows_total: int) -> dict:
    row = rng.randint(1, rows_total)
    if code == "date_parse_error":
        message = f"date '{rng.choice(BAD_DATES)}' could not be parsed"
    elif code == "missing_column":
        row = 1
        message = f"required column '{rng.choice(MISSING_COLUMNS)}' is missing"
    elif code == "file_too_large":
        row = 1
        message = "file is larger than the 50 MB limit"
    elif code == "duplicate_rows":
        message = f"row {row} duplicates an earlier row"
    else:
        message = "import did not finish within 30 minutes"
    return {"code": code, "message": message, "row": row}


IMPORT_JOBS = _build_import_jobs()
IMPORT_JOBS_BY_ID = {j["id"]: j for j in IMPORT_JOBS}

# --------------------------------------------------------------------------- records

RECORD_TOTALS_BY_CLIENT = {"CL-001": 110, "CL-002": 100, "CL-003": 95, "CL-004": 80, "CL-005": 65}
RECORD_FORMAT_TOTALS = {"iso": 300, "dmy": 90, "mon": 59}
RECORD_NULL_EMAILS = 36
BAD_RECORD_ID = "REC-0337"
BAD_RECORD_CLIENT = "CL-002"
BAD_RECORD_UPDATED_AT = "31/13/2026"
RECORD_TYPES = ["contact", "company", "deal"]
SOURCE_SYSTEMS = ["csv_upload", "crm_sync", "api"]

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DMY_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MON_RE = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$")


def _format_date(dt: datetime, fmt: str) -> str:
    if fmt == "iso":
        return iso(dt)
    if fmt == "dmy":
        return dt.strftime("%d/%m/%Y")
    return f"{dt:%b} {dt.day}, {dt.year}"


def _build_records() -> list[dict]:
    total = sum(RECORD_TOTALS_BY_CLIENT.values())
    bad_index = int(BAD_RECORD_ID.split("-")[1]) - 1

    clients = _expand(RECORD_TOTALS_BY_CLIENT)
    rng.shuffle(clients)
    if clients[bad_index] != BAD_RECORD_CLIENT:
        swap = next(i for i, c in enumerate(clients) if c == BAD_RECORD_CLIENT)
        clients[bad_index], clients[swap] = clients[swap], clients[bad_index]

    formats = _expand(RECORD_FORMAT_TOTALS)
    rng.shuffle(formats)
    formats.insert(bad_index, "bad")

    null_emails = set(rng.sample([i for i in range(total) if i != bad_index], RECORD_NULL_EMAILS))
    first_dmy = formats.index("dmy")

    records = []
    for i in range(total):
        if formats[i] == "bad":
            updated_at = BAD_RECORD_UPDATED_AT
        elif i == first_dmy:
            updated_at = "05/09/2026"  # guaranteed ambiguous example: 5 Sep or 9 May?
        else:
            updated_at = _format_date(_random_minute(), formats[i])
        system = rng.choice(SOURCE_SYSTEMS)
        records.append({
            "id": f"REC-{i + 1:04d}",
            "client_id": clients[i],
            "type": rng.choice(RECORD_TYPES),
            "contact_email": None if i in null_emails else fake.safe_email(),
            "updated_at": updated_at,
            "source": {
                "system": system,
                "file_name": fake.file_name(extension="csv") if system == "csv_upload" else None,
            },
        })
    return records


RECORDS = _build_records()  # sorted by id

# ----------------------------------------------------------------------- sync errors

SYNC_TOTALS_BY_CLIENT = {"CL-001": 18, "CL-002": 14, "CL-003": 12, "CL-004": 9, "CL-005": 7}
SYNC_CODE_TOTALS = {"crm_auth_expired": 24, "rate_limited": 21, "timeout": 15}
SYNC_RESOLVED = 20  # a third of 60
SYNC_MESSAGES = {
    "crm_auth_expired": "CRM credentials expired. Reconnect the CRM integration to resume syncing.",
    "rate_limited": "The CRM rejected the sync because its API rate limit was reached.",
    "timeout": "The CRM did not respond within 30 seconds.",
}


def _build_sync_errors() -> list[dict]:
    clients = _expand(SYNC_TOTALS_BY_CLIENT)
    codes = _expand(SYNC_CODE_TOTALS)
    rng.shuffle(clients)
    rng.shuffle(codes)
    total = len(clients)
    minutes = sorted(rng.sample(range(44 * 24 * 60), total))  # distinct, so the sort is stable
    resolved = set(rng.sample(range(total), SYNC_RESOLVED))
    errors = [
        {
            "id": f"SE-{i + 1:04d}",
            "client_id": clients[i],
            "code": codes[i],
            "message": SYNC_MESSAGES[codes[i]],
            "occurred_at": iso(SEED_START + timedelta(minutes=minutes[i])),
            "resolved": i in resolved,
        }
        for i in range(total)
    ]
    return sorted(errors, key=lambda e: e["occurred_at"], reverse=True)


SYNC_ERRORS = _build_sync_errors()  # sorted by occurred_at, newest first

# -------------------------------------------------------------------- startup checks


def _check_import_jobs() -> None:
    jobs = IMPORT_JOBS
    _require(len(jobs) == 150, "150 import jobs")
    _require([j["id"] for j in jobs] == [f"IMP-{n}" for n in range(2001, 2151)], "ids IMP-2001..IMP-2150")
    _require(Counter(j["client_id"] for j in jobs) == JOB_TOTALS_BY_CLIENT, "jobs per client")
    _require(Counter(j["client_id"] for j in jobs if j["status"] == "failed") == JOB_FAILED_BY_CLIENT,
             "failed jobs per client")
    _require(Counter(j["status"] for j in jobs) == JOB_STATUS_TOTALS, "status totals")
    _require(Counter(j["error"]["code"] for j in jobs if j["error"]) == JOB_ERROR_CODE_TOTALS,
             "error code totals")

    created = {j["id"]: parse_iso(j["created_at"]) for j in jobs}
    _require(all(SEED_START <= t <= SEED_END for t in created.values()), "jobs created 1 Sep - 14 Oct")
    pending = [j for j in jobs if j["status"] in ("running", "queued")]
    finished = [j for j in jobs if j["status"] in ("succeeded", "failed")]
    _require(all(datetime(2026, 10, 10, tzinfo=UTC) <= created[j["id"]] for j in pending),
             "running/queued created 10-14 Oct")
    _require(max(created[j["id"]] for j in finished) < min(created[j["id"]] for j in pending),
             "running/queued are the most recent")
    _require(len(set(created.values())) == len(jobs), "distinct created_at")

    for j in jobs:
        done = j["status"] in ("succeeded", "failed")
        _require((j["finished_at"] is not None) == done, f"{j['id']} finished_at")
        _require((j["error"] is not None) == (j["status"] == "failed"), f"{j['id']} error")
        if j["status"] == "failed":
            _require(j["rows_loaded"] < j["rows_total"], f"{j['id']} rows_loaded < rows_total")
            _require(1 <= j["error"]["row"] <= j["rows_total"], f"{j['id']} error.row <= rows_total")

    fixed = IMPORT_JOBS_BY_ID[FIXED_JOB_ID]
    _require(fixed["client_id"] == FIXED_JOB_CLIENT and fixed["status"] == "failed", "fixed job client/status")
    _require(fixed["file_name"] == "students_oct.csv", "fixed job file name")
    _require(fixed["error"] == FIXED_JOB_ERROR and fixed["rows_total"] >= 214, "fixed job error")


def _check_records() -> None:
    recs = RECORDS
    _require(len(recs) == 450, "450 records")
    _require([r["id"] for r in recs] == [f"REC-{n:04d}" for n in range(1, 451)], "ids REC-0001..REC-0450")
    _require(Counter(r["client_id"] for r in recs) == RECORD_TOTALS_BY_CLIENT, "records per client")

    bad = next(r for r in recs if r["id"] == BAD_RECORD_ID)
    _require(bad["client_id"] == BAD_RECORD_CLIENT, "bad record client")
    _require(bad["updated_at"] == BAD_RECORD_UPDATED_AT, "bad record updated_at")
    _require(bad["contact_email"] is not None, "bad record has an email")
    _require(sum(r["contact_email"] is None for r in recs) == RECORD_NULL_EMAILS, "36 null emails")

    others = [r["updated_at"] for r in recs if r["id"] != BAD_RECORD_ID]
    iso_dates = [v for v in others if ISO_RE.match(v)]
    dmy_dates = [v for v in others if DMY_RE.match(v)]
    mon_dates = [v for v in others if MON_RE.match(v)]
    _require((len(iso_dates), len(dmy_dates), len(mon_dates)) == (300, 90, 59), "updated_at format counts")
    _require(sum(int(v[:2]) <= 12 for v in dmy_dates) >= 5 and "05/09/2026" in dmy_dates,
             "ambiguous DD/MM/YYYY dates")
    parsed = ([parse_iso(v).date() for v in iso_dates]
              + [datetime.strptime(v, "%d/%m/%Y").date() for v in dmy_dates]
              + [datetime.strptime(v, "%b %d, %Y").date() for v in mon_dates])
    _require(all(date(2026, 9, 1) <= d <= date(2026, 10, 14) for d in parsed), "record dates 1 Sep - 14 Oct")

    for r in recs:
        _require(r["type"] in RECORD_TYPES, f"{r['id']} type")
        _require(r["source"]["system"] in SOURCE_SYSTEMS, f"{r['id']} source.system")
        _require((r["source"]["file_name"] is not None) == (r["source"]["system"] == "csv_upload"),
                 f"{r['id']} source.file_name")


def _check_sync_errors() -> None:
    errs = SYNC_ERRORS
    _require(len(errs) == 60, "60 sync errors")
    _require(sorted(e["id"] for e in errs) == [f"SE-{n:04d}" for n in range(1, 61)], "ids SE-0001..SE-0060")
    _require(Counter(e["client_id"] for e in errs) == SYNC_TOTALS_BY_CLIENT, "sync errors per client")
    _require(Counter(e["code"] for e in errs) == SYNC_CODE_TOTALS, "sync error codes")
    _require(all(SEED_START <= parse_iso(e["occurred_at"]) <= SEED_END for e in errs), "occurred_at range")
    _require(sum(e["resolved"] for e in errs) == SYNC_RESOLVED, "a third resolved")


_require(len(CLIENTS) == 5 and CLIENT_IDS == [f"CL-00{n}" for n in range(1, 6)], "5 clients")
_check_import_jobs()
_check_records()
_check_sync_errors()
