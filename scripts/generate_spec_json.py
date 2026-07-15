#!/usr/bin/env python3
"""
Generate spec3.json (JSON twin of spec3.yaml).

Handles YAML types that are not natively JSON-serializable:
  - datetime / date objects  → ISO 8601 string
  - any other non-serializable type → str()

Usage:
    python scripts/generate_spec_json.py
    python scripts/generate_spec_json.py path/to/spec3.yaml path/to/spec3.json
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import yaml


class _SafeEncoder(json.JSONEncoder):
    def default(self, obj: object) -> object:
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return str(obj)


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spec3.yaml")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".json")

    try:
        spec = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        print(f"❌ File not found: {src}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ Failed to parse {src}: {e}", file=sys.stderr)
        sys.exit(1)

    dst.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False, cls=_SafeEncoder),
        encoding="utf-8",
    )
    print(f"✅ {dst} generated ({dst.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
