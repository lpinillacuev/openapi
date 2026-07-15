#!/usr/bin/env python3
"""
Sync KVS policy decisions after a merge to main.

For each app in apps.yaml, calls the bot sync-from-merge endpoint so it can
compare the merged spec3.yaml against pending KVS paths and finalize decisions
(approved paths → whitelist, rejected paths → blacklist).

Environment variables (set as GitHub Actions secrets/vars):
    BOT_URL     Base URL of the bot service
    GH_PAT      GitHub personal access token for bot auth
    COMMIT_SHA  SHA of the merge commit
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    bot_url = os.environ.get("BOT_URL", "https://beta-bot-sync-specs.melioffice.com")
    token = os.environ.get("GH_PAT", "")
    commit_sha = os.environ.get("COMMIT_SHA", "")

    if not token:
        print("Warning: GH_PAT not set — skipping KVS sync", file=sys.stderr)
        sys.exit(0)

    apps_path = ROOT / "apps.yaml"
    if not apps_path.exists():
        print("apps.yaml not found — skipping KVS sync", file=sys.stderr)
        sys.exit(0)

    apps = yaml.safe_load(apps_path.read_text(encoding="utf-8")).get("apps", [])

    for app in apps:
        fury_app = app["fury_app"]
        print(f"Syncing KVS for {fury_app}...")
        try:
            result = subprocess.run(
                [
                    "curl", "-s", "-X", "POST",
                    f"{bot_url}/openapi/policy/{fury_app}/sync-from-merge",
                    "-H", "Content-Type: application/json",
                    "-H", f"X-github-token: {token}",
                    "-d", json.dumps({"commitSha": commit_sha}),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            print(result.stdout or "no response")
        except Exception as e:
            print(f"Warning: could not sync KVS for {fury_app}: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
