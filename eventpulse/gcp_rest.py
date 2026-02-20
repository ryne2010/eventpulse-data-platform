"""Minimal GCP REST helpers.

Why REST (instead of google-cloud-* libs)?
- Keeps the reference implementation dependency-light.
- Works well on Cloud Run using the metadata server for ADC tokens.

Notes:
- These helpers are intended for Cloud Run runtime only.
- Local-first development uses filesystem storage + Redis/RQ by default.

If you prefer the official client libraries, swap this module with
`google-cloud-storage` / `google-cloud-tasks` and keep the higher-level
interfaces unchanged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


class GCSDownloadError(RuntimeError):
    """Raised when a GCS download fails."""

    def __init__(self, *, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class GCSObjectMetadataError(RuntimeError):
    """Raised when a GCS object metadata lookup fails."""


class IAMCredentialsError(RuntimeError):
    """Raised when IAMCredentials API calls fail (e.g., signBlob)."""


_METADATA_BASE = "http://metadata.google.internal/computeMetadata/v1"


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float  # epoch seconds


_token_cache: Optional[_CachedToken] = None
_email_cache: Optional[str] = None


def _metadata_get(path: str, *, timeout: float = 2.0) -> requests.Response:
    url = f"{_METADATA_BASE}{path}"
    return requests.get(url, headers={"Metadata-Flavor": "Google"}, timeout=timeout)


def get_access_token() -> str:
    """Get an OAuth2 access token using the GCE/Cloud Run metadata server."""

    global _token_cache
    now = time.time()

    if _token_cache and _token_cache.expires_at - now > 30:
        return _token_cache.access_token

    try:
        resp = _metadata_get("/instance/service-accounts/default/token", timeout=2.0)
    except Exception as exc:
        raise RuntimeError(
            "GCP metadata server not available. These GCP REST helpers are intended for Cloud Run runtime."
        ) from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get access token from metadata server: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    token = data.get("access_token")
    expires_in = float(data.get("expires_in", 0))
    if not token or expires_in <= 0:
        raise RuntimeError(f"Malformed token response from metadata server: {data}")

    _token_cache = _CachedToken(access_token=token, expires_at=now + expires_in)
    return token


def get_service_account_email() -> str:
    """Return the runtime service account email via metadata server."""

    global _email_cache
    if _email_cache:
        return _email_cache

    try:
        resp = _metadata_get("/instance/service-accounts/default/email", timeout=2.0)
    except Exception as exc:
        raise RuntimeError(
            "GCP metadata server not available. Service account email lookup requires Cloud Run runtime."
        ) from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get service account email: {resp.status_code} {resp.text[:200]}")

    email = (resp.text or "").strip()
    if not email:
        raise RuntimeError("Empty service account email from metadata server")

    _email_cache = email
    return email


# -----------------------------
# Cloud Storage
# -----------------------------


def gcs_object_exists(bucket: str, object_name: str) -> bool:
    token = get_access_token()
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(object_name, safe='')}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    raise RuntimeError(f"GCS exists check failed: {resp.status_code} {resp.text[:200]}")


def gcs_get_object(bucket: str, object_name: str) -> Dict[str, Any]:
    """Fetch object metadata from GCS JSON API."""

    token = get_access_token()
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(object_name, safe='')}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if resp.status_code == 200:
        return dict(resp.json())
    if resp.status_code == 404:
        raise GCSObjectMetadataError(f"GCS object not found: gs://{bucket}/{object_name}")
    raise GCSObjectMetadataError(f"GCS metadata lookup failed: {resp.status_code} {resp.text[:300]}")


def gcs_upload_file(
    bucket: str, object_name: str, local_path: str, *, content_type: str = "application/octet-stream"
) -> None:
    token = get_access_token()
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
    params = {"uploadType": "media", "name": object_name}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": content_type}

    with open(local_path, "rb") as f:
        resp = requests.post(url, params=params, headers=headers, data=f, timeout=120)

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"GCS upload failed: {resp.status_code} {resp.text[:300]}")


def gcs_download_file(bucket: str, object_name: str, local_path: str) -> None:
    token = get_access_token()
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(object_name, safe='')}"
    params = {"alt": "media"}
    headers = {"Authorization": f"Bearer {token}"}

    with requests.get(url, params=params, headers=headers, stream=True, timeout=120) as resp:
        if resp.status_code != 200:
            snippet = resp.text[:300]
            raise GCSDownloadError(
                status_code=resp.status_code,
                message=f"GCS download failed: {resp.status_code} {snippet}",
            )
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


# -----------------------------
# IAMCredentials (signBlob)
# -----------------------------


def iam_sign_blob(*, service_account_email: str, payload: bytes) -> bytes:
    """Sign arbitrary bytes using IAMCredentials signBlob.

    This enables generating GCS signed URLs on Cloud Run without shipping a
    service account key.

    Requires:
    - iamcredentials.googleapis.com enabled
    - The runtime principal has iam.serviceAccounts.signBlob on the target SA
      (recommended: grant roles/iam.serviceAccountTokenCreator on itself).
    """

    token = get_access_token()
    email_escaped = quote(service_account_email, safe="")
    url = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{email_escaped}:signBlob"

    body = {"payload": base64.b64encode(payload).decode("ascii")}
    resp = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=10)
    if resp.status_code != 200:
        raise IAMCredentialsError(f"signBlob failed: {resp.status_code} {resp.text[:300]}")

    data = resp.json()
    signed = data.get("signedBlob")
    if not signed:
        raise IAMCredentialsError(f"signBlob response missing signedBlob: {data}")

    try:
        return base64.b64decode(signed)
    except Exception as exc:
        raise IAMCredentialsError("signBlob response signedBlob was not valid base64") from exc


# -----------------------------
# GCS Signed URLs (V4)
# -----------------------------


def _rfc3986_quote(value: str) -> str:
    # RFC 3986 / AWS-style encoding used for canonical query strings.
    return quote(value, safe="-_.~")


def _normalize_header_value(value: str) -> str:
    # Collapse internal whitespace and trim. This matches common canonicalization.
    return " ".join(value.strip().split())


def gcs_generate_v4_signed_url(
    *,
    bucket: str,
    object_name: str,
    method: str,
    expires_seconds: int,
    headers_to_sign: Optional[Dict[str, str]] = None,
    extra_query_params: Optional[Dict[str, str]] = None,
    service_account_email: Optional[str] = None,
) -> str:
    """Generate a V4 signed URL for GCS.

    This implementation signs via IAMCredentials signBlob so it works on Cloud
    Run without private key material.

    Returns a URL suitable for direct client upload/download.

    NOTE: This helper is intended for server-side generation and will raise if
    the metadata server is unavailable (e.g., running locally without GCP).
    """

    m = (method or "").upper().strip()
    if m not in {"PUT", "GET", "HEAD", "DELETE"}:
        raise ValueError(f"Unsupported signed URL method: {m}")

    expires = int(expires_seconds)
    # GCS V4 signed URLs allow up to 7 days.
    expires = max(1, min(expires, 60 * 60 * 24 * 7))

    email = service_account_email or get_service_account_email()

    now = datetime.now(timezone.utc)
    datestamp = now.strftime("%Y%m%d")
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    credential_scope = f"{datestamp}/auto/storage/goog4_request"

    # Canonical headers
    headers: Dict[str, str] = {"host": "storage.googleapis.com"}
    for k, v in (headers_to_sign or {}).items():
        if not k:
            continue
        headers[k.lower().strip()] = _normalize_header_value(str(v))

    signed_headers = ";".join(sorted(headers.keys()))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers.keys()))

    # Canonical URI uses path-style requests:
    #   https://storage.googleapis.com/<bucket>/<object>
    escaped_object = quote(object_name, safe="/~")
    canonical_uri = f"/{bucket}/{escaped_object}"

    query_params = {
        "X-Goog-Algorithm": "GOOG4-RSA-SHA256",
        "X-Goog-Credential": f"{email}/{credential_scope}",
        "X-Goog-Date": timestamp,
        "X-Goog-Expires": str(expires),
        "X-Goog-SignedHeaders": signed_headers,
    }

    # Additional signed query params (e.g., preconditions like ifGenerationMatch=0)
    for k, v in (extra_query_params or {}).items():
        if not k:
            continue
        if k in query_params:
            # Don't allow overriding required X-Goog-* params.
            continue
        query_params[str(k)] = str(v)

    canonical_query = "&".join(f"{_rfc3986_quote(k)}={_rfc3986_quote(v)}" for k, v in sorted(query_params.items()))

    canonical_request = "\n".join(
        [
            m,
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            "UNSIGNED-PAYLOAD",
        ]
    )

    canonical_request_hash = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()

    string_to_sign = "\n".join(
        [
            "GOOG4-RSA-SHA256",
            timestamp,
            credential_scope,
            canonical_request_hash,
        ]
    )

    sig_bytes = iam_sign_blob(service_account_email=email, payload=string_to_sign.encode("utf-8"))
    signature = binascii.hexlify(sig_bytes).decode("ascii")

    return f"https://storage.googleapis.com{canonical_uri}?{canonical_query}&X-Goog-Signature={signature}"


# -----------------------------
# Cloud Tasks
# -----------------------------


def cloud_tasks_create_http_task(
    *,
    project: str,
    location: str,
    queue: str,
    url: str,
    body_json: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    oidc_service_account_email: Optional[str] = None,
    dispatch_deadline_seconds: Optional[int] = None,
) -> str:
    """Create a Cloud Tasks HTTP task.

    Returns the created task name.

    REST API requires base64-encoded body.
    """

    token = get_access_token()
    parent = f"projects/{project}/locations/{location}/queues/{queue}"

    endpoint = f"https://cloudtasks.googleapis.com/v2/{parent}/tasks"

    body_bytes = json.dumps(body_json).encode("utf-8")
    http_req: Dict[str, Any] = {
        "httpMethod": "POST",
        "url": url,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": base64.b64encode(body_bytes).decode("ascii"),
    }

    if oidc_service_account_email:
        http_req["oidcToken"] = {"serviceAccountEmail": oidc_service_account_email}

    task: Dict[str, Any] = {"httpRequest": http_req}

    if dispatch_deadline_seconds is not None:
        sec = max(1, int(dispatch_deadline_seconds))
        task["dispatchDeadline"] = f"{sec}s"

    payload = {"task": task}

    resp = requests.post(endpoint, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=10)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Cloud Tasks create_task failed: {resp.status_code} {resp.text[:300]}")

    data = resp.json()
    name = data.get("name")
    if not name:
        raise RuntimeError(f"Cloud Tasks create_task response missing name: {data}")
    return str(name)
