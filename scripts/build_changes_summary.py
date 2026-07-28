#!/usr/bin/env python3
"""
Build a detailed changes summary from per-product diff files.

Includes the full OpenAPI spec definition for each changed schema and path
so the SDK agent has complete type information (properties, formats, required
fields, nested structures, etc.) to generate accurate SDK code.

Usage:
    CHANGED_PRODUCTS=orders,payments python scripts/build_changes_summary.py

Output (stdout, JSON string):
    {
      "orders": {
        "total_changes": 8,
        "paths": {
          "added": { "/v1/orders/{order_id}/confirm": { ...full path def... } },
          "modified": { ... },
          "removed": [...]
        },
        "schemas": {
          "added": { "ConfirmOrderRequest": { ...full schema def... } },
          "modified": { "RefundsResponse": { "properties_added": {...}, "properties_removed": [...] } },
          "removed": [...]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BY_PRODUCT = ROOT / "by-product"


def _load_spec(product: str) -> dict:
    """Load the bundled spec for a product, falling back to the root spec."""
    spec_path = BY_PRODUCT / product / "spec3.yaml"
    if spec_path.exists():
        return yaml.safe_load(spec_path.read_text()) or {}
    root_spec = ROOT / "spec3.yaml"
    if root_spec.exists():
        return yaml.safe_load(root_spec.read_text()) or {}
    return {}


def _full_schema(name: str, all_schemas: dict) -> dict:
    """Return the full schema definition, resolving inline $ref if present."""
    schema = all_schemas.get(name, {})
    if not schema:
        return {}
    return schema


def _property_defs(prop_names: list[str], all_props: dict) -> dict:
    """Return full definitions for a list of property names."""
    return {p: all_props[p] for p in prop_names if p in all_props}


def build_payload(changed_products: str) -> dict:
    """
    Build the structured changes payload for all changed products.
    Returns a dict keyed by product slug.
    """
    products = [p.strip() for p in changed_products.split(",") if p.strip()]
    result = {}

    for product in products:
        diff_path = BY_PRODUCT / product / "diff.yaml"
        if not diff_path.exists():
            result[product] = {"error": "no diff file found"}
            continue

        diff = yaml.safe_load(diff_path.read_text()) or {}
        spec = _load_spec(product)
        all_schemas = spec.get("components", {}).get("schemas", {})
        all_paths = spec.get("paths", {})

        total = diff.get("total_changes", 0)
        paths_diff = diff.get("paths", {})
        schemas_diff = diff.get("schemas", {})

        # ── Paths ────────────────────────────────────────────────────────────
        paths_out: dict = {}

        added_paths = {}
        for api_path in (paths_diff.get("added") or []):
            path_def = all_paths.get(api_path)
            if path_def:
                added_paths[api_path] = path_def
            else:
                added_paths[api_path] = {}
        if added_paths:
            paths_out["added"] = added_paths

        if paths_diff.get("removed"):
            paths_out["removed"] = paths_diff["removed"]

        modified_paths = {}
        modified_detail = {
            d["path"]: d
            for d in (paths_diff.get("detail", {}).get("modified") or [])
            if isinstance(d, dict)
        }
        for api_path in (paths_diff.get("modified") or []):
            entry: dict = {}
            if api_path in all_paths:
                entry["spec"] = all_paths[api_path]
            detail = modified_detail.get(api_path, {})
            if detail.get("methods_added"):
                entry["methods_added"] = detail["methods_added"]
            if detail.get("methods_removed"):
                entry["methods_removed"] = detail["methods_removed"]
            if detail.get("methods_modified"):
                entry["methods_modified"] = detail["methods_modified"]
            modified_paths[api_path] = entry
        if modified_paths:
            paths_out["modified"] = modified_paths

        # ── Schemas ──────────────────────────────────────────────────────────
        schemas_out: dict = {}

        added_schemas = {}
        for schema_name in (schemas_diff.get("added") or []):
            full = _full_schema(schema_name, all_schemas)
            added_schemas[schema_name] = full if full else {}
        if added_schemas:
            schemas_out["added"] = added_schemas

        if schemas_diff.get("removed"):
            schemas_out["removed"] = schemas_diff["removed"]

        modified_schemas = {}
        schema_mod_detail = {
            d["name"]: d
            for d in (schemas_diff.get("detail", {}).get("modified") or [])
            if isinstance(d, dict)
        }
        for schema_name in (schemas_diff.get("modified") or []):
            schema_def = all_schemas.get(schema_name, {})
            all_props = schema_def.get("properties", {})
            detail = schema_mod_detail.get(schema_name, {})
            added_props = detail.get("properties_added") or []
            removed_props = detail.get("properties_removed") or []

            entry = {}
            if added_props:
                entry["properties_added"] = _property_defs(added_props, all_props)
            if removed_props:
                entry["properties_removed"] = removed_props
            entry["full_schema"] = schema_def
            modified_schemas[schema_name] = entry
        if modified_schemas:
            schemas_out["modified"] = modified_schemas

        result[product] = {
            "total_changes": total,
            "paths": paths_out,
            "schemas": schemas_out,
        }

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build SDK request body from product diffs")
    parser.add_argument(
        "--flow",
        default="sdk_generation_test",
        help="Flow name or JSON array of flow names sent to spec-agent",
    )
    parser.add_argument("--output", metavar="FILE", help="Write full request body JSON to FILE")
    args = parser.parse_args()

    changed = os.environ.get("CHANGED_PRODUCTS", "")
    if not changed:
        print("No products provided via CHANGED_PRODUCTS", file=sys.stderr)
        sys.exit(1)

    changes = build_payload(changed)

    # The spec-agent API requires `changes` to be a string.
    # We serialize the structured payload as a compact JSON string.
    changes_str = json.dumps(changes, ensure_ascii=False, separators=(",", ":"))

    flow: str | list[str]
    try:
        parsed_flow = json.loads(args.flow)
        if isinstance(parsed_flow, list) and all(isinstance(item, str) for item in parsed_flow):
            flow = parsed_flow
        elif isinstance(parsed_flow, str):
            flow = parsed_flow
        else:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        flow = args.flow

    if args.output:
        body = {"flow": flow, "changes": changes_str}
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        print(json.dumps(changes, ensure_ascii=False, indent=2))
    else:
        print(changes_str)
