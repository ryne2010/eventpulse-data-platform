#!/usr/bin/env python3
"""
EventPulse Edge Agent (Raspberry Pi / field device)

Responsibilities:
- Sample sensor readings (simulated by default)
- Spool to local disk with rotation (offline-friendly)
- Upload batches to EventPulse API (direct) OR to GCS via signed URLs (recommended)
- Retry with backoff + never crash on transient network issues

Auth model (recommended):
- Per-device token (server-side revocable)
- Fast provisioning option: bootstrap enrollment via /api/edge/enroll using a shared
  EDGE_ENROLL_TOKEN.
- Edge agent sends:
  - X-Device-Id
  - X-Device-Token

Upload modes:
- auto: query /api/meta once and choose:
    - signed_url if storage_backend=gcs AND enable_edge_signed_urls=true
    - otherwise direct
- direct: POST /api/edge/ingest/upload (device-auth)
- signed_url: POST /api/edge/uploads/gcs_signed_url (device-auth) -> PUT to GCS -> POST /api/edge/ingest/from_gcs (device-auth)

This agent is intentionally dependency-light for compatibility on ARM devices.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import os
import platform
import random
import re
import select
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return str(v).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except Exception:
        return float(default)


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _read_first_line(path: str, *, max_len: int = 256) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readline().strip()[:max_len]
    except Exception:
        return ""


def _read_machine_id() -> str:
    # systemd machine-id is stable across boots. On cloned SD cards it *may* be duplicated
    # until regenerated, so we prefer Pi serial when available.
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        mid = _read_first_line(p)
        if mid:
            return mid
    return ""


def _read_rpi_serial() -> str:
    # Raspberry Pi: /proc/cpuinfo contains a stable per-board serial.
    try:
        txt = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^Serial\s*:\s*([0-9a-fA-F]+)\s*$", txt, flags=re.MULTILINE)
        if m:
            return str(m.group(1)).strip()
    except Exception:
        return ""
    return ""


def _default_device_id() -> str:
    """Best-effort unique device id for field deployments.

    Order:
    - Raspberry Pi serial
    - machine-id
    - hostname
    """

    serial = _read_rpi_serial()
    if serial:
        return f"rpi-{serial[-10:]}"

    mid = _read_machine_id()
    if mid:
        return f"dev-{mid[:12]}"

    return socket.gethostname()


def _enroll_fingerprint() -> str:
    """Stable fingerprint used to allow safe re-enrollment.

    The server stores this value in device metadata and only allows a token rotation
    via /api/edge/enroll when the fingerprint matches.

    We intentionally hash the underlying identifier before sending it.
    """

    base = _read_rpi_serial() or _read_machine_id() or socket.gethostname()
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _load_device_token_file(path: Path) -> str:
    try:
        t = path.read_text(encoding="utf-8").strip()
        return t
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def _save_device_token_file(path: Path, token: str) -> None:
    """Persist the device token with an atomic replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix="device_token_", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(str(token).strip() + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    finally:
        try:
            os.unlink(tmp_name)
        except Exception:
            pass


@dataclass(frozen=True)
class EdgeConfig:
    api_base_url: str
    dataset: str
    source: str
    device_id: str
    device_token: str
    device_label: str
    device_token_file: Path

    # Optional bootstrap enrollment
    enroll_token: str
    enroll_fingerprint: str
    enroll_every_seconds: int

    # Sampling + rotation
    sample_hz: float
    heartbeat_seconds: int
    rotate_every_seconds: int

    # Spool dirs
    spool_dir: Path
    outbox_dir: Path
    inflight_dir: Path
    sent_dir: Path
    dead_dir: Path

    # Spool safeguards
    max_spool_bytes: int
    max_spool_files: int
    flush_every_rows: int

    # Upload
    upload_interval_seconds: int
    max_retries_per_file: int
    upload_mode: str  # auto|direct|signed_url
    request_timeout_seconds: int

    # Sensor mode
    sensor_mode: str  # simulated|stdin|script
    sensor_script: str
    sensor_script_shell: bool

    # Enriched metadata (optional, but nice for UI + ops)
    firmware_version: str
    fixed_lat: Optional[float]
    fixed_lon: Optional[float]
    battery_v: Optional[float]
    rssi_dbm: Optional[int]

    # Determinism (sim)
    seed: Optional[int]

    @staticmethod
    def from_env() -> "EdgeConfig":
        api_base_url = _env("EDGE_API_BASE_URL", "http://localhost:8081").rstrip("/")
        dataset = _env("EDGE_DATASET", "edge_telemetry")
        source = _env("EDGE_SOURCE", "edge_agent")

        device_id = _env("EDGE_DEVICE_ID", "")
        if not device_id:
            # Prefer a more unique/stable default than hostname (cloned images often share hostnames).
            device_id = _default_device_id()

        device_label = _env("EDGE_DEVICE_LABEL", "")

        # Spool dirs
        spool_root = Path(_env("EDGE_SPOOL_DIR", "/data/spool")).resolve()

        token_file_default = str(spool_root / "device_token.txt")
        device_token_file = Path(_env("EDGE_DEVICE_TOKEN_FILE", token_file_default)).resolve()

        device_token = _env("EDGE_DEVICE_TOKEN", "")
        if not device_token:
            device_token = _load_device_token_file(device_token_file)

        enroll_token = _env("EDGE_ENROLL_TOKEN", "")
        enroll_every_seconds = max(30, _env_int("EDGE_ENROLL_EVERY_SECONDS", 300))
        enroll_fingerprint = _env("EDGE_ENROLL_FINGERPRINT", "") or _enroll_fingerprint()

        sample_hz = _env_float("EDGE_SAMPLE_HZ", 2.0)
        heartbeat_seconds = _env_int("EDGE_HEARTBEAT_SECONDS", 30)
        rotate_every_seconds = _env_int("EDGE_ROTATE_EVERY_SECONDS", 60)

        outbox_dir = spool_root / "outbox"
        inflight_dir = spool_root / "inflight"
        sent_dir = spool_root / "sent"
        dead_dir = spool_root / "dead"

        max_spool_bytes = _env_int("EDGE_MAX_SPOOL_MB", 256) * 1024 * 1024
        max_spool_files = _env_int("EDGE_MAX_SPOOL_FILES", 2000)
        flush_every_rows = max(1, _env_int("EDGE_FLUSH_EVERY_ROWS", 10))

        upload_interval_seconds = _env_int("EDGE_UPLOAD_INTERVAL_SECONDS", 10)
        max_retries_per_file = _env_int("EDGE_MAX_RETRIES_PER_FILE", 12)
        upload_mode = _env("EDGE_UPLOAD_MODE", "auto").lower()
        request_timeout_seconds = _env_int("EDGE_REQUEST_TIMEOUT_SECONDS", 30)

        sensor_mode = _env("EDGE_SENSOR_MODE", "simulated").lower()
        sensor_script = _env("EDGE_SENSOR_SCRIPT", "")

        sensor_script_shell = _env("EDGE_SENSOR_SCRIPT_SHELL", "false").lower() in (
            "1",
            "true",
            "yes",
            "y",
            "on",
        )

        # Optional device metadata (helps UI/ops)
        firmware_version = _env("EDGE_FIRMWARE_VERSION", "edge-agent/0.3.5")

        fixed_lat: Optional[float] = None
        fixed_lon: Optional[float] = None
        lat_raw = _env("EDGE_LAT", "")
        lon_raw = _env("EDGE_LON", "")
        if lat_raw and lon_raw:
            try:
                fixed_lat = float(lat_raw)
                fixed_lon = float(lon_raw)
            except Exception:
                fixed_lat, fixed_lon = None, None

        battery_v: Optional[float] = None
        battery_raw = _env("EDGE_BATTERY_V", "")
        if battery_raw:
            try:
                battery_v = float(battery_raw)
            except Exception:
                battery_v = None

        rssi_dbm: Optional[int] = None
        rssi_raw = _env("EDGE_RSSI_DBM", "")
        if rssi_raw:
            try:
                rssi_dbm = int(float(rssi_raw))
            except Exception:
                rssi_dbm = None

        seed_raw = _env("EDGE_SEED", "")
        seed = None
        if seed_raw:
            try:
                seed = int(seed_raw)
            except Exception:
                seed = None

        return EdgeConfig(
            api_base_url=api_base_url,
            dataset=dataset,
            source=source,
            device_id=device_id,
            device_token=device_token,
            device_label=device_label,
            device_token_file=device_token_file,
            enroll_token=enroll_token,
            enroll_fingerprint=enroll_fingerprint,
            enroll_every_seconds=enroll_every_seconds,
            sample_hz=sample_hz,
            heartbeat_seconds=heartbeat_seconds,
            rotate_every_seconds=rotate_every_seconds,
            spool_dir=spool_root,
            outbox_dir=outbox_dir,
            inflight_dir=inflight_dir,
            sent_dir=sent_dir,
            dead_dir=dead_dir,
            max_spool_bytes=max_spool_bytes,
            max_spool_files=max_spool_files,
            flush_every_rows=flush_every_rows,
            upload_interval_seconds=upload_interval_seconds,
            max_retries_per_file=max_retries_per_file,
            upload_mode=upload_mode,
            request_timeout_seconds=request_timeout_seconds,
            sensor_mode=sensor_mode,
            sensor_script=sensor_script,
            sensor_script_shell=sensor_script_shell,
            firmware_version=firmware_version,
            fixed_lat=fixed_lat,
            fixed_lon=fixed_lon,
            battery_v=battery_v,
            rssi_dbm=rssi_dbm,
            seed=seed,
        )


# CSV schema for contract-backed edge telemetry ingestions.
# Keep aligned with: data/contracts/edge_telemetry.yaml
EDGE_TELEMETRY_FIELDS = [
    "event_id",
    "device_id",
    "event_type",
    "sensor",
    "value",
    "units",
    "ts",
    "lat",
    "lon",
    "battery_v",
    "rssi_dbm",
    "firmware_version",
    "status",
    "message",
]


class CSVSpool:
    """Append-only CSV spooler with rotation.

    Files are written to inflight/ and atomically moved to outbox/ on rotation.
    The CSV schema is contract-backed (EDGE_TELEMETRY_FIELDS).
    """

    def __init__(self, cfg: EdgeConfig) -> None:
        self.cfg = cfg
        self.current_path: Optional[Path] = None
        self.current_f: Optional[Any] = None
        self.current_writer: Optional[Any] = None
        self.current_started_at = 0.0
        self.rows_since_flush = 0

        for d in (cfg.spool_dir, cfg.outbox_dir, cfg.inflight_dir, cfg.sent_dir, cfg.dead_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Crash recovery: if the process was killed mid-file, move the stranded inflight
        # batches to outbox so they can be uploaded on next boot.
        for p in cfg.inflight_dir.glob("*.csv"):
            try:
                p.rename(cfg.outbox_dir / p.name)
            except Exception:
                pass

    def _new_inflight_path(self) -> Path:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        name = f"{self.cfg.device_id}_{ts}_{uuid.uuid4().hex}.csv"
        return self.cfg.inflight_dir / name

    def rotate(self) -> Optional[Path]:
        """Close the current file and move it to outbox/. Returns moved path if any."""
        if not self.current_f or not self.current_path:
            return None

        try:
            self.current_f.flush()
            os.fsync(self.current_f.fileno())
        except Exception:
            pass

        try:
            self.current_f.close()
        except Exception:
            pass

        dest = self.cfg.outbox_dir / self.current_path.name
        self.current_path.rename(dest)

        self.current_path = None
        self.current_f = None
        self.current_writer = None
        self.current_started_at = 0.0
        self.rows_since_flush = 0
        return dest

    def _open_if_needed(self) -> None:
        if self.current_f and self.current_path and self.current_writer:
            return

        self.current_path = self._new_inflight_path()
        self.current_started_at = time.time()
        # newline="" is important for csv.writer (avoids blank lines on some platforms)
        self.current_f = open(self.current_path, "a", newline="", buffering=1, encoding="utf-8")  # line-buffered
        self.current_writer = csv.writer(self.current_f)

        # header
        self.current_writer.writerow(EDGE_TELEMETRY_FIELDS)

    @staticmethod
    def _csv_cell(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            # Keep output stable-ish and readable; pandas will still parse it as float.
            s = f"{v:.6f}"
            s = s.rstrip("0").rstrip(".")
            return s
        return str(v)

    def append_event(self, event: Dict[str, Any]) -> None:
        """Append a contract-aligned event row to the current spool file."""
        self._open_if_needed()

        payload = dict(event or {})

        # Fill required fields even if caller provided empty/None values.
        if not payload.get("event_id"):
            payload["event_id"] = str(uuid.uuid4())
        if not payload.get("device_id"):
            payload["device_id"] = self.cfg.device_id
        if not payload.get("event_type"):
            payload["event_type"] = "reading"
        if not payload.get("ts"):
            payload["ts"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

        # Backwards-compat mapping (older scripts used sensor_type/unit).
        if not payload.get("sensor") and payload.get("sensor_type"):
            payload["sensor"] = payload.get("sensor_type")
        if not payload.get("units") and payload.get("unit"):
            payload["units"] = payload.get("unit")

        # Default firmware_version if configured.
        fw = getattr(self.cfg, "firmware_version", "")
        if fw and payload.get("firmware_version") in (None, ""):
            payload["firmware_version"] = fw

        row = [self._csv_cell(payload.get(k)) for k in EDGE_TELEMETRY_FIELDS]
        assert self.current_writer is not None
        self.current_writer.writerow(row)

        self.rows_since_flush += 1
        if self.rows_since_flush >= self.cfg.flush_every_rows:
            try:
                assert self.current_f is not None
                self.current_f.flush()
            except Exception:
                pass
            self.rows_since_flush = 0

    def append_reading(
        self,
        *,
        sensor: str,
        value: float,
        units: str,
        ts: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        battery_v: Optional[float] = None,
        rssi_dbm: Optional[int] = None,
        status: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        self.append_event(
            {
                "event_type": "reading",
                "sensor": sensor,
                "value": value,
                "units": units,
                "ts": ts,
                "lat": lat,
                "lon": lon,
                "battery_v": battery_v,
                "rssi_dbm": rssi_dbm,
                "status": status,
                "message": message,
            }
        )

    def append_heartbeat(
        self,
        *,
        status: str = "ok",
        message: Optional[str] = None,
        ts: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        battery_v: Optional[float] = None,
        rssi_dbm: Optional[int] = None,
    ) -> None:
        self.append_event(
            {
                "event_type": "heartbeat",
                "sensor": None,
                "value": None,
                "units": None,
                "ts": ts,
                "lat": lat,
                "lon": lon,
                "battery_v": battery_v,
                "rssi_dbm": rssi_dbm,
                "status": status,
                "message": message,
            }
        )

    def append_error(
        self,
        *,
        message: str,
        sensor: Optional[str] = None,
        ts: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        battery_v: Optional[float] = None,
        rssi_dbm: Optional[int] = None,
        status: str = "error",
    ) -> None:
        self.append_event(
            {
                "event_type": "error",
                "sensor": sensor,
                "value": None,
                "units": None,
                "ts": ts,
                "lat": lat,
                "lon": lon,
                "battery_v": battery_v,
                "rssi_dbm": rssi_dbm,
                "status": status,
                "message": message,
            }
        )

    def should_rotate(self) -> bool:
        if not self.current_started_at:
            return False
        return (time.time() - self.current_started_at) >= float(self.cfg.rotate_every_seconds)


def _spool_pressure(cfg: EdgeConfig) -> tuple[int, int]:
    """Return (total_bytes, total_files) for inflight+outbox."""
    total_bytes = 0
    total_files = 0
    for d in (cfg.inflight_dir, cfg.outbox_dir):
        try:
            for p in d.glob("*.csv"):
                try:
                    st = p.stat()
                    total_bytes += int(st.st_size)
                    total_files += 1
                except FileNotFoundError:
                    continue
        except FileNotFoundError:
            continue
    return total_bytes, total_files


def _device_headers(cfg: EdgeConfig) -> Dict[str, str]:
    h = {"X-Device-Id": cfg.device_id}
    if cfg.device_token:
        h["X-Device-Token"] = cfg.device_token
    return h


def _http_session() -> requests.Session:
    s = requests.Session()
    # Keep default TLS verification enabled.
    return s


def _get_meta(session: requests.Session, cfg: EdgeConfig) -> Optional[Dict[str, Any]]:
    url = f"{cfg.api_base_url}/api/meta"
    try:
        r = session.get(url, timeout=cfg.request_timeout_seconds)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _choose_upload_mode(cfg: EdgeConfig, meta: Optional[Dict[str, Any]]) -> str:
    mode = (cfg.upload_mode or "auto").lower()
    if mode in ("direct", "signed_url"):
        return mode
    # auto
    runtime = (meta or {}).get("runtime") if isinstance(meta, dict) else {}
    storage_backend = str((runtime or {}).get("storage_backend") or "")
    enable_edge_signed_urls = bool((runtime or {}).get("enable_edge_signed_urls"))
    if storage_backend == "gcs" and enable_edge_signed_urls:
        return "signed_url"
    return "direct"


def _is_retryable_status(code: int) -> bool:
    return code in (408, 409, 425, 429) or 500 <= code <= 599


class UploadAuthError(RuntimeError):
    pass


class EnrollError(RuntimeError):
    pass


class EnrollAuthError(EnrollError):
    pass


def _redact(value: str, *, keep: int = 6) -> str:
    v = str(value or "")
    if not v:
        return ""
    if len(v) <= keep:
        return "***"
    return v[:keep] + "…"


def _enroll_device(session: requests.Session, cfg: EdgeConfig) -> str:
    """Enroll the device and return a per-device token."""

    if not cfg.enroll_token:
        raise EnrollError("EDGE_ENROLL_TOKEN not configured")

    url = f"{cfg.api_base_url}/api/edge/enroll"
    headers = {
        "X-Device-Enroll-Token": cfg.enroll_token,
        # X-Device-Id is not required by the API for enroll, but including it
        # helps with request tracing.
        "X-Device-Id": cfg.device_id,
        "Content-Type": "application/json",
    }
    payload = {
        "device_id": cfg.device_id,
        "enroll_fingerprint": cfg.enroll_fingerprint,
        "label": cfg.device_label or None,
        "metadata": {
            "agent": "eventpulse-edge-agent",
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "arch": platform.machine(),
            "python": sys.version.split(" ", 1)[0],
            "sensor_mode": cfg.sensor_mode,
        },
    }

    try:
        r = session.post(url, json=payload, headers=headers, timeout=cfg.request_timeout_seconds)
    except requests.RequestException as e:
        raise EnrollError(str(e))

    if r.status_code in (401, 403):
        raise EnrollAuthError(f"enroll auth failed: {r.status_code}")
    if not r.ok:
        raise EnrollError(f"enroll failed ({r.status_code}): {r.text[:200]}")

    try:
        data = r.json()
    except Exception:
        raise EnrollError("enroll response was not JSON")

    token = str(data.get("device_token") or "").strip()
    if not token:
        raise EnrollError("enroll response missing device_token")

    return token


def _upload_direct(
    session: requests.Session,
    cfg: EdgeConfig,
    path: Path,
) -> Dict[str, Any]:
    url = f"{cfg.api_base_url}/api/edge/ingest/upload"
    params = {"dataset": cfg.dataset, "filename": path.name, "source": cfg.source}
    headers = _device_headers(cfg)
    headers["Content-Type"] = "application/octet-stream"

    with open(path, "rb") as f:
        r = session.post(url, params=params, data=f, headers=headers, timeout=cfg.request_timeout_seconds)

    if r.status_code in (401, 403):
        raise UploadAuthError(f"auth failed: {r.status_code}")
    if not r.ok:
        raise RuntimeError(f"upload failed ({r.status_code}): {r.text[:200]}")
    return r.json()


def _upload_signed_url(
    session: requests.Session,
    cfg: EdgeConfig,
    path: Path,
) -> Dict[str, Any]:
    sha256 = _sha256_file(path)
    init_url = f"{cfg.api_base_url}/api/edge/uploads/gcs_signed_url"
    init_payload = {
        "dataset": cfg.dataset,
        "filename": path.name,
        "sha256": sha256,
        "source": cfg.source,
        "content_type": "text/csv",
    }

    r = session.post(
        init_url,
        json=init_payload,
        headers=_device_headers(cfg),
        timeout=cfg.request_timeout_seconds,
    )
    if r.status_code in (401, 403):
        raise UploadAuthError(f"auth failed: {r.status_code}")
    if not r.ok:
        raise RuntimeError(f"signed-url init failed ({r.status_code}): {r.text[:200]}")
    info = r.json()

    upload_url = str(info.get("upload_url") or "")
    required_headers = info.get("required_headers") or {}
    object_name = str(info.get("object_name") or "")

    if not upload_url or not object_name:
        raise RuntimeError("signed-url response missing upload_url/object_name")

    # Upload to GCS via signed URL
    with open(path, "rb") as f:
        put = session.put(
            upload_url,
            data=f,
            headers=required_headers,
            timeout=cfg.request_timeout_seconds,
        )

    if put.status_code in (200, 201):
        pass
    elif put.status_code == 412:
        # Precondition failed (object already exists). This is expected on retries because
        # the signed URL is generated with ifGenerationMatch=0 for idempotency.
        pass
    else:
        raise RuntimeError(f"GCS PUT failed ({put.status_code}): {put.text[:200]}")

    # Finalize ingestion
    fin_url = f"{cfg.api_base_url}/api/edge/ingest/from_gcs"
    fin_payload = {"dataset": cfg.dataset, "object_name": object_name}
    fin = session.post(
        fin_url,
        json=fin_payload,
        headers=_device_headers(cfg),
        timeout=cfg.request_timeout_seconds,
    )

    if fin.status_code in (401, 403):
        raise UploadAuthError(f"auth failed: {fin.status_code}")
    if not fin.ok:
        raise RuntimeError(f"finalize failed ({fin.status_code}): {fin.text[:200]}")
    return fin.json()


def _upload_file(
    session: requests.Session,
    cfg: EdgeConfig,
    mode: str,
    path: Path,
) -> Dict[str, Any]:
    if mode == "signed_url":
        return _upload_signed_url(session, cfg, path)
    return _upload_direct(session, cfg, path)


def _sorted_csv_files(dirpath: Path) -> Iterable[Path]:
    files = [p for p in dirpath.glob("*.csv") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def run() -> int:
    cfg = EdgeConfig.from_env()
    if cfg.seed is not None:
        random.seed(cfg.seed)

    if cfg.sensor_mode == "script" and not cfg.sensor_script:
        print(
            "[edge] WARN: EDGE_SENSOR_MODE=script but EDGE_SENSOR_SCRIPT is empty. Falling back to simulated.",
            flush=True,
        )
        cfg = dataclasses.replace(cfg, sensor_mode="simulated")

    print(
        f"[edge] device_id={cfg.device_id} dataset={cfg.dataset} mode={cfg.upload_mode} api={cfg.api_base_url} ",
        flush=True,
    )
    print(
        f"[edge] token={'set' if bool(cfg.device_token) else 'missing'} "
        f"token_file={cfg.device_token_file} "
        f"enroll={'set' if bool(cfg.enroll_token) else 'missing'} "
        f"fingerprint={_redact(cfg.enroll_fingerprint)}",
        flush=True,
    )
    if cfg.fixed_lat is not None and cfg.fixed_lon is not None:
        print(f"[edge] fixed location lat={cfg.fixed_lat} lon={cfg.fixed_lon}", flush=True)
    if cfg.firmware_version:
        print(f"[edge] firmware_version={cfg.firmware_version}", flush=True)

    spool = CSVSpool(cfg)
    session = _http_session()
    meta = _get_meta(session, cfg)
    mode = _choose_upload_mode(cfg, meta)

    print(f"[edge] resolved upload_mode={mode}", flush=True)

    # Best-effort enrollment on start (only if token is missing).
    if not cfg.device_token and cfg.enroll_token:
        try:
            token = _enroll_device(session, cfg)
            _save_device_token_file(cfg.device_token_file, token)
            cfg = dataclasses.replace(cfg, device_token=token)
            print("[edge] enrolled device token (saved to token_file)", flush=True)
        except EnrollAuthError as e:
            print(f"[edge] WARN: enroll auth rejected: {e}", flush=True)
        except EnrollError as e:
            print(f"[edge] WARN: enroll failed: {e}", flush=True)

    auth_required: Optional[bool] = None

    # Optional ping on start (helps validate auth)
    try:
        ping = session.get(
            f"{cfg.api_base_url}/api/edge/ping",
            headers=_device_headers(cfg),
            timeout=cfg.request_timeout_seconds,
        )
        if ping.status_code in (401, 403):
            auth_required = True
            print("[edge] WARN: device auth rejected (check token / provisioning)", flush=True)
        elif ping.ok:
            auth_required = False
            print("[edge] ping ok", flush=True)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Sensor configuration (simulated defaults)
    # ------------------------------------------------------------------

    sim_sensors = [
        # Wider ranges help demo/bring-up by naturally producing alert states.
        ("temp_c", "C", 5.0, 95.0),
        ("humidity_pct", "%", 5.0, 100.0),
        ("water_pressure_psi", "psi", 0.0, 160.0),
        ("oil_pressure_psi", "psi", 0.0, 100.0),
        ("oil_life_pct", "%", 0.0, 100.0),
        ("oil_level_pct", "%", 0.0, 100.0),
        ("drip_oil_level_pct", "%", 0.0, 100.0),
        ("vibration_g", "g", 0.0, 8.0),
    ]

    def common_enrichment() -> Dict[str, Any]:
        # Fixed site coords (or optional simulated jitter)
        lat = cfg.fixed_lat
        lon = cfg.fixed_lon
        if cfg.sensor_mode == "simulated" and lat is not None and lon is not None:
            # Small jitter makes the UI feel alive while still representing a fixed site.
            lat = lat + random.uniform(-0.0003, 0.0003)
            lon = lon + random.uniform(-0.0003, 0.0003)

        # Battery + signal are often not available without extra hardware/modem tooling.
        battery_v = cfg.battery_v
        rssi_dbm = cfg.rssi_dbm
        if cfg.sensor_mode == "simulated":
            if battery_v is None:
                battery_v = round(random.uniform(3.6, 4.2), 3)
            if rssi_dbm is None:
                rssi_dbm = int(random.uniform(-112, -70))

        return {
            "lat": lat,
            "lon": lon,
            "battery_v": battery_v,
            "rssi_dbm": rssi_dbm,
        }

    def parse_sensor_text(raw: str) -> list[Dict[str, Any]]:
        """Parse sensor output into one or more event dicts.

        Supported formats:
        - JSON object (single event) or JSON list (multiple events)
        - CSV line: sensor,value,units
        - Float: value (sensor defaults to script_value)
        """
        raw = (raw or "").strip()
        if not raw:
            return []

        events: list[Dict[str, Any]] = []
        for line in raw.splitlines():
            s = line.strip()
            if not s:
                continue

            if s.startswith("{") or s.startswith("["):
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict):
                        events.append(obj)
                        continue
                    if isinstance(obj, list):
                        for item in obj:
                            if isinstance(item, dict):
                                events.append(item)
                        continue
                except Exception:
                    # Fall through to CSV/float parsing
                    pass

            # CSV-ish: sensor,value[,units]
            parts = [p.strip() for p in s.split(",") if p.strip() != ""]
            if len(parts) >= 2:
                sensor = parts[0]
                try:
                    value = float(parts[1])
                except Exception:
                    continue
                units = parts[2] if len(parts) >= 3 else "unit"
                events.append({"sensor": sensor, "value": value, "units": units, "event_type": "reading"})
                continue

            # Float-only
            try:
                value = float(s)
                events.append({"sensor": "script_value", "value": value, "units": "unit", "event_type": "reading"})
                continue
            except Exception:
                continue

        return events

    # ------------------------------------------------------------------
    # Main loops
    # ------------------------------------------------------------------

    last_heartbeat = 0.0
    last_rotate_check = 0.0
    last_upload = 0.0
    last_enroll_attempt = 0.0
    last_sample = 0.0
    tick = 0

    sample_interval = 1.0 / max(0.1, float(cfg.sample_hz))
    retries: Dict[str, int] = {}

    while True:
        now = time.time()

        # If we don't have a token but we do have an enrollment token, attempt to
        # enroll periodically. This allows a device to be flashed/booted offline
        # and obtain a token once connectivity returns.
        if not cfg.device_token and cfg.enroll_token:
            if (now - last_enroll_attempt) >= float(cfg.enroll_every_seconds):
                last_enroll_attempt = now
                try:
                    token = _enroll_device(session, cfg)
                    _save_device_token_file(cfg.device_token_file, token)
                    cfg = dataclasses.replace(cfg, device_token=token)
                    print("[edge] enrolled device token (saved to token_file)", flush=True)
                except EnrollAuthError as e:
                    print(f"[edge] WARN: enroll auth rejected: {e}", flush=True)
                except EnrollError as e:
                    print(f"[edge] WARN: enroll failed: {e}", flush=True)

        # Upload loop
        if (now - last_upload) >= float(cfg.upload_interval_seconds):
            last_upload = now

            # If auth is required and we still lack a token, skip uploads (avoid noisy 401 spam).
            if auth_required is True and not cfg.device_token:
                time.sleep(1.0)
                continue

            for fpath in _sorted_csv_files(cfg.outbox_dir):
                key = str(fpath)
                attempts = retries.get(key, 0)
                if attempts >= cfg.max_retries_per_file:
                    # Quarantine after too many failures (avoid infinite loops).
                    dest = cfg.dead_dir / fpath.name
                    try:
                        fpath.rename(dest)
                        print(f"[edge] moved to dead-letter after {attempts} attempts: {dest.name}", flush=True)
                    except Exception as e:
                        print(f"[edge] ERROR moving to dead-letter: {e}", flush=True)
                    retries.pop(key, None)
                    continue

                try:
                    resp = _upload_file(session, cfg, mode, fpath)
                    dest = cfg.sent_dir / fpath.name
                    fpath.rename(dest)
                    retries.pop(key, None)
                    print(f"[edge] uploaded {dest.name} -> ingestion_id={resp.get('ingestion_id')}", flush=True)
                except UploadAuthError as e:
                    # If we have an enroll token, try to self-heal by re-enrolling.
                    print(f"[edge] AUTH ERROR uploading {fpath.name}: {e}", flush=True)
                    if cfg.enroll_token:
                        try:
                            token = _enroll_device(session, cfg)
                            _save_device_token_file(cfg.device_token_file, token)
                            cfg = dataclasses.replace(cfg, device_token=token)
                            print("[edge] re-enrolled device token after auth error", flush=True)
                        except Exception as ee:
                            print(f"[edge] WARN: re-enroll failed: {ee}", flush=True)
                    time.sleep(15)
                except requests.RequestException as e:
                    retries[key] = attempts + 1
                    backoff = min(60.0, 2.0 ** min(attempts, 8))
                    print(f"[edge] network error uploading {fpath.name}: {e} (retry in ~{backoff:.1f}s)", flush=True)
                    time.sleep(backoff)
                except Exception as e:
                    retries[key] = attempts + 1
                    backoff = min(60.0, 2.0 ** min(attempts, 8))
                    print(f"[edge] upload failed {fpath.name}: {e} (retry in ~{backoff:.1f}s)", flush=True)
                    time.sleep(backoff)

        # Spool pressure: avoid filling disks if offline for a long time.
        spool_bytes, spool_files = _spool_pressure(cfg)
        paused = False
        if spool_bytes > cfg.max_spool_bytes or spool_files > cfg.max_spool_files:
            paused = True
            print(
                f"[edge] WARN: spool pressure high: {spool_files} files / {spool_bytes / 1024 / 1024:.1f} MB. "
                "Pausing sampling until uploads catch up.",
                flush=True,
            )

        # Sampling loop (rate-limited by EDGE_SAMPLE_HZ)
        if not paused and (now - last_sample) >= sample_interval:
            last_sample = now
            enrich = common_enrichment()
            try:
                if cfg.sensor_mode == "stdin":
                    # Non-blocking read so uploads/heartbeats still run.
                    ready = False
                    try:
                        ready = bool(select.select([sys.stdin], [], [], 0.0)[0])
                    except Exception:
                        ready = False

                    if ready:
                        line = sys.stdin.readline()
                        for ev in parse_sensor_text(line):
                            merged = {**enrich, **ev}
                            spool.append_event(merged)

                elif cfg.sensor_mode == "script" and cfg.sensor_script:
                    # Call an external script (can output JSON or CSV lines).
                    if cfg.sensor_script_shell:
                        out_bytes = subprocess.check_output(
                            cfg.sensor_script,
                            shell=True,
                            timeout=max(5.0, sample_interval),
                        )
                    else:
                        cmd = shlex.split(cfg.sensor_script)
                        if not cmd:
                            raise RuntimeError("EDGE_SENSOR_SCRIPT is empty after parsing")
                        out_bytes = subprocess.check_output(
                            cmd,
                            shell=False,
                            timeout=max(5.0, sample_interval),
                        )
                    out = out_bytes.decode("utf-8", errors="ignore")
                    evs = parse_sensor_text(out)
                    if not evs:
                        # If the script outputs a single float without newlines, parse_sensor_text covers it,
                        # but this fallback helps if the output had extra whitespace.
                        evs = parse_sensor_text(out.strip())
                    for ev in evs:
                        merged = {**enrich, **ev}
                        spool.append_event(merged)

                else:
                    # Simulated sensors: round-robin across a sane default set.
                    sensor, units, lo, hi = sim_sensors[tick % len(sim_sensors)]
                    tick += 1
                    value = round(random.uniform(lo, hi), 3)
                    spool.append_reading(sensor=sensor, value=value, units=units, **enrich)

            except Exception as e:
                msg = f"sensor error ({cfg.sensor_mode}): {e}"
                print(f"[edge] WARN: {msg}", flush=True)
                spool.append_error(message=msg, **common_enrichment())

        # Heartbeat (independent cadence)
        now = time.time()
        if (now - last_heartbeat) >= float(cfg.heartbeat_seconds):
            last_heartbeat = now
            spool_bytes, spool_files = _spool_pressure(cfg)

            status = "ok"
            message = None
            # Mark degraded as we approach spool limits.
            if spool_bytes > cfg.max_spool_bytes * 0.8 or spool_files > cfg.max_spool_files * 0.8:
                status = "degraded"
                message = f"spool_pressure bytes={spool_bytes} files={spool_files}"

            spool.append_heartbeat(status=status, message=message, **common_enrichment())

        # Rotate
        if (now - last_rotate_check) >= 1.0:
            last_rotate_check = now
            if spool.should_rotate():
                moved = spool.rotate()
                if moved:
                    print(f"[edge] rotated -> outbox/{moved.name}", flush=True)

        # Sleep a bit to avoid a tight spin loop; keep it proportional to sample rate.
        sleep_s = max(0.05, min(0.5, sample_interval / 2.0))
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(run())
