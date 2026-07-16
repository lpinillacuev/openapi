#!/usr/bin/env python3
"""
Trigger SDK generation for products that changed after a merge.

Reads by-product/{product}/diff.yaml and by-product/{product}/spec3.yaml,
transforms the diff into the SDK generator API format, and POSTs
to the spec-agent-generator service.

Only products with sdk configuration in apps.yaml are processed.

Usage:
    python scripts/push_to_sdk.py --apps payments,customers
    python scripts/push_to_sdk.py --all
    python scripts/push_to_sdk.py --all --dry-run

Environment variables:
    SDK_GENERATOR_URL     Base URL of the spec-agent-generator service
    SDK_GENERATOR_TOKEN   Bearer token for authentication
    SDK_REPO_PYTHON       Target repo URL for Python SDK (e.g. https://github.com/mercadopago/sdk-python)
    SDK_REPO_JAVA         Target repo URL for Java SDK
    SDK_REPO_NODE         Target repo URL for Node.js SDK
    SDK_REPO_PHP          Target repo URL for PHP SDK
    SDK_REPO_RUBY         Target repo URL for Ruby SDK
    SDK_REPO_GO           Target repo URL for Go SDK
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
APPS_CONFIG_PATH = ROOT / "apps.yaml"
BY_PRODUCT = ROOT / "by-product"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SDK_GENERATOR_URL = os.environ.get(
    "SDK_GENERATOR_URL",
    "https://spec-agent-generator-test.melioffice.com",
)
SDK_GENERATOR_TOKEN = os.environ.get("SDK_GENERATOR_TOKEN", "")
SDK_GENERATOR_ENDPOINT = "/spec-agent/generate"
SPEC_VERSION = "1"


# ---------------------------------------------------------------------------
# Helpers — rich detail builders
# ---------------------------------------------------------------------------

def _field_descriptor(name: str, prop: dict[str, Any], required_fields: list[str]) -> str:
    """Build 'fieldname (type, required)' or 'fieldname (type)' string."""
    prop_type = prop.get("type", "")
    ref = prop.get("$ref", "")
    fmt = prop.get("format", "")
    default = prop.get("default")
    deprecated = prop.get("deprecated", False)

    if ref:
        type_str = ref.rsplit("/", 1)[-1] + " ref"
    elif fmt:
        type_str = fmt
    elif prop_type:
        type_str = prop_type
    else:
        type_str = "object"

    parts = [type_str]
    if name in required_fields:
        parts.append("required")
    if default is not None:
        parts.append(f"default {default}")
    if deprecated:
        parts.append("deprecated")

    return f"{name} ({', '.join(parts)})"


def _describe_new_schema(schema_name: str, spec: dict[str, Any]) -> str:
    """Build rich detail for a new schema using full spec definition."""
    schema = spec.get("components", {}).get("schemas", {}).get(schema_name, {})
    props = schema.get("properties", {})
    required = schema.get("required", [])
    description = schema.get("description", "")

    if not props:
        return f"Create {schema_name} model."

    field_parts = [_field_descriptor(n, p, required) for n, p in props.items()]
    detail = f"Create {schema_name} model"
    if description:
        detail += f". {description}"
    detail += f". Fields: {', '.join(field_parts)}."
    return detail


def _describe_modified_schema(
    schema_name: str,
    properties_added: list[str],
    properties_removed: list[str],
    spec: dict[str, Any],
    affected_endpoints: list[str],
) -> str:
    """Build rich detail for a modified schema: REMOVE ... ADD ... with types."""
    schema = spec.get("components", {}).get("schemas", {}).get(schema_name, {})
    props = schema.get("properties", {})
    required = schema.get("required", [])

    parts = []

    if properties_removed:
        parts.append(f"REMOVE fields: {', '.join(properties_removed)}")

    if properties_added:
        added_descriptors = []
        for field in properties_added:
            prop_def = props.get(field, {})
            added_descriptors.append(_field_descriptor(field, prop_def, required))
        parts.append(f"ADD fields: {', '.join(added_descriptors)}")

    if not parts:
        return f"Schema {schema_name} was modified. Review and update the SDK model accordingly."

    detail = ". ".join(parts) + "."
    if affected_endpoints:
        detail += f" Affects: {', '.join(affected_endpoints)}."
    return detail


def _find_endpoints_using_schema(schema_name: str, spec: dict[str, Any]) -> list[str]:
    """Find all endpoints (METHOD /path) that directly reference a schema."""
    affected = []
    ref_target = f"#/components/schemas/{schema_name}"

    for path, path_item in (spec.get("paths") or {}).items():
        for method, op in (path_item or {}).items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            op_str = str(op)
            if ref_target in op_str:
                affected.append(f"{method.upper()} {path}")

    return affected


def _describe_new_path(path_detail: dict[str, Any], spec: dict[str, Any]) -> str:
    """Build detail for a newly added path from its spec definition."""
    api_path = path_detail.get("path", "")
    methods = path_detail.get("methods", {})
    parts = []

    for method, op_summary in methods.items():
        if not isinstance(op_summary, dict):
            continue
        summary = op_summary.get("summary", "")
        request_body = op_summary.get("requestBody", "")
        responses = op_summary.get("responses", [])
        line = f"{method.upper()} {api_path}"
        if summary:
            line += f" — {summary}"
        if request_body:
            line += f". Request: {request_body}"
        if responses:
            line += f". Responses: {', '.join(responses)}"
        parts.append(line)

    return " | ".join(parts) if parts else f"Add {api_path} endpoint."


def _describe_modified_path(path_detail: dict[str, Any]) -> str:
    """Build detail for a modified path."""
    api_path = path_detail.get("path", "")
    methods_modified = path_detail.get("methods_modified", [])
    methods_added = path_detail.get("methods_added", [])
    methods_removed = path_detail.get("methods_removed", [])

    parts = []
    if methods_added:
        parts.append(f"Added methods: {', '.join(str(m) for m in methods_added)}")
    if methods_removed:
        parts.append(f"Removed methods: {', '.join(methods_removed)}")
    if methods_modified:
        parts.append(f"Modified methods: {', '.join(methods_modified)}")

    detail = f"Update {api_path}."
    if parts:
        detail += " " + ". ".join(parts) + "."
    return detail


# ---------------------------------------------------------------------------
# Main diff → SDK changes transformer
# ---------------------------------------------------------------------------

def build_sdk_changes(diff: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Transform a diff.yaml document into the SDK generator changes[] format.

    Mapping:
      paths.added        → change_type: new_endpoint  (with method/summary detail)
      paths.modified     → change_type: modify         (with methods changed)
      paths.removed      → change_type: modify          (deprecation notice)
      schemas.added      → change_type: new_endpoint   (with full field list + types)
      schemas.modified   → change_type: modify          (REMOVE/ADD fields with types)
      schemas.removed    → change_type: modify          (remove model instruction)
    """
    changes = []
    path_details = {
        d["path"]: d
        for d in (diff.get("paths", {}).get("detail", {}).get("added") or [])
        if isinstance(d, dict)
    }
    path_modified_details = {
        d["path"]: d
        for d in (diff.get("paths", {}).get("detail", {}).get("modified") or [])
        if isinstance(d, dict)
    }
    schema_added_details = {
        d["name"]: d
        for d in (diff.get("schemas", {}).get("detail", {}).get("added") or [])
        if isinstance(d, dict)
    }
    schema_modified_details = {
        d["name"]: d
        for d in (diff.get("schemas", {}).get("detail", {}).get("modified") or [])
        if isinstance(d, dict)
    }

    # ── Paths added ──────────────────────────────────────────────────────────
    for api_path in (diff.get("paths", {}).get("added") or []):
        detail_obj = path_details.get(api_path, {"path": api_path, "methods": {}})
        changes.append({
            "change_type": "new_endpoint",
            "title": f"Add {api_path}",
            "detail": _describe_new_path(detail_obj, spec),
            "affected_endpoints": [api_path],
        })

    # ── Paths modified ───────────────────────────────────────────────────────
    for api_path in (diff.get("paths", {}).get("modified") or []):
        detail_obj = path_modified_details.get(api_path, {"path": api_path})
        changes.append({
            "change_type": "modify",
            "title": f"Update {api_path}",
            "detail": _describe_modified_path(detail_obj),
            "affected_endpoints": [api_path],
        })

    # ── Paths removed ────────────────────────────────────────────────────────
    for api_path in (diff.get("paths", {}).get("removed") or []):
        changes.append({
            "change_type": "modify",
            "title": f"Remove {api_path}",
            "detail": f"Deprecate and remove {api_path} from the SDK. This endpoint no longer exists in the spec.",
            "affected_endpoints": [api_path],
        })

    # ── Schemas added ────────────────────────────────────────────────────────
    for schema_name in (diff.get("schemas", {}).get("added") or []):
        changes.append({
            "change_type": "new_endpoint",
            "title": f"Add {schema_name} schema",
            "detail": _describe_new_schema(schema_name, spec),
        })

    # ── Schemas modified ─────────────────────────────────────────────────────
    for schema_name in (diff.get("schemas", {}).get("modified") or []):
        detail_obj = schema_modified_details.get(schema_name, {})
        properties_added = detail_obj.get("properties_added") or []
        properties_removed = detail_obj.get("properties_removed") or []
        affected_endpoints = _find_endpoints_using_schema(schema_name, spec)

        changes.append({
            "change_type": "modify",
            "title": f"Update {schema_name} schema",
            "detail": _describe_modified_schema(
                schema_name, properties_added, properties_removed, spec, affected_endpoints,
            ),
            "affected_endpoints": affected_endpoints,
        })

    # ── Schemas removed ──────────────────────────────────────────────────────
    for schema_name in (diff.get("schemas", {}).get("removed") or []):
        changes.append({
            "change_type": "modify",
            "title": f"Remove {schema_name} schema",
            "detail": f"Remove the {schema_name} model from the SDK. This schema no longer exists in the spec.",
        })

    return changes


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_post(url: str, payload: dict[str, Any], dry_run: bool) -> bool:
    if dry_run:
        import json  # noqa: PLC0415
        print(f"  [dry-run] Would POST → {url}")
        print(f"  [dry-run] Payload preview:")
        print(json.dumps(payload, indent=2)[:1000])
        return True

    try:
        import requests  # noqa: PLC0415
    except ImportError:
        print("  ERROR: 'requests' not installed. Add it to requirements.txt.", file=sys.stderr)
        return False

    headers = {"Content-Type": "application/json"}
    if SDK_GENERATOR_TOKEN:
        headers["Authorization"] = f"Bearer {SDK_GENERATOR_TOKEN}"

    print(f"  POST {url}")
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.ok:
        print(f"  ✅ {resp.status_code}")
        return True

    print(f"  ❌ {resp.status_code} — {resp.text[:200]}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Per-product send
# ---------------------------------------------------------------------------

def _resolve_target_repo(sdk_cfg: dict[str, Any]) -> str:
    """
    Resolve target_repo from sdk config or env var SDK_REPO_{LANGUAGE_UPPER}.
    e.g. language=python → SDK_REPO_PYTHON=https://github.com/mercadopago/sdk-python
    """
    if sdk_cfg.get("target_repo"):
        return sdk_cfg["target_repo"]

    language = sdk_cfg.get("language", "")
    env_key = f"SDK_REPO_{language.upper()}"
    return os.environ.get(env_key, "")


def send_sdk_generation(
    product: str,
    sdk_configs: list[dict[str, Any]],
    by_product_dir: Path,
    dry_run: bool = False,
) -> bool:
    """
    Trigger SDK generation for all SDK targets configured for *product*.
    Returns True if all targets succeed (or if there are no targets).
    """
    diff_path = by_product_dir / product / "diff.yaml"
    spec_path = by_product_dir / product / "spec3.yaml"
    # Full spec has all schema definitions including newly added ones
    full_spec_path = by_product_dir.parent / "spec3.yaml"

    if not spec_path.exists():
        print(f"\n  [{product}] spec3.yaml not found — skipping")
        return True

    if not diff_path.exists():
        print(f"\n  [{product}] diff.yaml not found — no changes to send")
        return True

    diff = yaml.safe_load(diff_path.read_text()) or {}
    spec = yaml.safe_load(spec_path.read_text()) or {}
    # Use full spec for schema lookups (new schemas may not be in by-product yet)
    full_spec = yaml.safe_load(full_spec_path.read_text()) if full_spec_path.exists() else spec
    changes = build_sdk_changes(diff, full_spec)

    if not changes:
        print(f"\n  [{product}] No actionable changes for SDK generation — skipping")
        return True

    url = f"{SDK_GENERATOR_URL.rstrip('/')}{SDK_GENERATOR_ENDPOINT}"
    success = True

    for sdk_cfg in sdk_configs:
        language = sdk_cfg.get("language", "python")
        site_id = sdk_cfg.get("site_id", "MLB")
        target_repo = _resolve_target_repo(sdk_cfg)

        if not target_repo:
            print(
                f"\n  [{product}] WARNING: target_repo not set for {language}. "
                f"Set SDK_REPO_{language.upper()} env var.",
                file=sys.stderr,
            )

        print(f"\n  [{product}] → {language} / {site_id} — {len(changes)} change(s)")

        payload = {
            "spec_version": SPEC_VERSION,
            "language": language,
            "site_id": site_id,
            "target_repo": target_repo,
            "changes": changes,
        }

        ok = _http_post(url, payload, dry_run)
        if not ok:
            success = False

    return success


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_targets(
    fury_app_names: list[str],
    apps_config: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Map fury_app names → (product_slug, sdk_configs[]). Only apps with sdk[] entries."""
    lookup = {a["fury_app"]: a for a in apps_config}
    targets = []

    for name in fury_app_names:
        app = lookup.get(name)
        if not app:
            print(f"  Warning: fury_app '{name}' not found in apps.yaml — skipping")
            continue
        sdk_configs = app.get("sdk", [])
        if not sdk_configs:
            continue
        product = app.get("product", name)
        targets.append((product, sdk_configs))

    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger SDK generation for changed products")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apps", metavar="APP1,APP2,...", help="Comma-separated fury_app names")
    group.add_argument("--all", action="store_true", help="All apps with sdk config in apps.yaml")
    parser.add_argument("--openapi-path", default=str(ROOT), help="Path to the openapi repo root")
    parser.add_argument("--dry-run", action="store_true", help="Show payload without HTTP calls")
    args = parser.parse_args()

    openapi_root = Path(args.openapi_path).resolve()
    apps_cfg_path = openapi_root / "apps.yaml"
    by_product_dir = openapi_root / "by-product"

    with open(apps_cfg_path) as f:
        apps_config = yaml.safe_load(f).get("apps", [])

    fury_app_names = (
        [a["fury_app"] for a in apps_config]
        if args.all
        else [n.strip() for n in args.apps.split(",") if n.strip()]
    )

    targets = resolve_targets(fury_app_names, apps_config)

    if not targets:
        print("No products with SDK configuration found.")
        sys.exit(0)

    print(f"\n{'='*60}")
    print(f"Triggering SDK generation for {len(targets)} product(s)")
    print(f"Generator: {SDK_GENERATOR_URL}{SDK_GENERATOR_ENDPOINT}")
    if args.dry_run:
        print("[DRY RUN — no HTTP calls will be made]")
    print(f"{'='*60}")

    failures = 0
    for product, sdk_configs in targets:
        ok = send_sdk_generation(product, sdk_configs, by_product_dir, dry_run=args.dry_run)
        if not ok:
            failures += 1

    print(f"\n{'='*60}")
    print(f"Done. {len(targets) - failures}/{len(targets)} product(s) triggered successfully.")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
