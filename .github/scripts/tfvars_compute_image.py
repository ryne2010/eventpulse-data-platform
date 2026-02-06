#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def _get(text: str, key: str) -> str:
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*"([^"]+)"\s*$", text, flags=re.MULTILINE)
    if not m:
        raise SystemExit(f"Missing {key} in terraform.tfvars")
    return m.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute Artifact Registry image URI from terraform.tfvars + tag")
    parser.add_argument("--tfvars", required=True, help="Path to terraform.tfvars")
    parser.add_argument("--tag", required=True, help="Image tag")
    parser.add_argument("--default-image-name", default="eventpulse-api")
    args = parser.parse_args()

    text = Path(args.tfvars).read_text()

    project_id = _get(text, "project_id")
    region = _get(text, "region")
    repo_name = _get(text, "artifact_repo_name")

    m = re.search(r'^\s*image_name\s*=\s*"([^"]+)"\s*$', text, flags=re.MULTILINE)
    image_name = m.group(1) if m else args.default_image_name

    print(f"{region}-docker.pkg.dev/{project_id}/{repo_name}/{image_name}:{args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
