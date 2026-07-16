#!/usr/bin/env python3
"""
Send by-product OpenAPI specs to the external product API.

Only called for products where generate_product_diff.py detected real changes
after the merge to main. Sends two files per product:

  by-product/{product}/spec3.yaml  — full OpenAPI 3.1 spec for the product
  by-product/{product}/diff.yaml   — structured changelog of what changed in this merge

Usage:
    # Send for specific apps (comma-separated fury_app names from apps.yaml)
    python scripts/push_to_api.py --apps payments,customers

    # Send for all apps in apps.yaml
    python scripts/push_to_api.py --all

    # Dry run — show what would be sent without making HTTP calls
    python scripts/push_to_api.py --all --dry-run

Environment variables (set as GitHub secrets):
    PRODUCT_SPEC_API_ENDPOINT  Base URL of the product spec API
                               e.g. https://api.example.com/specs
                               TODO: replace with real endpoint when available

    PRODUCT_SPEC_API_TOKEN     Bearer token for API authentication
                               TODO: replace with real token secret when available
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

API_ENDPOINT = os.environ.get("PRODUCT_SPEC_API_ENDPOINT", "")
API_TOKEN = os.environ.get("PRODUCT_SPEC_API_TOKEN", "")


# ---------------------------------------------------------------------------
# Payload builder — combines diff + spec into one file
# ---------------------------------------------------------------------------

def build_payload(product: str, by_product_dir: Path) -> tuple[str, dict[str, Any]] | None:
    """
    Read diff.yaml and spec3.yaml for *product* and combine them into one
    YAML document:

        product:      payments
        generated_at: ...
        changes:      { ... diff content ... }
        spec:         { ... full OpenAPI 3.1 spec ... }

    Returns (yaml_string, data_dict) or None if spec3.yaml is missing.
    """
    spec_path = by_product_dir / product / "spec3.yaml"
    diff_path = by_product_dir / product / "diff.yaml"

    if not spec_path.exists():
        return None

    spec = yaml.safe_load(spec_path.read_text())
    diff = yaml.safe_load(diff_path.read_text()) if diff_path.exists() else {}

    payload: dict[str, Any] = {
        "product":      product,
        "generated_at": diff.get("generated_at", ""),
        "total_changes": diff.get("total_changes", 0),
        "changes": {
            "paths":   diff.get("paths", {}),
            "schemas": diff.get("schemas", {}),
        },
        "spec": spec,
    }

    payload_yaml = yaml.dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )
    return payload_yaml, payload


# ---------------------------------------------------------------------------
# API send
# ---------------------------------------------------------------------------

def _http_post(url: str, payload: bytes, content_type: str) -> bool:
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        print("  ERROR: 'requests' not installed. Add it to requirements.txt.", file=sys.stderr)
        return False

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": content_type,
    }
    print(f"  POST {url}")
    resp = requests.post(url, data=payload, headers=headers, timeout=60)
    if resp.ok:
        print(f"  ✅ {resp.status_code}")
        return True
    print(f"  ❌ {resp.status_code} — {resp.text[:200]}", file=sys.stderr)
    return False


def send_spec(product: str, by_product_dir: Path, dry_run: bool = False) -> bool:
    """
    Build and POST the combined payload for *product* to the API.

    Sends one file:
      POST {endpoint}/{product}
      Content-Type: application/yaml

    Body structure:
      product:      <slug>
      generated_at: <timestamp>
      total_changes: <n>
      changes:
        paths:   { added, removed, modified, detail }
        schemas: { added, removed, modified, detail }
      spec:
        openapi: 3.1.0
        paths:   { ... }
        components: { ... }

    TODO: adjust URL and HTTP method once you have the API contract.
    """
    result = build_payload(product, by_product_dir)
    if result is None:
        print(f"\n  [{product}] spec3.yaml not found — skipping")
        return True

    payload_yaml, payload_data = result
    spec_lines = len(yaml.dump(payload_data.get("spec", {})).splitlines())

    print(f"\n  Product      : {product}")
    print(f"  Total changes: {payload_data['total_changes']}")
    print(f"  Spec paths   : {len(payload_data['spec'].get('paths', {}))}")
    print(f"  Payload size : {len(payload_yaml.splitlines())} lines / {len(payload_yaml.encode())} bytes")

    # Write the combined payload next to the source files so it can be inspected
    out_path = by_product_dir / product / "payload.yaml"
    if not dry_run:
        out_path.write_text(payload_yaml)
        print(f"  Payload file : {out_path.relative_to(by_product_dir.parent)}")

    if dry_run:
        endpoint = API_ENDPOINT or "<PRODUCT_SPEC_API_ENDPOINT not set>"
        print(f"  [dry-run] Would POST → {endpoint}/{product}")
        print(f"  [dry-run] Payload written to: by-product/{product}/payload.yaml" if not dry_run else "")
        return True

    if not API_ENDPOINT:
        print(
            "  [TODO] PRODUCT_SPEC_API_ENDPOINT secret is not set.\n"
            f"         Payload ready at: by-product/{product}/payload.yaml"
        )
        return True  # non-fatal until endpoint is configured

    if not API_TOKEN:
        print("  ERROR: PRODUCT_SPEC_API_TOKEN secret is not set.", file=sys.stderr)
        return False

    url = f"{API_ENDPOINT.rstrip('/')}/{product}"
    return _http_post(url, payload_yaml.encode(), "application/yaml")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_products(fury_app_names: list[str], apps_config: list[dict[str, Any]]) -> list[str]:
    """Map fury_app names → product slugs."""
    lookup = {a["fury_app"]: a.get("product", a["fury_app"]) for a in apps_config}
    products = []
    for name in fury_app_names:
        product = lookup.get(name)
        if product:
            products.append(product)
        else:
            print(f"  Warning: fury_app '{name}' not found in apps.yaml — skipping")
    return products


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send by-product specs to the external product API"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--apps",
        metavar="APP1,APP2,...",
        help="Comma-separated fury_app names to send (from apps.yaml)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Send specs for all apps in apps.yaml",
    )
    parser.add_argument(
        "--openapi-path",
        default=str(ROOT),
        help="Path to the openapi repo root (default: parent of this script)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without HTTP calls")
    args = parser.parse_args()

    # Allow --openapi-path override (used by GitHub Actions)
    openapi_root = Path(args.openapi_path).resolve()
    apps_cfg = openapi_root / "apps.yaml"
    by_product = openapi_root / "by-product"

    with open(apps_cfg) as f:
        apps_config = yaml.safe_load(f).get("apps", [])

    if args.all:
        fury_app_names = [a["fury_app"] for a in apps_config]
    else:
        fury_app_names = [n.strip() for n in args.apps.split(",") if n.strip()]

    products = resolve_products(fury_app_names, apps_config)

    if not products:
        print("No products to send.")
        sys.exit(0)

    print(f"\n{'='*60}")
    print(f"Sending {len(products)} by-product spec(s) to API")
    print(f"Endpoint: {API_ENDPOINT or '[PRODUCT_SPEC_API_ENDPOINT not set — TODO]'}")
    print(f"{'='*60}")

    failures = 0
    for product in products:
        ok = send_spec(product, by_product, dry_run=args.dry_run)
        if not ok:
            failures += 1

    print(f"\n{'='*60}")
    print(f"Done. {len(products) - failures}/{len(products)} product(s) sent successfully.")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
