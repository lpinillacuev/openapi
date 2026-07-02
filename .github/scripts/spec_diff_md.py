#!/usr/bin/env python3
"""
Genera un resumen en Markdown de los cambios en spec3.yaml para comentarios de PR.

Compara spec3.yaml (y schemas/*.yaml) entre la rama base y HEAD, y produce
un resumen estructurado con los cambios por endpoint y schema.

Uso:
    python3 .github/scripts/spec_diff_md.py --base main --output /tmp/spec-diff.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
MAX_TEXT = 500


# ── Git helpers ───────────────────────────────────────────────────────────────

def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    return r.stdout if r.returncode == 0 else None


def changed_files(base_ref: str) -> list[str]:
    """Archivos YAML/JSON relevantes que cambiaron vs la rama base."""
    r = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    relevant = {"spec3.yaml", "spec3.json"}
    return [
        p for p in r.stdout.splitlines()
        if p in relevant
        or p.startswith("schemas/")
        or p.startswith("by-product/")
    ]


# ── Helpers de texto ──────────────────────────────────────────────────────────

def trunc(s: str) -> str:
    s = str(s or "")
    return s[:MAX_TEXT] + "…" if len(s) > MAX_TEXT else s


def text_diff(old: str, new: str) -> str | None:
    old, new = str(old or "").strip(), str(new or "").strip()
    if old == new:
        return None
    return f"> **Antes:** {trunc(old)}\n>\n> **Después:** {trunc(new)}"


def jdump(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


# ── Diff de parámetros ────────────────────────────────────────────────────────

def diff_params(old_params: list, new_params: list) -> list[str]:
    old_by = {p["name"]: p for p in (old_params or [])}
    new_by = {p["name"]: p for p in (new_params or [])}
    lines = []

    for name in sorted(set(new_by) - set(old_by)):
        p = new_by[name]
        t = (p.get("schema") or {}).get("type", "?")
        lines.append(f"➕ Parámetro **`{name}`** agregado (`in: {p.get('in','?')}`, `type: {t}`)")

    for name in sorted(set(old_by) - set(new_by)):
        lines.append(f"➖ Parámetro **`{name}`** eliminado")

    for name in sorted(set(old_by) & set(new_by)):
        op, np = old_by[name], new_by[name]
        if jdump(op) == jdump(np):
            continue
        # description
        d = text_diff(op.get("description", ""), np.get("description", ""))
        if d:
            lines.append(f"**`{name}.description`**\n\n{d}")
        # type
        ot = (op.get("schema") or {}).get("type")
        nt = (np.get("schema") or {}).get("type")
        if str(ot) != str(nt):
            lines.append(f"**`{name}.type`**: `{ot}` → `{nt}`")
        # required
        if op.get("required") != np.get("required"):
            lines.append(f"**`{name}.required`**: `{op.get('required')}` → `{np.get('required')}`")

    return lines


# ── Diff de schemas (components) ──────────────────────────────────────────────

def diff_schemas(old_schemas: dict, new_schemas: dict) -> list[str]:
    lines = []

    added = sorted(set(new_schemas) - set(old_schemas))
    removed = sorted(set(old_schemas) - set(new_schemas))

    if added:
        lines.append(f"➕ Schemas nuevos: {', '.join(f'`{s}`' for s in added)}")
    if removed:
        lines.append(f"➖ Schemas eliminados: {', '.join(f'`{s}`' for s in removed)}")

    for name in sorted(set(old_schemas) & set(new_schemas)):
        os, ns = old_schemas[name], new_schemas[name]
        if jdump(os) == jdump(ns):
            continue
        old_props = set((os.get("properties") or {}).keys())
        new_props = set((ns.get("properties") or {}).keys())
        adds = sorted(new_props - old_props)
        rems = sorted(old_props - new_props)
        parts = []
        if adds:
            parts.append(f"➕ `{', '.join(adds)}`")
        if rems:
            parts.append(f"➖ `{', '.join(rems)}`")
        if not parts:
            parts.append("propiedades modificadas")
        lines.append(f"**Schema `{name}`**: {' · '.join(parts)}")

    return lines


# ── Diff de operación (un método de un path) ──────────────────────────────────

def diff_operation(old_op: dict, new_op: dict) -> list[tuple[str, str]]:
    """Devuelve lista de (campo, markdown) con los cambios."""
    changes: list[tuple[str, str]] = []

    # summary
    d = text_diff(old_op.get("summary", ""), new_op.get("summary", ""))
    if d:
        changes.append(("`summary`", d))

    # description
    d = text_diff(old_op.get("description", ""), new_op.get("description", ""))
    if d:
        changes.append(("`description`", d))

    # parameters
    param_lines = diff_params(old_op.get("parameters"), new_op.get("parameters"))
    for line in param_lines:
        changes.append(("`parameters`", line))

    # requestBody — comparar al nivel de propiedades del schema
    old_rb = old_op.get("requestBody") or {}
    new_rb = new_op.get("requestBody") or {}
    if jdump(old_rb) != jdump(new_rb):
        # Intentar extraer propiedades del schema del requestBody
        def rb_props(rb):
            for ctype in (rb.get("content") or {}).values():
                schema = ctype.get("schema") or {}
                if schema.get("properties"):
                    return set(schema["properties"].keys())
            return set()

        old_props = rb_props(old_rb)
        new_props = rb_props(new_rb)
        adds = sorted(new_props - old_props)
        rems = sorted(old_props - new_props)

        if adds or rems:
            parts = []
            if adds:
                parts.append(f"➕ `{', '.join(adds)}`")
            if rems:
                parts.append(f"➖ `{', '.join(rems)}`")
            changes.append(("`requestBody`", " · ".join(parts)))
        else:
            changes.append(("`requestBody`", "⚠️ Estructura modificada — ver diff del archivo"))

    # responses — solo marcar si cambió
    if jdump(old_op.get("responses")) != jdump(new_op.get("responses")):
        old_codes = set((old_op.get("responses") or {}).keys())
        new_codes = set((new_op.get("responses") or {}).keys())
        adds = sorted(new_codes - old_codes)
        rems = sorted(old_codes - new_codes)
        if adds or rems:
            parts = []
            if adds:
                parts.append(f"➕ códigos `{', '.join(adds)}`")
            if rems:
                parts.append(f"➖ códigos `{', '.join(rems)}`")
            changes.append(("`responses`", " · ".join(parts)))
        else:
            changes.append(("`responses`", "Descripciones de respuestas modificadas"))

    # tags
    if jdump(old_op.get("tags")) != jdump(new_op.get("tags")):
        changes.append(("`tags`", f"`{old_op.get('tags')}` → `{new_op.get('tags')}`"))

    return changes


# ── Generación del Markdown ───────────────────────────────────────────────────

def generate_markdown(base_ref: str) -> str:
    # Siempre comparar spec3.yaml (el archivo principal)
    old_raw = git_show(f"origin/{base_ref}", "spec3.yaml")
    new_raw = git_show("HEAD", "spec3.yaml")

    if not old_raw or not new_raw:
        return ""

    try:
        old_spec = yaml.safe_load(old_raw) or {}
        new_spec = yaml.safe_load(new_raw) or {}
    except yaml.YAMLError:
        return ""

    old_paths = old_spec.get("paths") or {}
    new_paths = new_spec.get("paths") or {}
    old_schemas = (old_spec.get("components") or {}).get("schemas") or {}
    new_schemas = (new_spec.get("components") or {}).get("schemas") or {}

    all_paths = sorted(set(list(old_paths.keys()) + list(new_paths.keys())))

    endpoint_sections: list[str] = []
    total_endpoints = 0

    for api_path in all_paths:
        op = old_paths.get(api_path, {})
        np_ = new_paths.get(api_path, {})

        if not op:
            endpoint_sections.append(
                f"<details>\n<summary>🟢 <strong>{api_path}</strong> — path nuevo</summary>\n\n"
                f"Path agregado al spec.\n\n</details>\n"
            )
            total_endpoints += 1
            continue
        if not np_:
            endpoint_sections.append(
                f"<details>\n<summary>🔴 <strong>{api_path}</strong> — path eliminado</summary>\n\n"
                f"Path eliminado del spec.\n\n</details>\n"
            )
            total_endpoints += 1
            continue

        all_methods = sorted((set(op.keys()) | set(np_.keys())) & HTTP_METHODS)
        for method in all_methods:
            oo = op.get(method) or {}
            no = np_.get(method) or {}
            if jdump(oo) == jdump(no):
                continue

            changes = diff_operation(oo, no)
            if not changes:
                continue

            total_endpoints += 1
            n = len(changes)
            label = f"{method.upper()} {api_path}"
            summary_line = f"🟡 <strong>{label}</strong> — {n} cambio{'s' if n != 1 else ''}"

            detail_lines = [f"<details>\n<summary>{summary_line}</summary>\n"]
            for field, diff_md in changes:
                detail_lines.append(f"\n**{field}**\n\n{diff_md}\n")
            detail_lines.append("\n</details>\n")
            endpoint_sections.append("\n".join(detail_lines))

    # Schemas
    schema_lines = diff_schemas(old_schemas, new_schemas)
    schema_section = ""
    if schema_lines:
        schema_section = (
            "<details>\n<summary>📦 <strong>components/schemas</strong> — "
            f"{len(schema_lines)} cambio{'s' if len(schema_lines) != 1 else ''}</summary>\n\n"
            + "\n\n".join(schema_lines)
            + "\n\n</details>\n"
        )

    if not endpoint_sections and not schema_section:
        return ""

    header = (
        "## 📋 Resumen de cambios en `spec3.yaml`\n\n"
        f"> 🔀 Endpoints afectados: **{total_endpoints}** &nbsp;·&nbsp; "
        f"Rama base: `{base_ref}`\n\n"
        "> Expandí cada sección para ver el detalle del cambio.\n\n"
        "---\n\n"
    )

    body = "\n".join(endpoint_sections)
    if schema_section:
        body += "\n" + schema_section

    return header + body


# ── Schema checkboxes para el PR body ────────────────────────────────────────

def compute_schema_changes(base_ref: str) -> list[dict]:
    """
    Devuelve lista de schemas que cambiaron vs la rama base.
    Cada item: { name, status: 'added'|'modified'|'removed', added_props, removed_props }
    """
    old_raw = git_show(f"origin/{base_ref}", "spec3.yaml")
    new_raw = git_show("HEAD", "spec3.yaml")
    if not old_raw or not new_raw:
        return []

    try:
        old_spec = yaml.safe_load(old_raw) or {}
        new_spec = yaml.safe_load(new_raw) or {}
    except yaml.YAMLError:
        return []

    old_schemas = (old_spec.get("components") or {}).get("schemas") or {}
    new_schemas = (new_spec.get("components") or {}).get("schemas") or {}
    result = []

    for name in sorted(set(list(old_schemas.keys()) + list(new_schemas.keys()))):
        if name not in old_schemas:
            result.append({"name": name, "status": "added", "added_props": [], "removed_props": []})
        elif name not in new_schemas:
            result.append({"name": name, "status": "removed", "added_props": [], "removed_props": []})
        elif jdump(old_schemas[name]) != jdump(new_schemas[name]):
            old_props = set((old_schemas[name].get("properties") or {}).keys())
            new_props = set((new_schemas[name].get("properties") or {}).keys())
            result.append({
                "name": name,
                "status": "modified",
                "added_props": sorted(new_props - old_props),
                "removed_props": sorted(old_props - new_props),
            })

    return result


def generate_schema_checkboxes(base_ref: str) -> str:
    """
    Genera el bloque PENDING_SCHEMAS_START/END para el PR body.
    Formato idéntico al de PENDING_PATHS: cada schema es una línea con checkbox.
    """
    changes = compute_schema_changes(base_ref)
    if not changes:
        return ""

    lines = [
        "\n\n---\n\n"
        "## 📦 Schemas modificados — decidí cuáles sincronizar\n\n"
        "**Desmarcá** los schemas que querés rechazar, "
        "luego hacé **Review changes → Approve**.\n\n"
        "<!-- PENDING_SCHEMAS_START -->"
    ]

    for s in changes:
        if s["status"] == "added":
            detail = "_nuevo_"
        elif s["status"] == "removed":
            detail = "_eliminado_"
        else:
            parts = []
            if s["added_props"]:
                parts.append(f"+{len(s['added_props'])} campo{'s' if len(s['added_props']) != 1 else ''}")
            if s["removed_props"]:
                parts.append(f"-{len(s['removed_props'])} campo{'s' if len(s['removed_props']) != 1 else ''}")
            detail = f"_modificado: {', '.join(parts)}_" if parts else "_modificado_"

        lines.append(f"- [x] `{s['name']}` — {detail}")

    lines.append("<!-- PENDING_SCHEMAS_END -->")
    lines.append("\n> ✅ Marcado = aceptado · ☐ Desmarcado = rechazado (se revierte en `spec3.yaml`)")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera resumen Markdown de cambios en spec3.yaml"
    )
    parser.add_argument("--base", default="main", help="Rama base (default: main)")
    parser.add_argument("--output", default="/tmp/spec-diff.md", help="Archivo de salida")
    parser.add_argument("--schema-checkboxes", default="/tmp/schema-checkboxes.md",
                        help="Archivo de salida para los checkboxes de schemas (PR body)")
    args = parser.parse_args()

    md = generate_markdown(args.base)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)

    if md:
        print(f"✅ Resumen escrito en: {args.output} ({len(md)} chars)")
        print("\nPreview:")
        print(md[:800] + "…" if len(md) > 800 else md)
    else:
        print("Sin cambios en spec3.yaml detectados.")

    # Generar checkboxes de schemas para el PR body
    schema_cb = generate_schema_checkboxes(args.base)
    with open(args.schema_checkboxes, "w", encoding="utf-8") as f:
        f.write(schema_cb)
    if schema_cb:
        print(f"✅ Schema checkboxes escritos en: {args.schema_checkboxes}")


if __name__ == "__main__":
    main()
