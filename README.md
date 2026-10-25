# Course Practice API

A small FastAPI app that behaves like a fictional data-management product's API: clients,
import jobs, records, sync errors and monthly reports. Students use it to practise calling
an API, troubleshooting it and scripting against it.

It **breaks on purpose**, in fixed and repeatable ways. The seed data, error codes and
planted bugs are requirements that course notes and answer keys depend on: see
[`SPEC.md`](SPEC.md) before changing anything. All clients and people are fictional.

## API keys

| Key | Use |
|---|---|
| `demo_key_rw_4K9P` | Student key, read and write |
| `demo_key_ro_7M2Q` | Read-only (POST returns 403) |
| `demo_key_rw_inst_5H8D` | Instructor / demo key, read and write, separate rate limit |
| `demo_key_expired_1X0Z` | Always 401 `api_key_expired` |

Send the key in the `X-API-Key` header. `/health`, `/docs`, `/redoc` and `/openapi.json`
need no key. Limit: 30 requests per rolling 60 seconds per key.

## Run locally

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000/docs>, click **Authorize**, paste the student key.

| Variable | Default | Use |
|---|---|---|
| `PUBLIC_BASE_URL` | unset | Added to `openapi.json` `servers` (Postman uses it for `baseUrl`) |
| `SLOW_REPORT_SECONDS` | `15` | Delay for CL-003's monthly report |
| `REPORT_SECONDS` | `1` | Delay for every other monthly report |

## Tests

Contract tests run in-process (no server needed, about 3 seconds):

```bash
pytest tests/test_contract.py
```

Smoke tests run against a live deployment. They take about 1.5 minutes (one ~15 s report,
then a 61 s wait before the rate-limit check). **Don't run them during a class**:

```bash
BASE_URL=https://<live-host> pytest tests/test_smoke.py
```

Without `BASE_URL` the smoke tests are skipped.

## Logs

One line per request on stdout, with the request ID and the key's label (never the key):

```text
2026-10-25 10:46:06,515 INFO request_id=req_970791 key=inst GET /v1/records?page=7 status=500 duration_ms=7
```

When a student quotes a request ID, find it with:

```bash
docker logs course-practice-api 2>&1 | grep req_970791
```

500s also log a traceback tagged with the same request ID.

## Deploy (VPS, behind the existing reverse proxy)

1. Copy the repo to the server and create `.env` from `.env.example` with the real HTTPS address:

   ```bash
   cp .env.example .env   # then edit PUBLIC_BASE_URL
   docker compose up -d --build
   docker compose ps       # wait for "healthy"
   ```

   The container listens on `127.0.0.1:8000`, so only the proxy on the same host can reach it.
   It must run **one** uvicorn worker (rate limits and POSTed jobs are in memory; a restart
   resets both).

2. Point an HTTPS subdomain at it in the reverse proxy. The proxy must:
   - use a read timeout of **at least 30 s** (the CL-003 report takes 15 s);
   - pass `X-Request-ID`, `Retry-After`, `X-RateLimit-Limit` and `X-RateLimit-Remaining`
     through unchanged;
   - send `X-Forwarded-For` / `X-Forwarded-Proto` (uvicorn runs with `--proxy-headers`).

   Nginx example:

   ```nginx
   location / {
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_read_timeout 30s;
   }
   ```

   Caddy: `reverse_proxy 127.0.0.1:8000` (its default timeouts are already long enough).

3. Check it:

   ```bash
   BASE_URL=https://<live-host> pytest tests/test_smoke.py
   ```

   Then in `/docs`, Authorize with the student key; in Postman, Import →
   `https://<live-host>/openapi.json` and check the `baseUrl` variable; from Windows
   PowerShell, `curl.exe -o openapi.json https://<live-host>/openapi.json`.

## Layout

```text
app/
  main.py        app factory, core middleware (request ID, auth, rate limit, 500), handlers, OpenAPI
  auth.py        key table and the X-API-Key dependency
  ratelimit.py   sliding-window limiter
  data.py        deterministic seed data + startup checks
  errors.py      error envelope
  models.py      response models (incl. ErrorResponse)
  routers/       clients, import_jobs, records, sync_errors, reports
tests/
  test_contract.py
  test_smoke.py
```
