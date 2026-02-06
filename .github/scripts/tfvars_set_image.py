#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Set image="..." in terraform.tfvars")
    parser.add_argument("--tfvars", required=True, help="Path to terraform.tfvars")
    parser.add_argument("--image", required=True, help="Full image URI")
    args = parser.parse_args()

    p = Path(args.tfvars)
    text = p.read_text()

    if re.search(r'^\s*image\s*=.*$', text, flags=re.MULTILINE):
        text = re.sub(
            r'^\s*image\s*=\s*"[^"]*"\s*$',
            f'image = "{args.image}"',
            text,
            flags=re.MULTILINE,
        )
    else:
        text = text.rstrip() + f"
image = "{args.image}"
"

    p.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
