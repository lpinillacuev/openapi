#!/usr/bin/env python3
"""
Check that spec3.yaml contains no external $ref.

An external $ref is any $ref whose value does not start with '#'
(i.e. it points to another file like common.yaml#/... or schemas/foo.yaml).

Usage:
    python scripts/check_external_refs.py                  # checks spec3.yaml
    python scripts/check_external_refs.py by-site/MLB/spec3.yaml

Exit code 1 if any external $ref is found, 0 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def find_external_refs(obj: object, path: str = "$") -> list[tuple[str, str]]:
    """Traverse obj recursively and return (json_path, ref) for every external $ref."""
    found: list[tuple[str, str]] = []

    if isinstance(obj, dict):
        ref = obj.get("$ref", "")
        if isinstance(ref, str) and ref and not ref.startswith("#"):
            found.append((path, ref))
        for key, value in obj.items():
            if key != "$ref":
                found.extend(find_external_refs(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(find_external_refs(item, f"{path}[{i}]"))

    return found


def main() -> None:
    spec_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spec3.yaml")

    if not spec_path.exists():
        print(f"❌ File not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    spec = yaml.safe_load(spec_path.read_text()) or {}
    external = find_external_refs(spec)

    if external:
        print(f"❌ Found {len(external)} external $ref(s) in {spec_path}:")
        for json_path, ref in external:
            print(f"   {json_path}: {ref}")
        print()
        print("Fix: run  python scripts/bundle.py --schemas-only  to bundle all external refs.")
        sys.exit(1)

    print(f"✅ No external $ref — {spec_path} is self-contained.")


if __name__ == "__main__":
    main()
