#!/usr/bin/env python3
"""
Build a human-readable changes summary from per-product diff files.

Reads by-product/{product}/diff.yaml for each changed product and prints
a single-line summary of what changed (paths and schemas added/removed/modified).

Usage:
    CHANGED_PRODUCTS=orders,payments python scripts/build_changes_summary.py

Output (stdout):
    orders (5 change(s)); paths added: /v1/orders/{order_id}/confirm; schemas added: ConfirmOrder
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

BY_PRODUCT = Path(__file__).resolve().parent.parent / "by-product"


def build_summary(changed_products: str) -> str:
    products = [p.strip() for p in changed_products.split(",") if p.strip()]
    parts = []

    for product in products:
        diff_path = BY_PRODUCT / product / "diff.yaml"
        if not diff_path.exists():
            parts.append(f"{product}: no diff file found")
            continue

        diff = yaml.safe_load(diff_path.read_text()) or {}
        total = diff.get("total_changes", 0)
        lines = [f"{product} ({total} change(s))"]

        paths = diff.get("paths", {})
        if paths.get("added"):
            lines.append(f"paths added: {', '.join(paths['added'])}")
        if paths.get("removed"):
            lines.append(f"paths removed: {', '.join(paths['removed'])}")
        if paths.get("modified"):
            lines.append(f"paths modified: {', '.join(paths['modified'])}")

        schemas = diff.get("schemas", {})
        if schemas.get("added"):
            lines.append(f"schemas added: {', '.join(schemas['added'])}")
        if schemas.get("removed"):
            lines.append(f"schemas removed: {', '.join(schemas['removed'])}")
        if schemas.get("modified"):
            lines.append(f"schemas modified: {', '.join(schemas['modified'])}")

        parts.append("; ".join(lines))

    return " | ".join(parts)


if __name__ == "__main__":
    changed = os.environ.get("CHANGED_PRODUCTS", "")
    if not changed:
        print("No products provided via CHANGED_PRODUCTS", file=sys.stderr)
        sys.exit(1)

    print(build_summary(changed))
