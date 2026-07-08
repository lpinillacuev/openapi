#!/usr/bin/env python3
"""
Build spec3.reference.json — the DevSite api-json format — from a by-product OpenAPI spec.

Follows the contract documented in the API Layout Guide (Grid).
Applies the mechanical transformation (Layer A) and reports validation
results against rules R1–R11 (Layer C).

Translations (pt/es) are left as "TODO" — Layer B (GenAI Gateway) fills them.

Spec family:
  spec3.yaml              ← global OpenAPI 3.1 (all products)
  spec3.sdk.yaml          ← SDK variant (x-mp-sdk-coverage per operation)
  by-product/{p}/spec3.reference.json  ← DevSite api-json per product  ← THIS FILE

Usage:
    # Build reference for one product
    python scripts/build_reference.py --product payments

    # Build for all products in apps.yaml
    python scripts/build_reference.py --all

    # Validate only — no write
    python scripts/build_reference.py --all --validate-only

    # Dry run — print output, no file write
    python scripts/build_reference.py --product payments --dry-run
"""

from __future__ import annotations

import argparse
import copy
import json
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

VALID_SITES = {"mla", "mlb", "mlm", "mlc", "mco", "mpe", "mlu"}

# ---------------------------------------------------------------------------
# Layer A — Mechanical transformation
# ---------------------------------------------------------------------------

def _to_multilingual(value: Any, fallback: str = "") -> dict[str, str]:
    """Coerce any value to {en, pt, es}. Leaves pt/es as TODO for Layer B."""
    if isinstance(value, dict) and "en" in value:
        result = dict(value)
        result.setdefault("pt", "TODO")
        result.setdefault("es", "TODO")
        return result
    text = str(value).strip() if value else fallback
    return {"en": text, "pt": "TODO", "es": "TODO"}


def _convert_enum(enum_value: Any) -> list[dict[str, Any]]:
    """Convert OpenAPI enum (list of strings) to DevSite enum (list of objects)."""
    if not isinstance(enum_value, list):
        return enum_value
    result = []
    for item in enum_value:
        if isinstance(item, dict) and "title" in item:
            # Already in DevSite format — ensure description is multilingual
            obj = dict(item)
            if "description" in obj:
                obj["description"] = _to_multilingual(obj["description"])
            else:
                obj["description"] = {"en": "", "pt": "TODO", "es": "TODO"}
            result.append(obj)
        elif isinstance(item, str):
            # Layer A: use title as en description placeholder — Layer B (AI) will enrich
            # Empty string values (e.g. "no separator") get a generic placeholder
            en_desc = item if item else "(empty)"
            result.append({
                "title": item,
                "description": {"en": en_desc, "pt": "TODO", "es": "TODO"},
            })
        else:
            result.append(item)
    return result


def _promote_required(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Convert required: [field1, field2] at the object level
    to required: true on each listed property.
    """
    schema = dict(schema)
    required_list = schema.pop("required", None)
    if isinstance(required_list, list) and "properties" in schema:
        props = schema["properties"]
        for field in required_list:
            if field in props and isinstance(props[field], dict):
                props[field] = dict(props[field])
                props[field]["required"] = True
    return schema


def _convert_sites(obj: dict[str, Any]) -> dict[str, Any]:
    """Convert x-mp-sites: [MLA, MLB] → x-site-id: ["mla", "mlb"]."""
    if "x-mp-sites" in obj:
        sites = obj.pop("x-mp-sites")
        if isinstance(sites, list):
            obj["x-site-id"] = [s.lower() for s in sites]
    return obj


def _walk_schema(schema: Any) -> Any:
    """Recursively apply all field-level transformations to a schema object."""
    if not isinstance(schema, dict):
        return schema
    if isinstance(schema, list):
        return [_walk_schema(i) for i in schema]

    schema = _convert_sites(dict(schema))

    # description → multilingual
    if "description" in schema and not isinstance(schema["description"], dict):
        schema["description"] = _to_multilingual(schema["description"])

    # enum → DevSite objects
    if "enum" in schema:
        schema["enum"] = _convert_enum(schema["enum"])

    # required array → boolean per property
    schema = _promote_required(schema)

    # Recurse into properties
    if "properties" in schema and isinstance(schema["properties"], dict):
        schema["properties"] = {
            k: _walk_schema(v) for k, v in schema["properties"].items()
        }

    # Recurse into items (array type)
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = _walk_schema(schema["items"])

    # Recurse into additionalProperties
    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        schema["additionalProperties"] = _walk_schema(schema["additionalProperties"])

    # allOf / anyOf / oneOf
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema and isinstance(schema[key], list):
            schema[key] = [_walk_schema(i) for i in schema[key]]

    return schema


def _convert_parameters(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a parameters list to DevSite format."""
    result = []
    for p in params:
        p = dict(p)
        if "description" in p:
            p["description"] = _to_multilingual(p["description"])
        if "schema" in p and isinstance(p["schema"], dict):
            p["schema"] = _walk_schema(p["schema"])
        result.append(p)
    return result


def _convert_request_body(rb: dict[str, Any]) -> dict[str, Any]:
    """Convert requestBody to DevSite format."""
    rb = copy.deepcopy(rb)
    content = rb.get("content", {})
    for media_type, media in content.items():
        if "schema" in media:
            media["schema"] = _walk_schema(media["schema"])
    return rb


def _convert_responses(responses: dict[str, Any]) -> dict[str, Any]:
    """
    Convert responses to DevSite format.
    4xx/5xx responses get errorKey structure if not already present.
    """
    result = {}
    for code, resp in responses.items():
        resp = copy.deepcopy(resp)

        # description → multilingual
        if "description" in resp:
            resp["description"] = _to_multilingual(resp["description"])

        # Process content schemas
        for media_type, media in resp.get("content", {}).items():
            if "schema" in media:
                media["schema"] = _walk_schema(media["schema"])

        # Promote errorKey structure for 4xx/5xx if not already there
        str_code = str(code)
        if str_code.startswith(("4", "5")):
            content = resp.setdefault("content", {})
            app_json = content.setdefault("application/json", {})
            schema = app_json.setdefault("schema", {"type": "object", "properties": {}})
            props = schema.setdefault("properties", {})
            if "errorKey" not in props:
                props["errorKey"] = {
                    "type": "string",
                    "enum": [
                        {
                            "title": "TODO_error_code",
                            "description": {
                                "en": "TODO: describe this error",
                                "pt": "TODO",
                                "es": "TODO",
                            },
                        }
                    ],
                }

        result[str_code] = resp

    return result


def _convert_operation(op: dict[str, Any]) -> dict[str, Any]:
    """Convert a single HTTP operation to DevSite format."""
    op = copy.deepcopy(op)

    # summary → title (multilingual)
    summary = op.pop("summary", op.get("operationId", ""))
    op["title"] = _to_multilingual(summary)

    # description → multilingual
    if "description" in op:
        op["description"] = _to_multilingual(op["description"])
    else:
        op["description"] = _to_multilingual(summary)

    # Remove OpenAPI-only fields
    for field in ("operationId", "security", "externalDocs"):
        op.pop(field, None)

    # parameters
    if "parameters" in op:
        op["parameters"] = _convert_parameters(op["parameters"])

    # requestBody
    if "requestBody" in op:
        op["requestBody"] = _convert_request_body(op["requestBody"])

    # responses
    if "responses" in op:
        op["responses"] = _convert_responses(op["responses"])

    return op


def transform(openapi_spec: dict[str, Any]) -> dict[str, Any]:
    """
    Apply Layer A mechanical transformation:
    OpenAPI 3.1 → DevSite api-json format.

    Output structure:
        {
          "url": "https://api.mercadopago.com",
          "paths": { ... },
          "components": { "schemas": { ... } }   # optional
        }
    """
    result: dict[str, Any] = {
        "url": "https://api.mercadopago.com",
    }

    # Paths
    paths: dict[str, Any] = {}
    for path, methods in openapi_spec.get("paths", {}).items():
        path_obj: dict[str, Any] = {}
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            path_obj[method.lower()] = _convert_operation(operation)
        if path_obj:
            paths[path] = path_obj
    result["paths"] = paths

    # Components / schemas
    raw_schemas = openapi_spec.get("components", {}).get("schemas", {})
    if raw_schemas:
        result["components"] = {
            "schemas": {
                name: _walk_schema(copy.deepcopy(schema))
                for name, schema in raw_schemas.items()
            }
        }

    return result


# ---------------------------------------------------------------------------
# Layer C — Validator (R1–R11)
# ---------------------------------------------------------------------------

class ValidationError:
    def __init__(self, rule: str, severity: str, path: str, message: str):
        self.rule = rule
        self.severity = severity  # "error" | "warning"
        self.path = path
        self.message = message

    def __str__(self) -> str:
        icon = "❌" if self.severity == "error" else "⚠️"
        return f"  {icon} [{self.rule}] {self.path}: {self.message}"


def _check_multilingual(obj: Any, path: str) -> list[ValidationError]:
    """R5: description / title must be {en, pt, es} objects."""
    errors = []
    if not isinstance(obj, dict):
        errors.append(ValidationError("R5", "error", path, "Expected multilingual object {en, pt, es}"))
        return errors
    for lang in ("en", "pt", "es"):
        if lang not in obj or not obj[lang]:
            errors.append(ValidationError("R5", "error", path, f"Missing or empty '{lang}' translation"))
    if obj.get("en") and obj.get("pt") == obj.get("en") and obj.get("es") == obj.get("en"):
        errors.append(ValidationError("R6", "warning", path, "pt/es are identical to en — translations missing"))
    return errors


def _validate_schema(schema: Any, path: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not isinstance(schema, dict):
        return errors

    # R10: required must be boolean per field, not array on object
    if isinstance(schema.get("required"), list):
        errors.append(ValidationError("R10", "error", path + ".required",
                                      "required must be boolean per field, not an array"))

    # R11: enum items must be {title, description{en,pt,es}}
    if "enum" in schema:
        for i, item in enumerate(schema["enum"]):
            ep = f"{path}.enum[{i}]"
            if not isinstance(item, dict):
                errors.append(ValidationError("R11", "error", ep, "enum item must be object {title, description}"))
            else:
                if "title" not in item:
                    errors.append(ValidationError("R11", "error", ep, "enum item missing 'title'"))
                if "description" not in item:
                    errors.append(ValidationError("R11", "error", ep, "enum item missing 'description'"))
                else:
                    errors += _check_multilingual(item["description"], ep + ".description")

    # R7: x-site-id must be array of valid sites
    if "x-site-id" in schema:
        for site in schema.get("x-site-id", []):
            if site not in VALID_SITES:
                errors.append(ValidationError("R7", "error", path + ".x-site-id",
                                              f"Invalid site '{site}'. Valid: {sorted(VALID_SITES)}"))

    # Recurse
    for prop_name, prop_schema in schema.get("properties", {}).items():
        errors += _validate_schema(prop_schema, f"{path}.properties.{prop_name}")
    if "items" in schema:
        errors += _validate_schema(schema["items"], f"{path}.items")

    return errors


def validate(doc: dict[str, Any]) -> list[ValidationError]:
    """Run R1–R11 validation rules against a DevSite api-json document."""
    errors: list[ValidationError] = []

    # R1: No undefined values (can't happen in Python dicts, but check for None in strings)
    # R2: Valid structure (top-level keys)
    # R3: Top level only url, paths, components
    allowed_top = {"url", "paths", "components"}
    extra = set(doc.keys()) - allowed_top
    if extra:
        errors.append(ValidationError("R3", "error", "$",
                                      f"Extra top-level keys not allowed: {extra}"))

    if "url" not in doc:
        errors.append(ValidationError("R3", "error", "$.url", "Missing required 'url' field"))

    # R4: $ref only internal
    def check_refs(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            ref = obj.get("$ref", "")
            if ref and not ref.startswith("#/components/"):
                errors.append(ValidationError("R4", "error", path + ".$ref",
                                              f"External $ref not supported: {ref}"))
            for k, v in obj.items():
                check_refs(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                check_refs(item, f"{path}[{i}]")

    check_refs(doc, "$")

    # Per-path / per-operation checks
    for path, methods in doc.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            base = f"$.paths['{path}'].{method}"

            # R5: title and description must be multilingual
            if "title" not in op:
                errors.append(ValidationError("R5", "error", base + ".title", "Missing 'title'"))
            else:
                errors += _check_multilingual(op["title"], base + ".title")

            if "description" not in op:
                errors.append(ValidationError("R5", "error", base + ".description", "Missing 'description'"))
            else:
                errors += _check_multilingual(op["description"], base + ".description")

            # R5: parameter descriptions
            for i, param in enumerate(op.get("parameters", [])):
                pp = f"{base}.parameters[{i}]"
                if "description" in param:
                    errors += _check_multilingual(param["description"], pp + ".description")

            # R9: 4xx/5xx must use errorKey + enum
            for code, resp in op.get("responses", {}).items():
                rp = f"{base}.responses.{code}"
                if str(code).startswith(("4", "5")):
                    props = (resp.get("content", {})
                                 .get("application/json", {})
                                 .get("schema", {})
                                 .get("properties", {}))
                    if "errorKey" not in props:
                        errors.append(ValidationError("R9", "warning", rp,
                                                       "4xx/5xx response should use errorKey + enum pattern"))

                # R5: response description multilingual
                if "description" in resp:
                    errors += _check_multilingual(resp["description"], rp + ".description")

            # R8: country-specific content should use mustache (warning only)
            # (Heuristic: if description contains country-specific currency/id patterns)

    # Component schema checks
    for name, schema in doc.get("components", {}).get("schemas", {}).items():
        errors += _validate_schema(schema, f"$.components.schemas.{name}")

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_product(product: str, dry_run: bool = False, validate_only: bool = False) -> bool:
    """Build and optionally write spec3.reference.json for one product. Returns True if valid."""
    spec_path = BY_PRODUCT / product / "spec3.yaml"
    out_path  = BY_PRODUCT / product / "spec3.reference.json"

    if not spec_path.exists():
        print(f"  [{product}] spec3.yaml not found — run bundle.py --products-only first")
        return False

    with open(spec_path) as f:
        openapi_spec = yaml.safe_load(f)

    reference_doc = transform(openapi_spec)
    validation_errors = validate(reference_doc)

    blocking = [e for e in validation_errors if e.severity == "error"]
    warnings  = [e for e in validation_errors if e.severity == "warning"]

    paths_count = len(reference_doc.get("paths", {}))
    ops_count   = sum(
        len([m for m in methods if isinstance(methods.get(m), dict)])
        for methods in reference_doc.get("paths", {}).values()
        if isinstance(methods, dict)
    )

    print(f"\n  [{product}]")
    print(f"    Paths     : {paths_count}")
    print(f"    Operations: {ops_count}")
    print(f"    Errors    : {len(blocking)}")
    print(f"    Warnings  : {len(warnings)}")

    if validation_errors:
        # Show first 10 issues
        for err in (blocking + warnings)[:10]:
            print(err)
        if len(validation_errors) > 10:
            print(f"    ... {len(validation_errors) - 10} more issue(s)")

    if blocking:
        print(f"    ❌ FAILED R1–R11 validation — spec3.reference.json NOT written")
        return False

    if validate_only:
        print(f"    ✅ Valid (validate-only mode — not written)")
        return True

    if dry_run:
        print(f"    [dry-run] Would write: {out_path.relative_to(ROOT)}")
        return True

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(reference_doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"    ✅ Written: {out_path.relative_to(ROOT)}")
    return True


def build_global(dry_run: bool = False, validate_only: bool = False) -> bool:
    """
    Build the global spec3.reference.json from the root spec3.yaml.

    Output: {ROOT}/spec3.reference.json

    This is the global DevSite api-json — all products in one file,
    following the same spec family pattern as spec3.yaml and spec3.sdk.yaml.
    """
    spec_path = ROOT / "spec3.yaml"
    out_path  = ROOT / "spec3.reference.json"

    with open(spec_path) as f:
        openapi_spec = yaml.safe_load(f)

    reference_doc = transform(openapi_spec)
    validation_errors = validate(reference_doc)

    blocking = [e for e in validation_errors if e.severity == "error"]
    warnings  = [e for e in validation_errors if e.severity == "warning"]

    paths_count = len(reference_doc.get("paths", {}))
    ops_count   = sum(
        len([m for m in methods if isinstance(methods.get(m), dict)])
        for methods in reference_doc.get("paths", {}).values()
        if isinstance(methods, dict)
    )

    print(f"\n  [global]  spec3.yaml → spec3.reference.json")
    print(f"    Paths     : {paths_count}")
    print(f"    Operations: {ops_count}")
    print(f"    Errors    : {len(blocking)}")
    print(f"    Warnings  : {len(warnings)}")

    if validation_errors:
        for err in (blocking + warnings)[:10]:
            print(err)
        if len(validation_errors) > 10:
            print(f"    ... {len(validation_errors) - 10} more issue(s)")

    if blocking:
        print(f"    ❌ FAILED R1–R11 — spec3.reference.json NOT written")
        return False

    if validate_only:
        print(f"    ✅ Valid (validate-only mode — not written)")
        return True

    yaml_path = ROOT / "spec3.reference.yaml"

    if dry_run:
        print(f"    [dry-run] Would write: spec3.reference.json + spec3.reference.yaml")
        return True

    with open(out_path, "w") as f:
        json.dump(reference_doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"    ✅ Written: spec3.reference.json")

    with open(yaml_path, "w") as f:
        yaml.dump(reference_doc, f, allow_unicode=True, sort_keys=False,
                  default_flow_style=False, width=120)
    print(f"    ✅ Written: spec3.reference.yaml")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build spec3.reference.json (DevSite api-json) from OpenAPI specs"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--global", dest="build_global", action="store_true",
                       help="Build root spec3.reference.json from spec3.yaml (all products)")
    group.add_argument("--product", metavar="SLUG", help="Build by-product/{slug}/spec3.reference.json")
    group.add_argument("--all", action="store_true",
                       help="Build global spec3.reference.json + all per-product files")
    parser.add_argument("--validate-only", action="store_true", help="Validate without writing")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing")
    args = parser.parse_args()

    with open(APPS_CONFIG_PATH) as f:
        apps_config = yaml.safe_load(f).get("apps", [])

    print(f"\n{'='*60}")

    # Global build
    if args.build_global or args.all:
        print("Building global spec3.reference.json")
        print(f"{'='*60}")
        ok = build_global(dry_run=args.dry_run, validate_only=args.validate_only)
        if not ok:
            sys.exit(1)
        if not args.all:
            return

    # Per-product builds
    if args.product:
        products = [args.product]
    elif args.all:
        products = [a.get("product", a["fury_app"]) for a in apps_config]
    else:
        products = []

    if products:
        print(f"\nBuilding per-product spec3.reference.json for {len(products)} product(s)")
        print(f"{'='*60}")

    passed = ok = 0
    for product in products:
        success = build_product(product, dry_run=args.dry_run, validate_only=args.validate_only)
        ok += 1 if success else 0
        passed += 1

    if passed:
        print(f"\n{'='*60}")
        print(f"Result: {ok}/{passed} product(s) passed validation")
        if ok < passed:
            sys.exit(1)


if __name__ == "__main__":
    main()
