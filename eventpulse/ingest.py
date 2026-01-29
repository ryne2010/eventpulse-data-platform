import hashlib
import os
import shutil
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

from .config import settings
from .db import insert_ingestion


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def store_raw_file(dataset: str, src_path: str) -> Tuple[str, str, str]:
    """Copies a file into the immutable raw landing zone.
    Returns (sha256, raw_path, file_ext).
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    filename = os.path.basename(src_path)
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext not in settings.allowed_file_exts:
        raise ValueError(f"File extension '{ext}' not allowed. Allowed: {settings.allowed_file_exts}")

    # size check
    max_bytes = settings.max_file_mb * 1024 * 1024
    if os.path.getsize(src_path) > max_bytes:
        raise ValueError(f"File too large (> {settings.max_file_mb} MB)")

    sha = sha256_file(src_path)
    day = datetime.utcnow().strftime("%Y-%m-%d")
    raw_dir = os.path.join(settings.raw_data_dir, dataset, day)
    _ensure_dir(raw_dir)
    raw_path = os.path.join(raw_dir, f"{sha}{ext}")

    # Immutable-ish: never overwrite if already exists
    if not os.path.exists(raw_path):
        shutil.copy2(src_path, raw_path)

    return sha, raw_path, ext


def create_ingestion_record(
    dataset: str,
    source: Optional[str],
    src_path: str,
) -> str:
    filename = os.path.basename(src_path)
    sha, raw_path, ext = store_raw_file(dataset, src_path)
    ingestion_id = insert_ingestion(
        dataset=dataset,
        source=source,
        filename=filename,
        file_ext=ext,
        sha256=sha,
        raw_path=raw_path,
    )
    return str(ingestion_id)
