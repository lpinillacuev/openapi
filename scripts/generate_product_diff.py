#!/usr/bin/env python3
"""
Generate a structured diff of what actually changed per product after a merge to main.

Compares spec3.yaml HEAD~1 vs HEAD and produces one file per product:
  by-product/{product}/diff.yaml

The diff file captures ONLY what changed in that product's scope — paths added,
removed or modified, and schemas added, removed or modified. This is the source
of truth for the API call: if nothing changed for a product, no file is produced
and no API call is made.

Usage:
    # Run after merge to main (HEAD~1 is the previous commit)
    python scripts/generate_product_diff.py

    # Show diff without writing files
    python scripts/generate_product_diff.py --dry-run

    # Compare two arbitrary commits
    python scripts/generate_product_diff.py --base <sha> --head <sha>

    # Limit to specific products
    python scripts/generate_product_diff.py --products payments,customers

Environment:
    Runs inside the openapi repo. No extra env vars needed.
    Called by trigger-devsite-sync.yml after every merge to main.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import subprocess
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
# Git helpers
# ---------------------------------------------------------------------------

def git_show_file(ref: str, path: str) -> str | None:
    """Return the content of *path* at git *ref*, or None if it doesn't exist."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def git_current_branch_spec() -> dict[str, Any]:
    """Load spec3.yaml from the current working tree."""
    with open(ROOT / "spec3.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Spec loading
# ---------------------------------------------------------------------------

def load_spec_at(ref: str) -> dict[str, Any] | None:
    content = git_show_file(ref, "spec3.yaml")
    if content is None:
        return None
    return yaml.safe_load(content)


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def _schema_summary(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a concise summary of a schema for the diff report."""
    summary: dict[str, Any] = {}
    if "type" in schema:
        summary["type"] = schema["type"]
    if "properties" in schema:
        summary["properties"] = sorted(schema["properties"].keys())
    if "required" in schema:
        summary["required"] = schema["required"]
    if "description" in schema:
        summary["description"] = schema["description"]
    return summary


def _operation_summary(op: dict[str, Any]) -> dict[str, Any]:
    """Return a concise summary of a path operation for the diff report."""
    summary: dict[str, Any] = {}
    if "summary" in op:
        summary["summary"] = op["summary"]
    if "description" in op:
        summary["description"] = op["description"][:120] + "..." if len(op.get("description", "")) > 120 else op.get("description", "")
    if "parameters" in op:
        summary["parameters"] = [p.get("name") for p in op["parameters"]]
    if "requestBody" in op:
        content = op["requestBody"].get("content", {})
        for media_type, body in content.items():
            if "schema" in body:
                ref = body["schema"].get("$ref", "")
                summary["requestBody"] = ref.rsplit("/", 1)[-1] if ref else "(inline)"
                break
    if "responses" in op:
        summary["responses"] = list(op["responses"].keys())
    return summary


def diff_schemas(
    old_schemas: dict[str, Any],
    new_schemas: dict[str, Any],
    product_paths: list[str],
    all_schemas_before: dict[str, Any],
    all_schemas_after: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """
    Compare old_schemas vs new_schemas for schemas referenced by product_paths.
    Returns {"added": [...], "removed": [...], "modified": [...]}.
    """
    # Collect schemas referenced by the product's paths (transitively)
    def referenced(paths_obj: dict[str, Any], all_s: dict[str, Any]) -> set[str]:
        refs: set[str] = set()
        queue = [paths_obj]
        while queue:
            obj = queue.pop()
            if isinstance(obj, dict):
                ref = obj.get("$ref", "")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    name = ref.rsplit("/", 1)[-1]
                    if name not in refs:
                        refs.add(name)
                        if name in all_s:
                            queue.append(all_s[name])
                else:
                    queue.extend(obj.values())
            elif isinstance(obj, list):
                queue.extend(obj)
        return refs

    added = []
    removed = []
    modified = []

    all_names = set(old_schemas) | set(new_schemas)
    for name in sorted(all_names):
        if name in new_schemas and name not in old_schemas:
            added.append({
                "name": name,
                "summary": _schema_summary(new_schemas[name]),
            })
        elif name in old_schemas and name not in new_schemas:
            removed.append({"name": name})
        elif new_schemas.get(name) != old_schemas.get(name):
            old_props = set((old_schemas[name].get("properties") or {}).keys())
            new_props = set((new_schemas[name].get("properties") or {}).keys())
            modified.append({
                "name": name,
                "properties_added": sorted(new_props - old_props),
                "properties_removed": sorted(old_props - new_props),
            })

    return {"added": added, "removed": removed, "modified": modified}


def diff_paths(
    old_paths: dict[str, Any],
    new_paths: dict[str, Any],
    allowed_prefixes: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """
    Compare old_paths vs new_paths for paths matching allowed_prefixes.
    Returns {"added": [...], "removed": [...], "modified": [...]}.
    """
    def in_scope(path: str) -> bool:
        return not allowed_prefixes or any(path.startswith(p) for p in allowed_prefixes)

    old_scoped = {p: v for p, v in old_paths.items() if in_scope(p)}
    new_scoped = {p: v for p, v in new_paths.items() if in_scope(p)}

    added = []
    removed = []
    modified = []

    all_paths = set(old_scoped) | set(new_scoped)
    for path in sorted(all_paths):
        if path in new_scoped and path not in old_scoped:
            methods = {
                method: _operation_summary(op)
                for method, op in new_scoped[path].items()
                if isinstance(op, dict)
            }
            added.append({"path": path, "methods": methods})

        elif path in old_scoped and path not in new_scoped:
            removed.append({"path": path})

        else:
            old_methods = old_scoped[path]
            new_methods = new_scoped[path]
            if old_methods == new_methods:
                continue

            methods_added = []
            methods_removed = []
            methods_modified = []

            for method in sorted(set(old_methods) | set(new_methods)):
                if method in new_methods and method not in old_methods:
                    methods_added.append({method: _operation_summary(new_methods[method])})
                elif method in old_methods and method not in new_methods:
                    methods_removed.append(method)
                elif new_methods.get(method) != old_methods.get(method):
                    methods_modified.append(method.upper())

            if methods_added or methods_removed or methods_modified:
                modified.append({
                    "path": path,
                    "methods_added": methods_added,
                    "methods_removed": methods_removed,
                    "methods_modified": methods_modified,
                })

    return {"added": added, "removed": removed, "modified": modified}


# ---------------------------------------------------------------------------
# Per-product diff
# ---------------------------------------------------------------------------

def compute_product_diff(
    app_config: dict[str, Any],
    spec_before: dict[str, Any],
    spec_after: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Compute what changed for one product between spec_before and spec_after.
    Returns None if nothing changed for this product.
    """
    product = app_config.get("product") or app_config["fury_app"]
    allowed_prefixes = app_config.get("paths", [])

    old_paths = spec_before.get("paths", {})
    new_paths = spec_after.get("paths", {})
    old_schemas = spec_before.get("components", {}).get("schemas", {})
    new_schemas = spec_after.get("components", {}).get("schemas", {})

    # Filter schemas to those referenced by this product's paths
    def scoped_schemas(paths_obj: dict[str, Any], all_schemas: dict[str, Any]) -> dict[str, Any]:
        scoped_paths = {
            p: v for p, v in paths_obj.items()
            if not allowed_prefixes or any(p.startswith(pref) for pref in allowed_prefixes)
        }
        refs: set[str] = set()
        queue = [scoped_paths]
        while queue:
            obj = queue.pop()
            if isinstance(obj, dict):
                ref = obj.get("$ref", "")
                if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                    name = ref.rsplit("/", 1)[-1]
                    if name not in refs:
                        refs.add(name)
                        if name in all_schemas:
                            queue.append(all_schemas[name])
                else:
                    queue.extend(obj.values())
            elif isinstance(obj, list):
                queue.extend(obj)
        return {k: v for k, v in all_schemas.items() if k in refs}

    product_schemas_before = scoped_schemas(old_paths, old_schemas)
    product_schemas_after = scoped_schemas(new_paths, new_schemas)

    paths_diff = diff_paths(old_paths, new_paths, allowed_prefixes)
    schemas_diff = diff_schemas(
        product_schemas_before,
        product_schemas_after,
        allowed_prefixes,
        old_schemas,
        new_schemas,
    )

    # If nothing changed for this product, return None
    has_path_changes = any(paths_diff[k] for k in ("added", "removed", "modified"))
    has_schema_changes = any(schemas_diff[k] for k in ("added", "removed", "modified"))

    if not has_path_changes and not has_schema_changes:
        return None

    total = (
        len(paths_diff["added"])
        + len(paths_diff["removed"])
        + len(paths_diff["modified"])
        + len(schemas_diff["added"])
        + len(schemas_diff["removed"])
        + len(schemas_diff["modified"])
    )

    return {
        "product": product,
        "fury_app": app_config["fury_app"],
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_changes": total,
        "paths": {
            "added":    [c["path"] if isinstance(c, dict) else c for c in paths_diff["added"]],
            "removed":  [c["path"] if isinstance(c, dict) else c for c in paths_diff["removed"]],
            "modified": [c["path"] if isinstance(c, dict) else c for c in paths_diff["modified"]],
            "detail":   paths_diff,
        },
        "schemas": {
            "added":    [c["name"] for c in schemas_diff["added"]],
            "removed":  [c["name"] for c in schemas_diff["removed"]],
            "modified": [c["name"] for c in schemas_diff["modified"]],
            "detail":   schemas_diff,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate per-product diff after merge to main"
    )
    parser.add_argument(
        "--base",
        default="HEAD~1",
        help="Git ref for the spec BEFORE the merge (default: HEAD~1)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Git ref for the spec AFTER the merge (default: HEAD = working tree)",
    )
    parser.add_argument(
        "--products",
        metavar="p1,p2,...",
        help="Comma-separated product slugs to diff (default: all in apps.yaml)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print diffs, don't write files")
    args = parser.parse_args()

    # Load specs
    spec_before = load_spec_at(args.base)
    if spec_before is None:
        print(f"Could not load spec3.yaml at {args.base} — is this a fresh repo?", file=sys.stderr)
        spec_before = {"paths": {}, "components": {"schemas": {}}}

    if args.head == "HEAD":
        spec_after = git_current_branch_spec()
    else:
        spec_after = load_spec_at(args.head)
        if spec_after is None:
            print(f"Could not load spec3.yaml at {args.head}", file=sys.stderr)
            sys.exit(1)

    # Load apps config
    with open(APPS_CONFIG_PATH) as f:
        apps_config = yaml.safe_load(f).get("apps", [])

    # Filter to requested products
    filter_products = set()
    if args.products:
        filter_products = {p.strip() for p in args.products.split(",") if p.strip()}
        apps_config = [
            a for a in apps_config
            if a.get("product", a["fury_app"]) in filter_products
        ]

    print(f"\n{'='*60}")
    print(f"Comparing: {args.base} → {args.head}")
    print(f"Products  : {len(apps_config)}")
    print(f"{'='*60}")

    changed_products: list[str] = []
    skipped_products: list[str] = []

    for app_config in apps_config:
        product = app_config.get("product") or app_config["fury_app"]
        diff = compute_product_diff(app_config, spec_before, spec_after)

        if diff is None:
            print(f"\n  [{product}] No changes — skipping")
            skipped_products.append(product)
            continue

        print(f"\n  [{product}] {diff['total_changes']} change(s):")
        if diff["paths"]["added"]:
            print(f"    + paths : {', '.join(diff['paths']['added'])}")
        if diff["paths"]["removed"]:
            print(f"    - paths : {', '.join(diff['paths']['removed'])}")
        if diff["paths"]["modified"]:
            print(f"    ~ paths : {', '.join(diff['paths']['modified'])}")
        if diff["schemas"]["added"]:
            print(f"    + schemas: {', '.join(diff['schemas']['added'])}")
        if diff["schemas"]["removed"]:
            print(f"    - schemas: {', '.join(diff['schemas']['removed'])}")
        if diff["schemas"]["modified"]:
            print(f"    ~ schemas: {', '.join(diff['schemas']['modified'])}")

        if dry_run := args.dry_run:
            print(f"    [dry-run] Would write: by-product/{product}/diff.yaml")
        else:
            out_path = BY_PRODUCT / product / "diff.yaml"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                yaml.dump(diff, f, allow_unicode=True, sort_keys=False, default_flow_style=False, width=120)
            print(f"    Written: {out_path.relative_to(ROOT)}")

        changed_products.append(product)

    print(f"\n{'='*60}")
    print(f"Changed : {len(changed_products)} product(s) → {', '.join(changed_products) or 'none'}")
    print(f"No change: {len(skipped_products)} product(s)")

    # Write changed products list so the workflow can consume it
    if not args.dry_run:
        changed_list_path = ROOT / "by-product" / ".changed-products"
        BY_PRODUCT.mkdir(parents=True, exist_ok=True)
        changed_list_path.write_text(",".join(changed_products))
        print(f"Changed products list written to: {changed_list_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
