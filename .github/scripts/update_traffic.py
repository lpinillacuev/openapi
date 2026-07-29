import json
import os
import re
import urllib.request
from datetime import datetime, timezone, datetime as dt
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MaxNLocator

REPO = os.environ.get("GITHUB_REPOSITORY", "mercadopago/openapi")
TOKEN = os.environ["TRAFFIC_TOKEN"]
GRAPHS_DIR = Path("graphs/traffic")

GH_BLUE = "#0969da"
GH_GREEN = "#1a7f37"
GH_PURPLE = "#8250df"
GH_ORANGE = "#bc4c00"
GH_GRID = "#eaeef2"
GH_TEXT = "#24292f"
GH_SUBTEXT = "#57606a"
GH_BG = "#ffffff"


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


def setup_ax(ax, title):
    ax.set_facecolor(GH_BG)
    ax.set_title(title, color=GH_TEXT, fontsize=12, fontweight="semibold", pad=10, loc="left")
    ax.tick_params(colors=GH_SUBTEXT, labelsize=9)
    ax.yaxis.grid(True, color=GH_GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["bottom", "left"]:
        ax.spines[spine].set_edgecolor(GH_GRID)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))


def generate_line_chart(data, title, filename, color_total, color_unique):
    dates = sorted(data.keys())[-30:]
    if not dates:
        return

    x = [dt.strptime(d, "%Y-%m-%d") for d in dates]
    totals = [data[d]["count"] for d in dates]
    uniques = [data[d]["uniques"] for d in dates]

    fig, ax = plt.subplots(figsize=(9, 3))
    fig.patch.set_facecolor(GH_BG)
    setup_ax(ax, title)

    ax.fill_between(x, totals, alpha=0.1, color=color_total, zorder=1)
    ax.plot(x, totals, color=color_total, linewidth=2, label="Total", zorder=2)
    ax.fill_between(x, uniques, alpha=0.15, color=color_unique, zorder=1)
    ax.plot(x, uniques, color=color_unique, linewidth=2, linestyle="--", label="Unique", zorder=2)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=20, ha="right", color=GH_SUBTEXT, fontsize=9)

    legend = ax.legend(
        facecolor=GH_BG, edgecolor=GH_GRID,
        labelcolor=GH_TEXT, fontsize=9, framealpha=1,
    )

    plt.tight_layout(pad=1.2)
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAPHS_DIR / filename, format="svg", bbox_inches="tight", facecolor=GH_BG)
    plt.close(fig)


def generate_bar_chart(items, title, filename, color):
    if not items:
        return

    labels = [item.get("referrer") or item.get("path", "")[:40] for item in items[:10]]
    totals = [item["count"] for item in items[:10]]
    uniques = [item["uniques"] for item in items[:10]]

    fig, ax = plt.subplots(figsize=(9, 3.5))
    fig.patch.set_facecolor(GH_BG)
    setup_ax(ax, title)

    y = range(len(labels))
    bar_h = 0.35
    ax.barh([i + bar_h / 2 for i in y], totals, bar_h, label="Total", color=color, alpha=0.85, zorder=2)
    ax.barh([i - bar_h / 2 for i in y], uniques, bar_h, label="Unique", color=color, alpha=0.4, zorder=2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8, color=GH_TEXT)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=GH_GRID, linewidth=0.8, zorder=0)
    ax.yaxis.grid(False)

    ax.legend(facecolor=GH_BG, edgecolor=GH_GRID, labelcolor=GH_TEXT, fontsize=9, framealpha=1)

    plt.tight_layout(pad=1.2)
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAPHS_DIR / filename, format="svg", bbox_inches="tight", facecolor=GH_BG)
    plt.close(fig)


def generate_html_dashboard(views, clones, referrers, popular_paths):
    views_json = json.dumps({d: views[d] for d in sorted(views.keys())})
    clones_json = json.dumps({d: clones[d] for d in sorted(clones.keys())})
    referrers_json = json.dumps(referrers)
    paths_json = json.dumps(popular_paths)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Traffic Dashboard — {REPO}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f8fa; color: #24292f; padding: 24px; }}
    h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 4px; }}
    .subtitle {{ font-size: 13px; color: #57606a; margin-bottom: 24px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .card {{ background: #fff; border: 1px solid #d0d7de; border-radius: 6px; padding: 20px; }}
    .card h2 {{ font-size: 14px; font-weight: 600; margin-bottom: 16px; color: #24292f; }}
    canvas {{ max-height: 220px; }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>{REPO} — Traffic Dashboard</h1>
  <p class="subtitle">Last updated: {today} · Data persisted daily via GitHub Actions</p>
  <div class="grid">
    <div class="card"><h2>Page Views</h2><canvas id="views"></canvas></div>
    <div class="card"><h2>Git Clones</h2><canvas id="clones"></canvas></div>
    <div class="card"><h2>Referring Sites</h2><canvas id="referrers"></canvas></div>
    <div class="card"><h2>Popular Content</h2><canvas id="paths"></canvas></div>
  </div>
  <script>
    const views = {views_json};
    const clones = {clones_json};
    const referrers = {referrers_json};
    const popularPaths = {paths_json};

    const lineDefaults = {{
      tension: 0.3, pointRadius: 2, pointHoverRadius: 5, fill: true,
    }};

    function makeTimeSeries(data, colorTotal, colorUnique) {{
      const labels = Object.keys(data);
      return {{
        labels,
        datasets: [
          {{ ...lineDefaults, label: "Total", data: labels.map(d => data[d].count),
             borderColor: colorTotal, backgroundColor: colorTotal + "18" }},
          {{ ...lineDefaults, label: "Unique", data: labels.map(d => data[d].uniques),
             borderColor: colorUnique, backgroundColor: colorUnique + "18", borderDash: [4,3] }},
        ],
      }};
    }}

    const timeOpts = {{
      responsive: true, interaction: {{ mode: "index", intersect: false }},
      plugins: {{ legend: {{ labels: {{ font: {{ size: 12 }} }} }} }},
      scales: {{
        x: {{ type: "time", time: {{ unit: "day", displayFormats: {{ day: "MMM d" }} }},
              grid: {{ color: "#eaeef2" }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{ grid: {{ color: "#eaeef2" }}, ticks: {{ font: {{ size: 11 }}, precision: 0 }} }},
      }},
    }};

    new Chart(document.getElementById("views"), {{ type: "line", data: makeTimeSeries(views, "#0969da", "#1a7f37"), options: timeOpts }});
    new Chart(document.getElementById("clones"), {{ type: "line", data: makeTimeSeries(clones, "#8250df", "#bc4c00"), options: timeOpts }});

    function makeBar(items, labelKey, color) {{
      const top = items.slice(0, 8);
      return {{
        labels: top.map(i => i[labelKey]),
        datasets: [
          {{ label: "Total", data: top.map(i => i.count), backgroundColor: color + "cc" }},
          {{ label: "Unique", data: top.map(i => i.uniques), backgroundColor: color + "55" }},
        ],
      }};
    }}

    const barOpts = {{
      indexAxis: "y", responsive: true,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{ legend: {{ labels: {{ font: {{ size: 12 }} }} }} }},
      scales: {{
        x: {{ grid: {{ color: "#eaeef2" }}, ticks: {{ font: {{ size: 11 }}, precision: 0 }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
      }},
    }};

    new Chart(document.getElementById("referrers"), {{ type: "bar", data: makeBar(referrers, "referrer", "#0969da"), options: barOpts }});
    new Chart(document.getElementById("paths"), {{ type: "bar", data: makeBar(popularPaths, "path", "#8250df"), options: barOpts }});
  </script>
</body>
</html>"""

    (GRAPHS_DIR / "index.html").write_text(html)


def build_readme_section(views, clones, referrers, popular_paths):
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

    ref_rows = "\n".join(
        f"| {r['referrer']} | {r['count']:,} | {r['uniques']:,} |"
        for r in referrers[:5]
    )

    path_rows = "\n".join(
        f"| `{p['path']}` | {p['count']:,} | {p['uniques']:,} |"
        for p in popular_paths[:5]
    )

    return (
        f"<!-- TRAFFIC_START -->\n"
        f"## Traffic\n\n"
        f"> Last updated: {today} · Persisted daily via GitHub Actions · "
        f"[Interactive dashboard](graphs/traffic/index.html)\n\n"
        f"![Views](graphs/traffic/views.svg)\n"
        f"![Clones](graphs/traffic/clones.svg)\n\n"
        f"<details>\n<summary>Full table (last 14 days)</summary>\n\n"
        f"| Date | Views | Unique visitors | Clones | Unique cloners |\n"
        f"|------|------:|----------------:|-------:|---------------:|\n"
        f"{chr(10).join(rows)}\n\n"
        f"</details>\n\n"
        f"### Referring sites\n\n"
        f"![Referrers](graphs/traffic/referrers.svg)\n\n"
        f"| Source | Views | Unique |\n"
        f"|--------|------:|-------:|\n"
        f"{ref_rows}\n\n"
        f"### Popular content\n\n"
        f"![Popular paths](graphs/traffic/popular_paths.svg)\n\n"
        f"| Path | Views | Unique |\n"
        f"|------|------:|-------:|\n"
        f"{path_rows}\n\n"
        f"<!-- TRAFFIC_END -->"
    )


def update_readme(views, clones, referrers, popular_paths):
    readme = Path("README.md")
    content = readme.read_text()
    section = build_readme_section(views, clones, referrers, popular_paths)

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
    views_raw = gh_api("traffic/views")
    clones_raw = gh_api("traffic/clones")
    referrers = gh_api("traffic/popular/referrers")
    popular_paths = gh_api("traffic/popular/paths")

    views = load_json(GRAPHS_DIR / "views.json", {})
    clones = load_json(GRAPHS_DIR / "clones.json", {})

    views = merge_time_series(views, views_raw["views"], "timestamp", "count", "uniques")
    clones = merge_time_series(clones, clones_raw["clones"], "timestamp", "count", "uniques")

    save_json(GRAPHS_DIR / "views.json", views)
    save_json(GRAPHS_DIR / "clones.json", clones)
    save_json(GRAPHS_DIR / "referrers.json", referrers)
    save_json(GRAPHS_DIR / "popular_paths.json", popular_paths)

    generate_line_chart(views, "Page Views", "views.svg", GH_BLUE, GH_GREEN)
    generate_line_chart(clones, "Git Clones", "clones.svg", GH_PURPLE, GH_ORANGE)
    generate_bar_chart(referrers, "Referring Sites", "referrers.svg", GH_BLUE)
    generate_bar_chart(popular_paths, "Popular Content", "popular_paths.svg", GH_PURPLE)

    generate_html_dashboard(views, clones, referrers, popular_paths)

    update_readme(views, clones, referrers, popular_paths)

    print(f"Updated: {len(views)} view records, {len(clones)} clone records")


if __name__ == "__main__":
    main()
