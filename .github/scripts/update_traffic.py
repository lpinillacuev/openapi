import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime as dt

REPO = os.environ.get("GITHUB_REPOSITORY", "mercadopago/openapi")
TOKEN = os.environ["TRAFFIC_TOKEN"]
GRAPHS_DIR = Path("graphs/traffic")


def gh_api(path):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def load_json(path, default):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def merge_time_series(existing, items, date_key, count_key, uniques_key):
    for item in items:
        date = item[date_key][:10]
        existing[date] = {"count": item[count_key], "uniques": item[uniques_key]}
    return existing


def generate_chart(data, title, filename, color_total, color_unique):
    dates = sorted(data.keys())[-30:]
    x = [dt.strptime(d, "%Y-%m-%d") for d in dates]
    totals = [data[d]["count"] for d in dates]
    uniques = [data[d]["uniques"] for d in dates]

    fig, ax = plt.subplots(figsize=(10, 3.5))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    ax.fill_between(x, totals, alpha=0.15, color=color_total)
    ax.plot(x, totals, color=color_total, linewidth=2, label="Total")
    ax.fill_between(x, uniques, alpha=0.15, color=color_unique)
    ax.plot(x, uniques, color=color_unique, linewidth=2, linestyle="--", label="Unique")

    ax.set_title(title, color="#e6edf3", fontsize=13, pad=12)
    ax.tick_params(colors="#8b949e", labelsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.xticks(rotation=30, ha="right")

    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")

    ax.yaxis.grid(True, color="#21262d", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(facecolor="#161b22", edgecolor="#30363d", labelcolor="#8b949e", fontsize=9)

    plt.tight_layout()
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAPHS_DIR / filename, format="svg", bbox_inches="tight")
    plt.close(fig)


def build_traffic_section(views, clones):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dates = sorted(set(views) | set(clones), reverse=True)[:14]

    rows = []
    for date in dates:
        v = views.get(date, {})
        c = clones.get(date, {})
        rows.append(
            f"| {date} | {v.get('count', 0):,} | {v.get('uniques', 0):,} "
            f"| {c.get('count', 0):,} | {c.get('uniques', 0):,} |"
        )

    table = "\n".join(rows)
    return (
        f"<!-- TRAFFIC_START -->\n"
        f"## Traffic\n\n"
        f"> Last updated: {today} · Persisted daily via GitHub Actions\n\n"
        f"![Views](graphs/traffic/views.svg)\n"
        f"![Clones](graphs/traffic/clones.svg)\n\n"
        f"| Date | Views | Unique visitors | Clones | Unique cloners |\n"
        f"|------|------:|----------------:|-------:|---------------:|\n"
        f"{table}\n\n"
        f"<!-- TRAFFIC_END -->"
    )


def update_readme(views, clones):
    readme = Path("README.md")
    content = readme.read_text()
    section = build_traffic_section(views, clones)

    if "<!-- TRAFFIC_START -->" in content:
        content = re.sub(
            r"<!-- TRAFFIC_START -->.*?<!-- TRAFFIC_END -->",
            section,
            content,
            flags=re.DOTALL,
        )
    else:
        content = content.rstrip() + "\n\n" + section + "\n"

    readme.write_text(content)


def main():
    views_data = gh_api("traffic/views")
    clones_data = gh_api("traffic/clones")

    views = load_json(GRAPHS_DIR / "views.json", {})
    clones = load_json(GRAPHS_DIR / "clones.json", {})

    views = merge_time_series(views, views_data["views"], "timestamp", "count", "uniques")
    clones = merge_time_series(clones, clones_data["clones"], "timestamp", "count", "uniques")

    save_json(GRAPHS_DIR / "views.json", views)
    save_json(GRAPHS_DIR / "clones.json", clones)

    generate_chart(views, "Page Views", "views.svg", "#2f81f7", "#3fb950")
    generate_chart(clones, "Git Clones", "clones.svg", "#a371f7", "#f78166")

    update_readme(views, clones)

    print(f"Updated: {len(views)} view records, {len(clones)} clone records")


if __name__ == "__main__":
    main()
