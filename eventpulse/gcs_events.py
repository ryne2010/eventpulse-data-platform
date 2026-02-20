from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class RawObjectRef:
    """Parsed reference to an immutable raw object in the landing zone."""

    dataset: str
    day: str
    sha256: str
    ext: str
    object_name: str


def is_valid_sha256_hex(value: str) -> bool:
    return bool(_SHA256_HEX_RE.match((value or "").lower()))


def build_raw_object_name(*, raw_prefix: str, dataset: str, day: str, sha256: str, ext: str) -> str:
    """Build an object name for a raw artifact.

    raw_prefix may contain slashes (e.g. "raw/dev").
    """

    prefix = (raw_prefix or "").strip("/")
    ext_norm = (ext or "").lower()
    if ext_norm and not ext_norm.startswith("."):
        ext_norm = f".{ext_norm}"

    if prefix:
        return f"{prefix}/{dataset}/{day}/{sha256}{ext_norm}"
    return f"{dataset}/{day}/{sha256}{ext_norm}"


def parse_raw_object_name(*, raw_prefix: str, object_name: str) -> Optional[RawObjectRef]:
    """Parse a raw object name.

    Expected shape:
      <raw_prefix>/<dataset>/<YYYY-MM-DD>/<sha256><ext>

    raw_prefix may contain slashes (e.g. "raw/dev").

    Returns None if the object name doesn't match the scheme.
    """

    obj = (object_name or "").lstrip("/")
    if not obj:
        return None

    prefix = (raw_prefix or "").strip("/")

    remainder = obj
    if prefix:
        if not remainder.startswith(prefix + "/"):
            return None
        remainder = remainder[len(prefix) + 1 :]

    parts = remainder.split("/")
    if len(parts) != 3:
        return None

    dataset, day, filename = parts[0], parts[1], parts[2]

    # Defense-in-depth: ensure we only accept the day partition shape we write.
    if not _DAY_RE.match(day):
        return None

    sha, ext = os.path.splitext(filename)
    sha = (sha or "").lower()
    ext = (ext or "").lower()

    if not is_valid_sha256_hex(sha):
        return None

    return RawObjectRef(dataset=dataset, day=day, sha256=sha, ext=ext, object_name=obj)
