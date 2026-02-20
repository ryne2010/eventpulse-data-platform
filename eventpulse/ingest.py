import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from .config import settings
from .db import insert_ingestion
from .gcp_rest import gcs_object_exists, gcs_upload_file
from .naming import normalize_dataset_name


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_file(path: str) -> Tuple[str, str]:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if not os.path.isfile(path):
        raise ValueError(f"Not a file: {path}")

    filename = os.path.basename(path)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in settings.allowed_file_exts:
        raise ValueError(f"File extension '{ext}' not allowed. Allowed: {settings.allowed_file_exts}")

    # size check
    max_bytes = settings.max_file_mb * 1024 * 1024
    if os.path.getsize(path) > max_bytes:
        raise ValueError(f"File too large (> {settings.max_file_mb} MB)")

    return filename, ext


def store_raw_file(dataset: str, src_path: str) -> Tuple[str, str, str]:
    """Copy a file into the immutable raw landing zone.

    Returns (sha256, raw_path, file_ext).

    raw_path:
    - local backend: absolute filesystem path
    - gcs backend: gs://bucket/object
    """

    dataset = normalize_dataset_name(dataset)
    filename, ext = _validate_file(src_path)

    sha = sha256_file(src_path)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if settings.storage_backend == "gcs":
        if not settings.raw_gcs_bucket:
            raise ValueError("RAW_GCS_BUCKET must be set when STORAGE_BACKEND=gcs")

        prefix = (settings.raw_gcs_prefix or "raw").strip("/")
        object_name = f"{prefix}/{dataset}/{day}/{sha}{ext}"

        if not gcs_object_exists(settings.raw_gcs_bucket, object_name):
            gcs_upload_file(settings.raw_gcs_bucket, object_name, src_path)

        return sha, f"gs://{settings.raw_gcs_bucket}/{object_name}", ext

    # local filesystem
    raw_dir = Path(settings.raw_data_dir) / dataset / day
    _ensure_dir(raw_dir)
    raw_path = raw_dir / f"{sha}{ext}"

    # Immutable-ish: never overwrite if already exists
    if not raw_path.exists():
        shutil.copy2(src_path, raw_path)

    return sha, str(raw_path), ext


def create_ingestion_record(
    dataset: str,
    source: Optional[str],
    src_path: str,
) -> str:
    dataset = normalize_dataset_name(dataset)
    filename, ext = _validate_file(src_path)

    sha, raw_path, _ = store_raw_file(dataset, src_path)

    ingestion_id = insert_ingestion(
        dataset=dataset,
        source=source,
        filename=filename,
        file_ext=ext,
        sha256=sha,
        raw_path=raw_path,
    )
    return str(ingestion_id)
