"""Smoke tests against a live deployment.

    BASE_URL=https://<live> pytest tests/test_smoke.py

Uses the instructor key so the student key's rate limit is untouched (one call uses the
student key). Takes about 1.5 minutes: the slow report waits ~15 s and the rate-limit
test sleeps 61 s first so it starts from an empty window. Never run it during a class.
Tests run in file order; the rate-limit test must stay last.
"""

import os
import time

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
RW = {"X-API-Key": "demo_key_rw_4K9P"}
RO = {"X-API-Key": "demo_key_ro_7M2Q"}
INST = {"X-API-Key": "demo_key_rw_inst_5H8D"}
EXPIRED = {"X-API-Key": "demo_key_expired_1X0Z"}

pytestmark = pytest.mark.skipif(not BASE_URL, reason="set BASE_URL to run the smoke tests")


@pytest.fixture(scope="module")
def http():
    with httpx.Client(base_url=BASE_URL, timeout=25) as client:
        yield client


def assert_error(r, status, code):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == r.headers["X-Request-ID"]


def test_01_health(http):
    r = http.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_02_missing_key(http):
    assert_error(http.get("/v1/clients"), 401, "missing_api_key")


def test_03_student_key(http):
    r = http.get("/v1/clients", headers=RW)
    assert r.status_code == 200 and len(r.json()["data"]) == 5


def test_04_unknown_client(http):
    assert_error(http.get("/v1/clients/CL-009", headers=INST), 404, "client_not_found")


def test_05_invalid_date(http):
    assert_error(http.get("/v1/import-jobs", params={"created_after": "31/13/2026"}, headers=INST),
                 400, "invalid_date")


def test_06_records_page_7(http):
    r = http.get("/v1/records?page=7", headers=INST)
    assert_error(r, 500, "internal_error")
    assert r.json()["error"]["request_id"].startswith("req_")


def test_07_records_page_4_of_100(http):
    assert http.get("/v1/records?page=4&page_size=100", headers=INST).status_code == 500


def test_08_page_size_too_big(http):
    r = http.get("/v1/import-jobs?page_size=500", headers=INST)
    assert r.status_code == 422 and "detail" in r.json()


def test_09_read_only_post(http):
    assert_error(http.post("/v1/import-jobs", headers=RO), 403, "forbidden")


def test_10_expired_key(http):
    assert_error(http.get("/v1/clients", headers=EXPIRED), 401, "api_key_expired")


def test_11_failed_jobs(http):
    body = http.get("/v1/import-jobs?status=failed", headers=INST).json()
    assert (body["total"], body["total_pages"]) == (43, 3)


def test_12_cl_001_jobs(http):
    body = http.get("/v1/import-jobs?client_id=CL-001", headers=INST).json()
    assert (body["total"], body["total_pages"]) == (34, 2)


def test_13_imp_2114(http):
    job = http.get("/v1/import-jobs/IMP-2114", headers=INST).json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "date_parse_error"
    assert job["error"]["row"] == 214


def test_14_page_past_the_end(http):
    r = http.get("/v1/import-jobs?status=failed&page=9", headers=INST)
    assert r.status_code == 200 and r.json()["data"] == []


def test_15_slow_report(http):
    started = time.monotonic()
    r = http.get("/v1/reports/monthly?client_id=CL-003&month=2026-09", headers=INST)
    elapsed = time.monotonic() - started
    assert r.status_code == 200, r.text
    assert r.json()["client_name"] == "Kestrel Finance"
    assert elapsed >= 10, f"expected the ~15 s delay, took {elapsed:.1f} s"


def test_16_rate_limit_last(http):
    time.sleep(61)  # let the instructor key's window empty out
    statuses = []
    for _ in range(31):
        r = http.get("/v1/clients", headers=INST)
        statuses.append(r.status_code)
    assert statuses[:30] == [200] * 30, statuses
    assert_error(r, 429, "rate_limited")
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers["X-RateLimit-Remaining"] == "0"
