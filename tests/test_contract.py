"""Contract tests: run locally against the app with FastAPI's TestClient.

Every number checked here is something course material depends on. Data is read
through the API, never from app.data.
"""

import os

os.environ["SLOW_REPORT_SECONDS"] = "0.1"
os.environ["REPORT_SECONDS"] = "0.01"
os.environ.pop("PUBLIC_BASE_URL", None)

from collections import Counter  # noqa: E402
from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

RW = {"X-API-Key": "demo_key_rw_4K9P"}
RO = {"X-API-Key": "demo_key_ro_7M2Q"}
INST = {"X-API-Key": "demo_key_rw_inst_5H8D"}
EXPIRED = {"X-API-Key": "demo_key_expired_1X0Z"}
CLIENT_IDS = ["CL-001", "CL-002", "CL-003", "CL-004", "CL-005"]


@pytest.fixture
def client():
    """A fresh app per test, so rate-limit windows and POSTed jobs start empty."""
    return TestClient(create_app())


@pytest.fixture
def bulk():
    """For reading whole datasets: same app, but a limit high enough not to get in the way."""
    return TestClient(create_app(rate_limit=100_000))


def get_ok(c, url, headers=RW):
    r = c.get(url, headers=headers)
    assert r.status_code == 200, (url, r.status_code, r.text)
    return r.json()


def fetch_all(c, url):
    items, page = [], 1
    while True:
        body = get_ok(c, f"{url}{'&' if '?' in url else '?'}page={page}&page_size=100")
        items += body["data"]
        if page >= body["total_pages"]:
            return items
        page += 1


def total(c, url):
    # A page past the end returns 200 with the total, without loading any items.
    return get_ok(c, f"{url}{'&' if '?' in url else '?'}page=1000")["total"]


def assert_envelope(r, status, code):
    assert r.status_code == status, r.text
    err = r.json()["error"]
    assert err["code"] == code
    assert err["message"]
    assert err["request_id"] == r.headers["X-Request-ID"]


# ---------------------------------------------------------------------- seed counts

def test_clients(bulk):
    body = get_ok(bulk, "/v1/clients")
    assert [c["id"] for c in body["data"]] == CLIENT_IDS
    assert set(body) == {"data"}  # not paginated
    by_id = {c["id"]: c for c in body["data"]}
    expected = {
        "CL-001": ("Bluepeak Health", "Enterprise", ["priority", "renewal"], None),
        "CL-002": ("Orchard Retail", "Growth", ["retail"], "Prefers email over phone."),
        "CL-003": ("Kestrel Finance", "Enterprise", ["priority"], None),
        "CL-004": ("Lumen Education", "Starter", [], None),
        "CL-005": ("Northwind Logistics", "Growth", ["renewal"], None),
    }
    for cid, (name, plan, tags, notes) in expected.items():
        c = by_id[cid]
        assert (c["name"], c["plan"], c["tags"], c["notes"]) == (name, plan, tags, notes)
        assert set(c["contact"]) == {"name", "email"}
        assert c["created_at"].startswith("2025-")
    assert get_ok(bulk, "/v1/clients/CL-001") == by_id["CL-001"]


def test_import_job_counts(bulk):
    jobs = fetch_all(bulk, "/v1/import-jobs?sort=created_at")
    assert len(jobs) == 150
    assert sorted(j["id"] for j in jobs) == [f"IMP-{n}" for n in range(2001, 2151)]
    assert Counter(j["client_id"] for j in jobs) == {"CL-001": 34, "CL-002": 33, "CL-003": 31,
                                                      "CL-004": 28, "CL-005": 24}
    assert Counter(j["client_id"] for j in jobs if j["status"] == "failed") == {
        "CL-001": 12, "CL-002": 10, "CL-003": 9, "CL-004": 7, "CL-005": 5}
    assert Counter(j["status"] for j in jobs) == {"succeeded": 88, "failed": 43, "running": 11, "queued": 8}
    assert Counter(j["error"]["code"] for j in jobs if j["status"] == "failed") == {
        "date_parse_error": 15, "missing_column": 11, "file_too_large": 7, "duplicate_rows": 6, "timeout": 4}

    # The same totals through the filters, as students will see them.
    assert total(bulk, "/v1/import-jobs") == 150
    for cid, n in {"CL-001": 34, "CL-002": 33, "CL-003": 31, "CL-004": 28, "CL-005": 24}.items():
        assert total(bulk, f"/v1/import-jobs?client_id={cid}") == n
    for status, n in {"succeeded": 88, "failed": 43, "running": 11, "queued": 8}.items():
        assert total(bulk, f"/v1/import-jobs?status={status}") == n


def test_import_job_shapes_and_dates(bulk):
    jobs = fetch_all(bulk, "/v1/import-jobs?sort=created_at")
    created = [datetime.fromisoformat(j["created_at"]) for j in jobs]
    assert all("2026-09-01" <= j["created_at"][:10] <= "2026-10-14" for j in jobs)
    assert created == sorted(created)

    pending = [j for j in jobs if j["status"] in ("running", "queued")]
    finished = [j for j in jobs if j["status"] in ("succeeded", "failed")]
    assert all("2026-10-10" <= j["created_at"][:10] <= "2026-10-14" for j in pending)
    assert max(j["created_at"] for j in finished) < min(j["created_at"] for j in pending)

    for j in jobs:
        assert (j["finished_at"] is not None) == (j["status"] in ("succeeded", "failed"))
        assert (j["error"] is not None) == (j["status"] == "failed")
        if j["status"] == "failed":
            assert j["rows_loaded"] < j["rows_total"]
            assert j["error"]["row"] <= j["rows_total"]


def test_fixed_job_imp_2114(bulk):
    job = get_ok(bulk, "/v1/import-jobs/IMP-2114")
    assert job["client_id"] == "CL-004"
    assert job["file_name"] == "students_oct.csv"
    assert job["status"] == "failed"
    assert job["error"] == {"code": "date_parse_error", "message": "date '31/13/2026' could not be parsed",
                            "row": 214}
    assert job["rows_total"] >= 214


def test_import_job_pagination_and_filters(bulk):
    body = get_ok(bulk, "/v1/import-jobs?status=failed")
    assert (body["total"], body["total_pages"], body["page_size"], len(body["data"])) == (43, 3, 20, 20)
    body = get_ok(bulk, "/v1/import-jobs?client_id=CL-001")
    assert (body["total"], body["total_pages"]) == (34, 2)
    body = get_ok(bulk, "/v1/import-jobs?status=failed&page=9")
    assert body["data"] == [] and body["total"] == 43
    body = get_ok(bulk, "/v1/import-jobs?client_id=CL-999")
    assert (body["data"], body["total"], body["total_pages"]) == ([], 0, 0)

    newest = get_ok(bulk, "/v1/import-jobs")["data"]
    assert newest[0]["id"] == "IMP-2150"
    assert get_ok(bulk, "/v1/import-jobs?sort=created_at")["data"][0]["id"] == "IMP-2001"

    since = fetch_all(bulk, "/v1/import-jobs?created_after=2026-10-01")
    everything = fetch_all(bulk, "/v1/import-jobs")
    assert len(since) == sum(j["created_at"][:10] >= "2026-10-01" for j in everything)
    assert all(j["created_at"][:10] >= "2026-10-01" for j in since)


def test_record_counts(bulk):
    # REC-0337's page always fails, so read around it: pages of 100 except page 4,
    # and records 301-400 one at a time, skipping 337.
    records = []
    for page in (1, 2, 3, 5):
        records += get_ok(bulk, f"/v1/records?page={page}&page_size=100")["data"]
    for n in range(301, 401):
        if n != 337:
            records += get_ok(bulk, f"/v1/records?page={n}&page_size=1")["data"]
    records.sort(key=lambda r: r["id"])

    assert [r["id"] for r in records] == [f"REC-{n:04d}" for n in range(1, 451) if n != 337]
    assert total(bulk, "/v1/records") == 450
    for cid, n in {"CL-001": 110, "CL-002": 100, "CL-003": 95, "CL-004": 80, "CL-005": 65}.items():
        assert total(bulk, f"/v1/records?client_id={cid}") == n
    visible = Counter(r["client_id"] for r in records)
    assert visible == {"CL-001": 110, "CL-002": 99, "CL-003": 95, "CL-004": 80, "CL-005": 65}  # 337 is CL-002

    assert sum(r["contact_email"] is None for r in records) == 36  # all 36 nulls are outside REC-0337

    def fmt(value):
        for name, pattern in (("iso", "%Y-%m-%dT%H:%M:%SZ"), ("dmy", "%d/%m/%Y"), ("mon", "%b %d, %Y")):
            try:
                return name, datetime.strptime(value, pattern).date()
            except ValueError:
                pass
        raise AssertionError(f"unexpected updated_at {value!r}")

    parsed = [fmt(r["updated_at"]) for r in records]
    assert Counter(name for name, _ in parsed) == {"iso": 300, "dmy": 90, "mon": 59}
    assert all("2026-09-01" <= d.isoformat() <= "2026-10-14" for _, d in parsed)
    dmy = [r["updated_at"] for r in records if fmt(r["updated_at"])[0] == "dmy"]
    assert "05/09/2026" in dmy and sum(int(v[:2]) <= 12 for v in dmy) >= 5

    for r in records:
        assert r["type"] in ("contact", "company", "deal")
        assert r["source"]["system"] in ("csv_upload", "crm_sync", "api")
        assert (r["source"]["file_name"] is not None) == (r["source"]["system"] == "csv_upload")


def test_sync_error_counts(bulk):
    errors = fetch_all(bulk, "/v1/sync-errors")
    assert sorted(e["id"] for e in errors) == [f"SE-{n:04d}" for n in range(1, 61)]
    assert Counter(e["client_id"] for e in errors) == {"CL-001": 18, "CL-002": 14, "CL-003": 12,
                                                        "CL-004": 9, "CL-005": 7}
    assert Counter(e["code"] for e in errors) == {"crm_auth_expired": 24, "rate_limited": 21, "timeout": 15}
    assert [e["occurred_at"] for e in errors] == sorted((e["occurred_at"] for e in errors), reverse=True)
    assert all("2026-09-01" <= e["occurred_at"][:10] <= "2026-10-14" for e in errors)
    assert sum(e["resolved"] for e in errors) == 20
    assert total(bulk, "/v1/sync-errors?code=timeout") == 15
    assert total(bulk, "/v1/sync-errors?client_id=CL-004") == 9


# ------------------------------------------------------------------ the planted 500

def test_rec_0337_page_maths(client):
    for url in ("/v1/records?page=7", "/v1/records?page=4&page_size=100"):
        assert_envelope(client.get(url, headers=RW), 500, "internal_error")
    for url in ("/v1/records?page=6", "/v1/records?page=8"):
        assert client.get(url, headers=RW).status_code == 200


def test_rec_0337_fails_client_filter(bulk):
    statuses = [bulk.get(f"/v1/records?client_id=CL-002&page={p}&page_size=10", headers=RW).status_code
                for p in range(1, 11)]
    assert statuses.count(500) == 1 and statuses.count(200) == 9
    for cid in ("CL-001", "CL-003", "CL-004", "CL-005"):
        fetch_all(bulk, f"/v1/records?client_id={cid}")


def test_500_message_and_headers(client):
    r = client.get("/v1/records?page=7", headers=RW)
    assert r.json()["error"]["message"] == ("Something went wrong on our side. "
                                            "Quote the request ID when you contact support.")
    assert r.headers["X-RateLimit-Limit"] == "30"
    assert "X-RateLimit-Remaining" in r.headers


# -------------------------------------------------------------------- auth and keys

@pytest.mark.parametrize("headers, code, message", [
    ({}, "missing_api_key", "Send your API key in the X-API-Key header."),
    ({"X-API-Key": "nope"}, "invalid_api_key", "This API key is not valid."),
    (EXPIRED, "api_key_expired", "API key expired on 2026-10-01. Generate a new key."),
])
def test_401s(client, headers, code, message):
    r = client.get("/v1/clients", headers=headers)
    assert_envelope(r, 401, code)
    assert r.json()["error"]["message"] == message
    assert "X-RateLimit-Limit" not in r.headers


def test_valid_keys(client):
    for headers in (RW, RO, INST):
        assert client.get("/v1/clients", headers=headers).status_code == 200


def test_no_key_needed_for_docs(client):
    for url in ("/health", "/docs", "/redoc", "/openapi.json"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["X-Request-ID"].startswith("req_")
    assert client.get("/health").json() == {"status": "ok"}
    assert "X-RateLimit-Limit" not in client.get("/health").headers


# ----------------------------------------------------------------------- precedence

def test_precedence_401_before_422(client):
    assert_envelope(client.get("/v1/import-jobs?page_size=500"), 401, "missing_api_key")


def test_precedence_403_before_422(client):
    r = client.post("/v1/import-jobs", headers=RO)
    assert_envelope(r, 403, "forbidden")
    assert r.json()["error"]["message"] == "This API key is read-only"


def test_precedence_429_before_403(client):
    for _ in range(30):
        client.get("/v1/clients", headers=RO)
    assert_envelope(client.post("/v1/import-jobs", headers=RO, json={}), 429, "rate_limited")


def test_precedence_400_before_404_on_reports(client):
    assert_envelope(client.get("/v1/reports/monthly?client_id=CL-999&month=2026-13", headers=RW),
                    400, "invalid_month")


# ----------------------------------------------------------------------- error shapes

def test_error_shapes(client):
    r = client.get("/v1/import-jobs?page_size=500", headers=RW)
    assert r.status_code == 422 and "detail" in r.json() and "error" not in r.json()
    assert client.get("/v1/import-jobs?status=done", headers=RW).status_code == 422
    assert client.get("/v1/import-jobs?sort=name", headers=RW).status_code == 422
    assert client.get("/v1/records?page=0", headers=RW).status_code == 422

    assert_envelope(client.get("/v1/clients/CL-009", headers=RW), 404, "client_not_found")
    assert client.get("/v1/clients/CL-009", headers=RW).json()["error"]["message"] == "No client with id CL-009"
    assert_envelope(client.get("/v1/import-jobs/IMP-1234", headers=RW), 404, "job_not_found")

    r = client.get("/v1/import-jobs?created_after=31/13/2026", headers=RW)
    assert_envelope(r, 400, "invalid_date")
    assert r.json()["error"]["message"] == \
        "created_after must be a date in YYYY-MM-DD format, got '31/13/2026'"
    assert_envelope(client.get("/v1/import-jobs?created_after=2026-02-30", headers=RW), 400, "invalid_date")

    r = client.get("/v1/reports/monthly?client_id=CL-001&month=2026-9", headers=RW)
    assert_envelope(r, 400, "invalid_month")
    assert r.json()["error"]["message"] == "month must be in YYYY-MM format, got '2026-9'"
    assert_envelope(client.get("/v1/reports/monthly?client_id=CL-009&month=2026-09", headers=RW),
                    404, "client_not_found")


def test_unknown_route_and_wrong_method(client):
    assert_envelope(client.get("/v1/nothing-here", headers=RW), 404, "not_found")
    assert_envelope(client.get("/nothing-here"), 404, "not_found")
    assert_envelope(client.delete("/v1/clients", headers=RW), 405, "method_not_allowed")


def test_request_id_everywhere(client):
    responses = {
        200: client.get("/v1/clients", headers=RW),
        401: client.get("/v1/clients"),
        404: client.get("/v1/clients/CL-009", headers=RW),
        422: client.get("/v1/import-jobs?page_size=500", headers=RW),
        500: client.get("/v1/records?page=7", headers=RW),
    }
    for _ in range(30):
        client.get("/v1/clients", headers=RW)
    responses[429] = client.get("/v1/clients", headers=RW)
    for status, r in responses.items():
        assert r.status_code == status
        rid = r.headers["X-Request-ID"]
        assert rid.startswith("req_") and len(rid) == 10 and rid[4:].isdigit()
    ids = [r.headers["X-Request-ID"] for r in responses.values()]
    assert len(set(ids)) == len(ids)


# ------------------------------------------------------------------------ rate limit

def test_rate_limit(client):
    remaining = []
    for _ in range(30):
        r = client.get("/v1/clients/CL-009", headers=RW)  # errors count too
        assert r.headers["X-RateLimit-Limit"] == "30"
        remaining.append(int(r.headers["X-RateLimit-Remaining"]))
    assert remaining == list(range(29, -1, -1))

    r = client.get("/v1/clients", headers=RW)
    assert_envelope(r, 429, "rate_limited")
    assert r.json()["error"]["message"] == \
        "Too many requests. Wait the number of seconds in Retry-After, then try again."
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert r.headers["X-RateLimit-Remaining"] == "0"

    # Each key has its own window; bad keys are never counted.
    assert client.get("/v1/clients", headers=INST).status_code == 200
    for _ in range(40):
        assert client.get("/v1/clients", headers=EXPIRED).status_code == 401


def test_limiter_window_slides():
    from app.ratelimit import SlidingWindowLimiter

    now = [1000.0]
    limiter = SlidingWindowLimiter(limit=30, window=60, clock=lambda: now[0])
    for i in range(30):
        now[0] = 1000.0 + i
        assert limiter.hit("rw").allowed
    now[0] = 1040.2
    d = limiter.hit("rw")
    assert not d.allowed and d.retry_after == 20  # oldest (t=1000) expires at 1060
    now[0] = 1060.0
    assert limiter.hit("rw").allowed
    assert not limiter.hit("rw").allowed
    now[0] = 1060.5
    assert limiter.hit("rw").retry_after == 1  # 0.5 s rounds up to 1
    now[0] = 1061.0
    assert limiter.hit("rw").allowed


# --------------------------------------------------------------------- POST jobs

def test_post_import_job(client):
    before = client.get("/v1/import-jobs", headers=RW).json()["total"]
    r = client.post("/v1/import-jobs", headers=RW, json={"client_id": "CL-001", "file_name": "contacts_nov.csv"})
    assert r.status_code == 201
    assert r.headers["Location"] == "/v1/import-jobs/IMP-9001"
    job = r.json()
    assert job["id"] == "IMP-9001"
    assert (job["status"], job["rows_total"], job["rows_loaded"], job["finished_at"], job["error"]) == \
        ("queued", None, 0, None, None)
    assert job["client_id"] == "CL-001" and job["file_name"] == "contacts_nov.csv"

    assert client.get("/v1/import-jobs/IMP-9001", headers=RW).json() == job
    assert client.get("/v1/import-jobs", headers=RW).json()["total"] == before == 150
    assert client.get("/v1/import-jobs?status=queued", headers=RW).json()["total"] == 8
    assert client.post("/v1/import-jobs", headers=INST,
                       json={"client_id": "CL-002", "file_name": "x.csv"}).json()["id"] == "IMP-9002"


def test_post_import_job_errors(client):
    assert_envelope(client.post("/v1/import-jobs", headers=RW, json={"client_id": "CL-009", "file_name": "a.csv"}),
                    404, "client_not_found")
    r = client.post("/v1/import-jobs", headers=RW, json={"client_id": "CL-001"})
    assert r.status_code == 422 and "detail" in r.json()


def test_posted_jobs_capped_at_200():
    from app.routers.import_jobs import PostedJobs

    store = PostedJobs()
    for _ in range(205):
        store.add("CL-001", "a.csv")
    assert len(store.jobs) == 200
    assert next(iter(store.jobs)) == "IMP-9006"


# ------------------------------------------------------------------------- reports

def test_monthly_report(bulk):
    jobs = fetch_all(bulk, "/v1/import-jobs?client_id=CL-003")
    errors = fetch_all(bulk, "/v1/sync-errors?client_id=CL-003")
    sept = [j for j in jobs if j["created_at"].startswith("2026-09")]
    report = get_ok(bulk, "/v1/reports/monthly?client_id=CL-003&month=2026-09")
    assert report == {
        "client_id": "CL-003",
        "client_name": "Kestrel Finance",
        "month": "2026-09",
        "imports_total": len(sept),
        "imports_succeeded": sum(j["status"] == "succeeded" for j in sept),
        "imports_failed": sum(j["status"] == "failed" for j in sept),
        "rows_loaded": sum(j["rows_loaded"] for j in sept),
        "sync_errors": sum(e["occurred_at"].startswith("2026-09") for e in errors),
    }
    empty = get_ok(bulk, "/v1/reports/monthly?client_id=CL-001&month=2025-01")
    assert [empty[k] for k in ("imports_total", "imports_succeeded", "imports_failed", "rows_loaded",
                               "sync_errors")] == [0, 0, 0, 0, 0]


def test_slow_report_does_not_block_other_requests():
    import asyncio

    import httpx

    async def run():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            loop = asyncio.get_running_loop()
            started = loop.time()
            slow = asyncio.create_task(ac.get("/v1/reports/monthly?client_id=CL-003&month=2026-09", headers=RW))
            await asyncio.sleep(0.01)
            fast = await ac.get("/health")
            fast_done = loop.time() - started
            assert fast.status_code == 200
            assert (await slow).status_code == 200
            assert fast_done < 0.1  # the slow report (0.1 s) was still sleeping

    asyncio.run(run())


# ------------------------------------------------------------------------- OpenAPI

def test_openapi_hides_the_planted_bugs(client):
    text = client.get("/openapi.json").text
    assert "REC-0337" not in text
    assert "31/13" not in text


def test_openapi_documents_the_api(client):
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Course Practice API"
    assert spec["info"]["version"] == "1.0.0"
    assert "servers" not in spec
    assert "ErrorResponse" in spec["components"]["schemas"]
    assert {t["name"] for t in spec["tags"]} == {"clients", "import-jobs", "records", "sync-errors",
                                                 "reports", "health"}
    scheme = next(iter(spec["components"]["securitySchemes"].values()))
    assert scheme == {**scheme, "type": "apiKey", "in": "header", "name": "X-API-Key"}

    expected_errors = {
        ("get", "/v1/clients"): {"401", "429"},
        ("get", "/v1/clients/{client_id}"): {"401", "429", "404"},
        ("get", "/v1/import-jobs"): {"401", "429", "400", "422"},
        ("post", "/v1/import-jobs"): {"401", "429", "403", "404", "422"},
        ("get", "/v1/import-jobs/{job_id}"): {"401", "429", "404"},
        ("get", "/v1/records"): {"401", "429", "500"},
        ("get", "/v1/sync-errors"): {"401", "429"},
        ("get", "/v1/reports/monthly"): {"401", "429", "400", "404"},
    }
    for (method, path), codes in expected_errors.items():
        op = spec["paths"][path][method]
        assert op["summary"] and op["description"]
        assert op.get("security"), path
        assert codes <= set(op["responses"]), (path, set(op["responses"]))
        for code in codes - {"422"}:
            ref = op["responses"][code]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorResponse")
        success = op["responses"]["201" if method == "post" else "200"]
        assert "X-Request-ID" in success["headers"]
    assert "security" not in spec["paths"]["/health"]["get"]


def test_openapi_servers_from_env(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.com")
    spec = TestClient(create_app()).get("/openapi.json").json()
    assert spec["servers"] == [{"url": "https://api.example.com"}]
