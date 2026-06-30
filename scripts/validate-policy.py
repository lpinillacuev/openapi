#!/usr/bin/env python3
"""
Validates that no paths are in pending[] state in apps.yaml.
CI blocks merge while any app has pending path decisions.

Usage:
    python scripts/validate-policy.py
    python scripts/validate-policy.py --apps-file path/to/apps.yaml
"""

import sys
import argparse
import yaml


def normalize_path(api_path):
    """Normalize path variables: /v1/payments/{id} -> /v1/payments/{}"""
    result = []
    in_brace = False
    for char in api_path:
        if char == '{':
            in_brace = True
            result.append('{')
        elif char == '}':
            in_brace = False
            result.append('}')
        elif not in_brace:
            result.append(char)
    return ''.join(result)


def validate_policy_structure(app):
    """Validate that pathPolicy entries have required fields."""
    errors = []
    policy = app.get('pathPolicy', {})
    fury_app = app.get('fury_app', 'unknown')

    for list_name in ('whitelist', 'blacklist', 'pending'):
        entries = policy.get(list_name, [])
        if not isinstance(entries, list):
            errors.append(f"[{fury_app}] pathPolicy.{list_name} must be a list")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                errors.append(f"[{fury_app}] pathPolicy.{list_name}[{i}] must be an object")
                continue
            if 'path' not in entry:
                errors.append(f"[{fury_app}] pathPolicy.{list_name}[{i}] is missing required field 'path'")

    return errors


def main():
    parser = argparse.ArgumentParser(description='Validate apps.yaml path policy')
    parser.add_argument('--apps-file', default='apps.yaml', help='Path to apps.yaml')
    args = parser.parse_args()

    try:
        with open(args.apps_file, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"❌ File not found: {args.apps_file}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"❌ Invalid YAML in {args.apps_file}: {e}")
        sys.exit(1)

    apps = config.get('apps', [])
    pending_paths = []
    structure_errors = []

    for app in apps:
        fury_app = app.get('fury_app', 'unknown')

        # Validate structure
        errors = validate_policy_structure(app)
        structure_errors.extend(errors)

        # Collect pending entries
        pending = app.get('pathPolicy', {}).get('pending', [])
        for entry in pending:
            if isinstance(entry, dict) and 'path' in entry:
                method = entry.get('method', '*')
                detected = entry.get('detected_at', 'unknown date')
                pending_paths.append({
                    'app': fury_app,
                    'path': entry['path'],
                    'method': method,
                    'detected_at': detected,
                })

    if structure_errors:
        print("❌ Structure errors in apps.yaml:\n")
        for err in structure_errors:
            print(f"  {err}")
        sys.exit(1)

    if pending_paths:
        print("❌ Paths requiring a decision before this PR can be merged:\n")
        print(f"  {'App':<35} {'Method':<8} {'Path':<50} {'Detected'}")
        print(f"  {'-'*35} {'-'*8} {'-'*50} {'-'*12}")
        for entry in pending_paths:
            print(f"  {entry['app']:<35} {entry['method']:<8} {entry['path']:<50} {entry['detected_at']}")

        print("""
To resolve, edit apps.yaml and move each pending entry to:
  - pathPolicy.whitelist  →  approve and sync this path
  - pathPolicy.blacklist  →  reject and never sync this path

Example:
  pathPolicy:
    whitelist:
      - path: /v1/payments/search
        approved_by: your-github-user
        approved_at: YYYY-MM-DD
    blacklist:
      - path: /v1/payments/experimental
        reason: "Not stable yet"
        decided_by: your-github-user
        decided_at: YYYY-MM-DD
""")
        sys.exit(1)

    print(f"✅ No pending paths — all {len(apps)} app(s) have resolved policies")
    sys.exit(0)


if __name__ == '__main__':
    main()
