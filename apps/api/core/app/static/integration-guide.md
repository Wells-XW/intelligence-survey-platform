# Intelligence Survey Platform — Integration Guide

This guide covers four common integration tasks against the Intelligence Survey Platform REST API:

1. Authentication
2. Listing your surveys
3. Registering a webhook subscription
4. Starting an export job

Two authentication paths are supported:

- **JWT bearer** — interactive UI users via `/api/v1/auth/login`.
- **API key** — long-lived machine credentials via `/api/v1/api-keys`. Format: `sk_<env>_<24 chars>`.

API keys can be presented as `Authorization: Bearer sk_...` or as the `X-API-Key` header.

---

## 1. Authentication

### Login (JWT)

**cURL:**

```bash
curl -X POST https://api.example.com/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice@example.com&password=secret"
# Response: {"access_token": "...", "refresh_token": "...", "expires_in": 900}
```

**Python (httpx):**

```python
import httpx

resp = httpx.post(
    "https://api.example.com/api/v1/auth/login",
    data={"username": "alice@example.com", "password": "secret"},
)
tokens = resp.json()
access_token = tokens["access_token"]
```

### Create an API Key (requires JWT)

**cURL:**

```bash
curl -X POST https://api.example.com/api/v1/api-keys/ \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"My CRM","scopes":["survey:read","response:read","webhook:manage","export:read"]}'
# Response includes "plaintext": "sk_live_..." — capture it; it cannot be recovered later.
```

**Python (httpx):**

```python
resp = httpx.post(
    "https://api.example.com/api/v1/api-keys/",
    json={
        "name": "My CRM",
        "scopes": ["survey:read", "response:read", "webhook:manage", "export:read"],
    },
    headers={"Authorization": f"Bearer {access_token}"},
)
key = resp.json()
api_key_secret = key["plaintext"]  # capture once
```

---

## 2. List Your Surveys

**cURL (with API key):**

```bash
curl https://api.example.com/api/v1/surveys/ \
  -H "X-API-Key: sk_live_..."
```

**Python (httpx):**

```python
resp = httpx.get(
    "https://api.example.com/api/v1/surveys/",
    headers={"X-API-Key": api_key_secret},
)
surveys = resp.json()
```

---

## 3. Register a Webhook Subscription

Subscribed events: `response.created`, `response.completed`, `quota.reached`, `distribution.sent`.

**cURL:**

```bash
curl -X POST https://api.example.com/api/v1/webhooks/ \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "target_url": "https://hooks.example.com/intelligence-survey",
    "event_types": ["response.created", "response.completed"],
    "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11"
  }'
# Response includes "signing_secret": "whsec_..." — capture it for HMAC verification.
```

**Python (httpx):**

```python
resp = httpx.post(
    "https://api.example.com/api/v1/webhooks/",
    json={
        "target_url": "https://hooks.example.com/intelligence-survey",
        "event_types": ["response.created", "response.completed"],
        "survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11",
    },
    headers={"Authorization": f"Bearer {access_token}"},
)
sub = resp.json()
signing_secret = sub["signing_secret"]  # capture once
```

### Verify Incoming Webhook Signatures

The platform signs every webhook with HMAC-SHA256 over the JSON body bytes:

```
X-Webhook-Signature: sha256=<64 hex chars>
```

**Python verification example:**

```python
import hashlib
import hmac

def verify_webhook(body_bytes: bytes, signature_header: str, signing_secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        signing_secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

---

## 4. Start an Export Job

Supported formats: `csv`, `xlsx`, `json` are always available; `sav` and `sas7bdat` are available when the platform's export worker has `pyreadstat` installed.

**cURL:**

```bash
curl -X POST https://api.example.com/api/v1/exports/ \
  -H "X-API-Key: sk_live_..." \
  -H "Content-Type: application/json" \
  -d '{"survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11", "format": "csv"}'
# Response: {"id": "<job_id>", "status": "queued", ...}

# Poll for completion:
curl https://api.example.com/api/v1/exports/<job_id> \
  -H "X-API-Key: sk_live_..."
# When status == "succeeded", response includes "download_url": "/api/v1/exports/<id>/download?token=..."

# Download (browser-friendly):
curl https://api.example.com<download_url> -o export.csv
```

**Python (httpx):**

```python
import time

# Create
resp = httpx.post(
    "https://api.example.com/api/v1/exports/",
    json={"survey_id": "d3b07384-d9a8-4f3b-9f1e-6c2a4d2c8a11", "format": "csv"},
    headers={"X-API-Key": api_key_secret},
)
job = resp.json()
job_id = job["id"]

# Poll
for _ in range(60):
    resp = httpx.get(
        f"https://api.example.com/api/v1/exports/{job_id}",
        headers={"X-API-Key": api_key_secret},
    )
    job = resp.json()
    if job["status"] == "succeeded":
        download_url = job["download_url"]
        # Download (token in URL, no auth header needed)
        file_resp = httpx.get(f"https://api.example.com{download_url}")
        with open("export.csv", "wb") as f:
            f.write(file_resp.content)
        break
    elif job["status"] == "failed":
        raise RuntimeError(f"Export failed: {job['error_message']}")
    time.sleep(5)
```

---

## Rate Limits

API key requests are rate-limited per key with default quotas:

- 60 requests / minute
- 1200 requests / hour
- 10000 requests / day

Successful responses carry headers:

- `X-RateLimit-Limit`: per-minute quota
- `X-RateLimit-Remaining`: requests remaining in the current minute window
- `X-RateLimit-Reset`: Unix timestamp at which the minute window resets

429 responses carry `Retry-After: <seconds>` indicating when to retry.

---

## Error Envelope

All API errors share a JSON envelope:

```json
{
  "error": "<machine_readable_code>",
  "details": { /* optional, type-specific */ }
}
```

Common error codes:

- `auth_required` (401) — no credentials
- `api_key_invalid` / `api_key_revoked` / `api_key_expired` (401)
- `insufficient_scope` (403) — API key lacks required scope
- `rate_limited` (429) — quota exceeded
- `export_format_unsupported` (400) — format not available on this host
- `webhook_url_must_be_https` (400) — webhook target must use HTTPS

---

## Further Reading

- API reference: `/api/v1/docs` (Swagger) or `/api/v1/redoc` (ReDoc)
- OpenAPI schema: `/api/v1/openapi.json`
