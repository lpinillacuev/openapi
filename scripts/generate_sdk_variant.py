#!/usr/bin/env python3
"""
Generate spec3.sdk.yaml and spec3.sdk.json from spec3.yaml.

The SDK variant mirrors the public spec and preserves the existing
x-mp-sdk-coverage annotations for operations that already had them. New
operations receive an empty coverage list.

Usage:
    python scripts/generate_sdk_variant.py
    python scripts/generate_sdk_variant.py spec3.yaml spec3.sdk.yaml spec3.sdk.json
"""

from __future__ import annotations

import copy
import datetime
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
SDK_LANGUAGES = ["php", "nodejs", "java", "python", "ruby", "dotnet", "go"]


class _SafeEncoder(json.JSONEncoder):
    def default(self, obj: object) -> object:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return str(obj)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as exc:
        print(f"Failed to parse {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def collect_existing_coverage(sdk_spec: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    coverage: dict[tuple[str, str], list[str]] = {}
    for api_path, path_item in (sdk_spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            value = operation.get("x-mp-sdk-coverage", [])
            coverage[(api_path, method)] = value if isinstance(value, list) else []
    return coverage


def build_sdk_spec(source_spec: dict[str, Any], previous_sdk_spec: dict[str, Any]) -> dict[str, Any]:
    sdk_spec = copy.deepcopy(source_spec)
    previous_coverage = collect_existing_coverage(previous_sdk_spec)

    info = sdk_spec.setdefault("info", {})
    description = info.get("description", "").rstrip()
    sdk_note = (
        "### SDK Variant\n\n"
        "This file is the SDK variant of the public spec. Each operation includes\n"
        "`x-mp-sdk-coverage` listing which official SDKs implement that endpoint:\n"
        "`php`, `nodejs`, `java`, `python`, `ruby`, `dotnet`, `go`.\n"
        "An empty list means the endpoint exists in the API but has no current SDK implementation."
    )
    if "### SDK Variant" not in description:
        info["description"] = f"{description}\n\n{sdk_note}\n" if description else f"{sdk_note}\n"

    sdk_spec["x-mp-spec-variant"] = "sdk"

    for api_path, path_item in (sdk_spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            existing = previous_coverage.get((api_path, method), [])
            operation["x-mp-sdk-coverage"] = [
                language for language in existing if language in SDK_LANGUAGES
            ]

    return sdk_spec


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spec3.yaml")
    yaml_dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("spec3.sdk.yaml")
    json_dst = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("spec3.sdk.json")

    source_spec = load_yaml(src)
    previous_sdk_spec = load_yaml(yaml_dst) if yaml_dst.exists() else {}
    sdk_spec = build_sdk_spec(source_spec, previous_sdk_spec)

    yaml_dst.write_text(
        yaml.dump(
            sdk_spec,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ),
        encoding="utf-8",
    )
    json_dst.write_text(
        json.dumps(sdk_spec, indent=2, ensure_ascii=False, cls=_SafeEncoder) + "\n",
        encoding="utf-8",
    )

    print(f"{yaml_dst} generated")
    print(f"{json_dst} generated")


if __name__ == "__main__":
    main()
