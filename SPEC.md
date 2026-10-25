# Course Practice API — build guide

A small FastAPI app that behaves like a data-management product's API: clients, import jobs, records, sync errors, monthly reports. Students use it to learn how to call APIs, troubleshoot them, and later script against them in Python.

It **breaks on purpose**, in fixed and repeatable ways. Every number below is a requirement: course notes and answer keys depend on them. Do not "improve" the data, the errors or the bugs.

Generic and reusable: fictional clients only. No real people, companies or employer data anywhere in this repo.

---

## 1. Stack and layout

- Python 3.13, FastAPI, Pydantic v2, Faker, uvicorn. **One worker** (the rate limiter is in memory).
- Docker + docker-compose, `restart: unless-stopped`, behind the VPS's existing reverse proxy on an HTTPS subdomain.

```text
course-practice-api/
  app/
    main.py          # app factory, middleware, exception handlers, OpenAPI settings
    auth.py          # API key dependency
    ratelimit.py     # sliding-window limiter
    data.py          # deterministic seed data + startup assertions
    models.py        # Pydantic response models (incl. ErrorResponse)
    routers/         # clients, import_jobs, records, sync_errors, reports
  tests/
    test_contract.py # local, FastAPI TestClient, checks data + behaviour
    test_smoke.py    # against a live BASE_URL
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md
```

Config by environment variable:

| Var | Default | Use |
|---|---|---|
| `PUBLIC_BASE_URL` | unset | When set, put it in OpenAPI `servers` (Postman's import uses it for `baseUrl`). When unset, omit `servers`. |
| `SLOW_REPORT_SECONDS` | `15` | Delay for CL-003's monthly report. Tests set it to `0.1`. |
| `REPORT_SECONDS` | `1` | Delay for every other monthly report. |

---

## 2. Authentication

Header **`X-API-Key`**. Declare it with `APIKeyHeader(name="X-API-Key", auto_error=False)` so Swagger shows **Authorize** and *our* handler produces the error (with `auto_error=True` FastAPI returns its own error body, which breaks the envelope).

| Key | Label (for logs) | Behaviour |
|---|---|---|
| `demo_key_rw_4K9P` | `rw` | Valid, read and write. The student key. |
| `demo_key_ro_7M2Q` | `ro` | Valid, read-only. Any `POST` → **403** `forbidden`, message `This API key is read-only`. |
| `demo_key_rw_inst_5H8D` | `inst` | Valid, read and write. Instructor/demo key, so demos and smoke tests don't eat the student's rate limit. |
| `demo_key_expired_1X0Z` | `expired` | **401** `api_key_expired`, message `API key expired on 2026-10-01. Generate a new key.` |
| header missing | `none` | **401** `missing_api_key`, message `Send your API key in the X-API-Key header.` |
| any other value | `invalid` | **401** `invalid_api_key`, message `This API key is not valid.` |

No key needed: `/health`, `/docs`, `/redoc`, `/openapi.json`. Everything under `/v1/*` needs one.

Keys are fake and hard-coded. That's fine. Never log a full key; log its label.

---

## 3. Rules every response follows

**Request ID.** Every response (200s, every error, 422, 429, 500, docs) carries `X-Request-ID: req_` + 6 random digits. Generate with `secrets`, not the seeded RNG.

**Error envelope.** Every error except 422:

```json
{"error": {"code": "client_not_found", "message": "No client with id CL-009", "request_id": "req_483920"}}
```

The `request_id` in the body equals the header.

**422 keeps FastAPI's default body** (`{"detail": [...]}`). Deliberate: it teaches that one API can return errors in two shapes. Do not override `RequestValidationError`.

**Unknown routes and wrong methods** also use the envelope: 404 `not_found`, 405 `method_not_allowed`. Register a handler for Starlette's `HTTPException`, not only FastAPI's.

**Rate-limit headers** on every `/v1/*` response from a valid key (including its errors): `X-RateLimit-Limit: 30`, `X-RateLimit-Remaining: <n>`.

**Error precedence** (first match wins):

1. Auth: 401 (missing / invalid / expired)
2. Rate limit: 429
3. Permission: 403 (read-only key on POST)
4. Request problems: 422 / 400 / 404
5. Server: 500

So "no key + `page_size=500`" is **401**, not 422.

---

## 4. Rate limit

- **30 requests per rolling 60 seconds, per valid key** (`rw`, `ro`, `inst` each have their own window), on `/v1/*` only.
- Count every request from that key, whatever its result. Requests with no / invalid / expired keys are not counted (they always get 401).
- Request 31 → **429** `rate_limited`, message `Too many requests. Wait the number of seconds in Retry-After, then try again.`, header **`Retry-After`** = whole seconds until the oldest request in the window expires (round up, minimum 1). `X-RateLimit-Remaining: 0`.
- Sliding window: a deque of timestamps per key. In memory; a restart resets it.

---

## 5. Pagination (list endpoints)

Query `page` (default 1, `ge=1`) and `page_size` (default per endpoint, `ge=1`, `le=100`). Out of range → **422** via FastAPI's validation (that's the intended 422).

```json
{"data": [ ... ], "page": 1, "page_size": 20, "total": 43, "total_pages": 3}
```

- `total_pages = ceil(total / page_size)`, `0` when `total` is 0.
- A page past the end → **200** with `"data": []`. Not 404.
- A filter value that matches nothing (e.g. `client_id=CL-999`) → 200, empty list.

---

## 6. Endpoints

Every endpoint gets a `summary`, a plain-English `description`, a `response_model`, parameter descriptions with examples, and a `responses=` map listing the errors it can return (using an `ErrorResponse` model). Students later ask Claude to explain this API **from `openapi.json` alone**, including "which errors each endpoint can return", so the spec must say so.

**The spec must not give away the planted bugs.** Document the records 500 as a generic "Unexpected server error" and nothing more. No mention of REC-0337, month 13, or which page fails.

| Method | Path | Behaviour |
|---|---|---|
| GET | `/health` | `{"status": "ok"}`. No auth, no rate limit. |
| GET | `/v1/clients` | `{"data": [5 clients]}`. Not paginated. |
| GET | `/v1/clients/{client_id}` | One client. Unknown → **404** `client_not_found`, `No client with id CL-009`. |
| GET | `/v1/import-jobs` | Paginated, default `page_size` 20. Filters below. |
| GET | `/v1/import-jobs/{job_id}` | One job (seed or POSTed). Unknown → **404** `job_not_found`. |
| POST | `/v1/import-jobs` | Create a queued job. See below. |
| GET | `/v1/records` | Paginated, default `page_size` 50. Filter `client_id`. Contains the planted 500. |
| GET | `/v1/sync-errors` | Paginated, default `page_size` 20. Filters `client_id`, `code`. |
| GET | `/v1/reports/monthly` | Slow on purpose. See below. |

### `GET /v1/import-jobs` filters

| Param | Rule |
|---|---|
| `status` | Enum `succeeded`, `failed`, `running`, `queued`. Other values → 422 (normal validation). |
| `client_id` | Exact match. |
| `created_after` | **Type it as `str`** and validate by hand: must match `^\d{4}-\d{2}-\d{2}$` and parse with `date.fromisoformat`. Otherwise **400** `invalid_date`, message `created_after must be a date in YYYY-MM-DD format, got '31/13/2026'`. (If typed as `date`, FastAPI returns 422 and the lesson breaks.) Inclusive: jobs created on or after that day (UTC). |
| `sort` | `created_at` or `-created_at`, default `-created_at`. Other values → 422. |

### `POST /v1/import-jobs`

Body `{"client_id": "CL-001", "file_name": "contacts_nov.csv"}`, both required strings.

- Read-only key → **403** `forbidden`.
- Unknown client → **404** `client_not_found`.
- Missing field → **422** (default body).
- Success → **201**, header `Location: /v1/import-jobs/IMP-9001`, body is the new job: `status` `queued`, `rows_total` null, `rows_loaded` 0, `created_at` now, `finished_at` null, `error` null.

**POSTed jobs never appear in list results or counts**: store them in a separate in-memory dict, retrievable only by `GET /v1/import-jobs/{job_id}`. IDs start at `IMP-9001` so they can't be confused with seed jobs. Keep at most 200 (drop oldest). Lost on restart. This keeps every answer key stable no matter how many students POST.

### `GET /v1/records` and the planted 500

Sorted by `id` ascending, always (page maths depends on it).

For each record on the requested page, the route calls an internal `normalise_date(updated_at)` (accepts the three formats in §7). The response still returns the **raw** `updated_at` strings, unchanged: the mixed formats are a later lesson.

`REC-0337` has `updated_at = "31/13/2026"`. `normalise_date` raises `ValueError` on it, the exception is **not caught in the route**, and the app returns **500** `internal_error`, message `Something went wrong on our side. Quote the request ID when you contact support.` Log the traceback with the request ID.

Result: whichever page contains REC-0337 fails. Unfiltered, that's page 7 at `page_size=50` and page 4 at `page_size=100`. REC-0337 belongs to **CL-002**, so `client_id=CL-002` also fails on whichever page holds it.

### `GET /v1/sync-errors`

Fields: `id` (`SE-0001`…`SE-0060`), `client_id`, `code`, `message`, `occurred_at` (ISO 8601 UTC), `resolved` (bool). Sorted by `occurred_at` descending. `code` filter is an enum of the three codes.

### `GET /v1/reports/monthly`

Query `client_id` (required) and `month` (required, `str`, must match `^\d{4}-(0[1-9]|1[0-2])$`, else **400** `invalid_month`, message `month must be in YYYY-MM format, got '...'`). Unknown client → 404 `client_not_found`.

**Delay with `await asyncio.sleep(...)`, never `time.sleep`.** With one worker, a blocking sleep freezes the whole API for every user for 15 seconds. `REPORT_SECONDS` normally, `SLOW_REPORT_SECONDS` for `CL-003`.

Response, computed from the seed data for that client and month (zeros for months with no data):

```json
{"client_id": "CL-003", "client_name": "Kestrel Finance", "month": "2026-09",
 "imports_total": 0, "imports_succeeded": 0, "imports_failed": 0,
 "rows_loaded": 0, "sync_errors": 0}
```

---

## 7. Seed data

### Determinism rules

- Build each dataset **explicitly to hit the counts**, then use a dedicated `random.Random(42)` to shuffle and assign details. Don't generate randomly and hope.
- `Faker` seeded with 42, used only for names, emails and filler file names.
- **All timestamps are fixed** (no `now()` anywhere in seed data), so answers never drift.
- `data.py` runs `assert`s for every count in this section at startup. If any fails, the app must not start.

### Clients (5)

| id | name | plan | tags | notes |
|---|---|---|---|---|
| CL-001 | Bluepeak Health | Enterprise | `["priority", "renewal"]` | `null` |
| CL-002 | Orchard Retail | Growth | `["retail"]` | `"Prefers email over phone."` |
| CL-003 | Kestrel Finance | Enterprise | `["priority"]` | `null` |
| CL-004 | Lumen Education | Starter | `[]` | `null` |
| CL-005 | Northwind Logistics | Growth | `["renewal"]` | `null` |

Fields: `id`, `name`, `plan`, `contact` (`{name, email}`, Faker), `tags`, `notes`, `created_at` (fixed dates in 2025). The CL-001 shape matches the example in the course notes, so keep `tags` and `notes`.

### Import jobs (150): `IMP-2001` to `IMP-2150`, created 1 Sep – 14 Oct 2026

Fields: `id`, `client_id`, `file_name`, `status`, `rows_total`, `rows_loaded`, `created_at`, `finished_at` (null unless succeeded/failed), `error` (null unless failed: `{code, message, row}`).

| | CL-001 | CL-002 | CL-003 | CL-004 | CL-005 | Total |
|---|---|---|---|---|---|---|
| All jobs | 34 | 33 | 31 | 28 | 24 | **150** |
| Failed | 12 | 10 | 9 | 7 | 5 | **43** |

- Status totals: succeeded **88**, failed **43**, running **11**, queued **8**.
- Running and queued jobs are the most recent ones (created 10–14 Oct).
- Failed by error code: `date_parse_error` **15**, `missing_column` **11**, `file_too_large` **7**, `duplicate_rows` **6**, `timeout` **4**.
- Failed jobs: `rows_loaded < rows_total`, `error.row <= rows_total`.
- **Fixed job:** `IMP-2114`, client `CL-004`, file `students_oct.csv`, status `failed`, `error = {"code": "date_parse_error", "message": "date '31/13/2026' could not be parsed", "row": 214}`, `rows_total` ≥ 214. It counts toward CL-004's 7 and `date_parse_error`'s 15.

### Records (450): `REC-0001` to `REC-0450`

Fields: `id`, `client_id`, `type`, `contact_email`, `updated_at`, `source` (`{system, file_name}`).

| Field | Rule |
|---|---|
| `client_id` | CL-001 110 · CL-002 100 · CL-003 95 · CL-004 80 · CL-005 65. **REC-0337 is CL-002.** |
| `type` | `contact`, `company` or `deal` |
| `contact_email` | Exactly **36** null (8%), never REC-0337 |
| `updated_at` | Mixed formats on purpose: **300** ISO (`2026-09-14T10:22:00Z`), **90** `DD/MM/YYYY` (`14/09/2026`, include some ambiguous ones like `05/09/2026`), **59** `Mon D, YYYY` (`Sep 14, 2026`), plus **REC-0337 = `31/13/2026`**. All real dates fall 1 Sep – 14 Oct 2026. |
| `source.system` | `csv_upload`, `crm_sync` or `api`. `file_name` set only for `csv_upload`, else null. |

### Sync errors (60): `SE-0001` to `SE-0060`

- By client: CL-001 18 · CL-002 14 · CL-003 12 · CL-004 9 · CL-005 7.
- By code: `crm_auth_expired` 24 · `rate_limited` 21 · `timeout` 15.
- `occurred_at` 1 Sep – 14 Oct 2026. About a third `resolved: true`.

---

## 8. OpenAPI settings

- `title="Course Practice API"`, `version="1.0.0"`, a short description of what the API is (a fictional data-management product) and how to authenticate.
- `servers=[{"url": PUBLIC_BASE_URL}]` when that env var is set.
- Tags: `clients`, `import-jobs`, `records`, `sync-errors`, `reports`, `health`.
- An `ErrorResponse` model in `components/schemas`, referenced from each endpoint's `responses` (401, 429 everywhere under `/v1`; plus 403, 404, 400 where they apply).
- Document `X-Request-ID` as a response header where FastAPI allows it.
- Examples on parameters (`created_after: 2026-10-01`, `month: 2026-09`, `client_id: CL-001`).

---

## 9. Implementation gotchas

- **Use middleware, not `@app.exception_handler(Exception)`, for the 500.** That handler runs outside user middleware in Starlette, so the 500 response loses `X-Request-ID` and the rate-limit headers. Put one HTTP middleware in charge of: creating the request ID, rate limiting, wrapping `call_next` in `try/except Exception` to build the 500 envelope, and adding headers to every response.
- The middleware and the auth dependency must agree on which keys are valid. Keep the key table in one module.
- `APIKeyHeader(..., auto_error=False)` (see §2).
- `created_after` and `month` are `str`, validated by hand (see §6).
- `asyncio.sleep`, never `time.sleep`.
- One uvicorn worker. Run with `--proxy-headers --forwarded-allow-ips="*"` behind the proxy.
- Reverse proxy read timeout must exceed 20 s (the 15 s report) and must pass `X-Request-ID`, `Retry-After` and `X-RateLimit-*` through untouched.
- **Request log**, one line per request to stdout: time, request ID, key label, method, path with query, status, duration ms. The instructor greps a student's request ID in `docker logs` during class, which mirrors how escalation works.

---

## 10. Tests

### `tests/test_contract.py` (local, TestClient, `SLOW_REPORT_SECONDS=0.1`)

- Every count in §7, read through the API (not from `data.py`).
- REC-0337 page maths: 500 at `page=7` (size 50) and `page=4&page_size=100`; pages 6 and 8 are fine.
- Precedence: no key + `page_size=500` → 401; read-only key + POST with empty body → 403.
- 422 body has `detail`; every other error has the envelope with `request_id` equal to the header.
- `X-Request-ID` present on 200, 401, 404, 422, 429 and 500.
- POST creates `IMP-9001`, `GET /v1/import-jobs/IMP-9001` returns it, and list totals are unchanged.
- Unknown route → 404 envelope; `DELETE /v1/clients` → 405 envelope.
- `openapi.json` mentions no `REC-0337` and no `31/13`.

### `tests/test_smoke.py` (live, `BASE_URL` env var)

Uses the `inst` key for the rw rows (so the student's quota is untouched), plus one call with the student `rw` key. The rate-limit test runs **last**, after sleeping 61 s. Timeout 25 s for the slow report. Never run it during a class.

| # | Request | Key | Expect |
|---|---|---|---|
| 1 | `GET /health` | none | 200 `{"status":"ok"}` |
| 2 | `GET /v1/clients` | none | 401 `missing_api_key` |
| 3 | `GET /v1/clients` | rw (student) | 200, 5 clients |
| 4 | `GET /v1/clients/CL-009` | inst | 404 `client_not_found` |
| 5 | `GET /v1/import-jobs?created_after=31/13/2026` | inst | 400 `invalid_date` |
| 6 | `GET /v1/records?page=7` | inst | 500 `internal_error` with `request_id` |
| 7 | `GET /v1/records?page=4&page_size=100` | inst | 500 |
| 8 | `GET /v1/import-jobs?page_size=500` | inst | 422 (`detail` body) |
| 9 | `POST /v1/import-jobs` | ro | 403 `forbidden` |
| 10 | `GET /v1/clients` | expired | 401 `api_key_expired` |
| 11 | `GET /v1/import-jobs?status=failed` | inst | `total` 43, `total_pages` 3 |
| 12 | `GET /v1/import-jobs?client_id=CL-001` | inst | `total` 34, `total_pages` 2 |
| 13 | `GET /v1/import-jobs/IMP-2114` | inst | failed, `date_parse_error`, row 214 |
| 14 | `GET /v1/import-jobs?status=failed&page=9` | inst | 200, `data: []` |
| 15 | `GET /v1/reports/monthly?client_id=CL-003&month=2026-09` | inst | ~15 s, then 200 |
| 16 | 31 × `GET /v1/clients` within a minute | inst | #31 → 429 with `Retry-After` |

---

## 11. Deploy

- `Dockerfile`: `python:3.13-slim`, install requirements, run `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips="*"`.
- `docker-compose.yml`: `restart: unless-stopped`, `PUBLIC_BASE_URL` set to the real HTTPS address, healthcheck on `/health`, port reachable only by the reverse proxy.
- Reverse proxy: HTTPS subdomain, read timeout ≥ 30 s.

### Done when

- [ ] `pytest tests/test_contract.py` green locally.
- [ ] `BASE_URL=https://<live> pytest tests/test_smoke.py` green.
- [ ] `/docs`: Authorize with the student key works and the padlocks close.
- [ ] Postman: Import → paste `https://<live>/openapi.json` creates a collection whose base URL variable points at the live address.
- [ ] `curl.exe -o openapi.json https://<live>/openapi.json` works from Windows PowerShell.
- [ ] README explains how to run locally, run both test files, and deploy.

---

## Prompt for Claude Code

```text
Build the Course Practice API in this repo from SPEC.md. Follow it exactly: the seed
counts, error envelope, keys, rate limit, error precedence, and the REC-0337 behaviour
are requirements that course material depends on. Section 9 lists implementation traps;
avoid every one. Do not mention the planted bugs anywhere in the OpenAPI spec.

Plan first. In the plan, show how data.py hits every count deterministically and how the
middleware handles request IDs, rate limiting and the 500. Then build it, write
tests/test_contract.py and tests/test_smoke.py as described in section 10, and run the
contract tests until they pass. Add the Dockerfile, docker-compose.yml and a README.
Ask me before deploying anything.
```
