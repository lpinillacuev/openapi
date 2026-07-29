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

# GitHub dark theme colors
GH_BG = "#0d1117"
GH_CARD = "#161b22"
GH_BORDER = "#30363d"
GH_GREEN = "#2ea043"
GH_GREEN_FILL = "#2ea04320"
GH_GRID = "#21262d"
GH_TEXT = "#e6edf3"
GH_SUBTEXT = "#7d8590"


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


def generate_line_svg(data, title, subtitle, value_key, filename):
    """Generate a single-metric line chart matching GitHub's dark style."""
    dates = sorted(data.keys())[-14:]
    if not dates:
        return

    x = [dt.strptime(d, "%Y-%m-%d") for d in dates]
    values = [data[d][value_key] for d in dates]
    total = sum(values)

    fig, ax = plt.subplots(figsize=(5.5, 2.8))
    fig.patch.set_facecolor(GH_CARD)
    ax.set_facecolor(GH_CARD)

    ax.fill_between(x, values, alpha=0.15, color=GH_GREEN, zorder=1)
    ax.plot(x, values, color=GH_GREEN, linewidth=1.8, zorder=2)

    ax.yaxis.grid(True, color=GH_GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["bottom", "left"]:
        ax.spines[spine].set_edgecolor(GH_BORDER)

    ax.tick_params(colors=GH_SUBTEXT, labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=0, ha="center", color=GH_SUBTEXT, fontsize=8)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))

    fig.text(0.04, 0.97, title, color=GH_TEXT, fontsize=10,
             fontweight="bold", va="top", ha="left")
    fig.text(0.04, 0.83, f"{total:,} {subtitle}", color=GH_SUBTEXT,
             fontsize=8.5, va="top", ha="left")

    plt.tight_layout(rect=[0, 0, 1, 0.78])
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAPHS_DIR / filename, format="svg", bbox_inches="tight", facecolor=GH_CARD)
    plt.close(fig)


def generate_bar_svg(items, title, label_key, filename):
    if not items:
        return

    labels = [item.get(label_key, "")[:35] for item in items[:8]]
    totals = [item["count"] for item in items[:8]]
    uniques = [item["uniques"] for item in items[:8]]

    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    fig.patch.set_facecolor(GH_CARD)
    ax.set_facecolor(GH_CARD)

    y = range(len(labels))
    bar_h = 0.35
    ax.barh([i + bar_h / 2 for i in y], totals, bar_h, label="Total",
            color=GH_GREEN, alpha=0.9, zorder=2)
    ax.barh([i - bar_h / 2 for i in y], uniques, bar_h, label="Unique",
            color=GH_GREEN, alpha=0.4, zorder=2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=7.5, color=GH_TEXT)
    ax.invert_yaxis()
    ax.xaxis.grid(True, color=GH_GRID, linewidth=0.7, zorder=0)
    ax.yaxis.grid(False)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["bottom", "left"]:
        ax.spines[spine].set_edgecolor(GH_BORDER)

    ax.tick_params(colors=GH_SUBTEXT, labelsize=8)
    legend = ax.legend(facecolor=GH_CARD, edgecolor=GH_BORDER,
                       labelcolor=GH_TEXT, fontsize=8, framealpha=1)

    fig.text(0.04, 0.97, title, color=GH_TEXT, fontsize=10,
             fontweight="bold", va="top", ha="left")

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(GRAPHS_DIR / filename, format="svg", bbox_inches="tight", facecolor=GH_CARD)
    plt.close(fig)


def generate_html_dashboard(views, clones, referrers, popular_paths):
    views_json = json.dumps({d: views[d] for d in sorted(views.keys())})
    clones_json = json.dumps({d: clones[d] for d in sorted(clones.keys())})
    referrers_json = json.dumps(referrers)
    paths_json = json.dumps(popular_paths)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    total_views = sum(v["count"] for v in views.values())
    total_unique_views = sum(v["uniques"] for v in views.values())
    total_clones = sum(v["count"] for v in clones.values())
    total_unique_clones = sum(v["uniques"] for v in clones.values())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Traffic — {REPO}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
           background: #0d1117; color: #e6edf3; padding: 24px 32px; }}
    h1 {{ font-size: 18px; font-weight: 600; margin-bottom: 2px; }}
    .updated {{ font-size: 12px; color: #7d8590; margin-bottom: 28px; }}
    h2 {{ font-size: 15px; font-weight: 600; margin-bottom: 20px; color: #e6edf3; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
    .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px 20px; }}
    .card-title {{ font-size: 13px; font-weight: 600; color: #e6edf3; margin-bottom: 2px; }}
    .card-stat {{ font-size: 12px; color: #7d8590; margin-bottom: 14px; }}
    canvas {{ max-height: 200px; }}
    section {{ margin-bottom: 32px; }}
    @media (max-width: 640px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>{REPO}</h1>
  <p class="updated">Last updated: {today} · Persisted daily via GitHub Actions</p>

  <section>
    <h2>Git clones</h2>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Clones in last 14 days</div>
        <div class="card-stat" id="stat-clones-total"></div>
        <canvas id="chart-clones-total"></canvas>
      </div>
      <div class="card">
        <div class="card-title">Unique cloners in last 14 days</div>
        <div class="card-stat" id="stat-clones-unique"></div>
        <canvas id="chart-clones-unique"></canvas>
      </div>
    </div>
  </section>

  <section>
    <h2>Visitors</h2>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Total views in last 14 days</div>
        <div class="card-stat" id="stat-views-total"></div>
        <canvas id="chart-views-total"></canvas>
      </div>
      <div class="card">
        <div class="card-title">Unique visitors in last 14 days</div>
        <div class="card-stat" id="stat-views-unique"></div>
        <canvas id="chart-views-unique"></canvas>
      </div>
    </div>
  </section>

  <section>
    <h2>Referring sites &amp; popular content</h2>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Referring sites</div>
        <canvas id="chart-referrers"></canvas>
      </div>
      <div class="card">
        <div class="card-title">Popular content</div>
        <canvas id="chart-paths"></canvas>
      </div>
    </div>
  </section>

<script>
const views = {views_json};
const clones = {clones_json};
const referrers = {referrers_json};
const popularPaths = {paths_json};

const GREEN = "#2ea043";
const GREEN_FILL = "rgba(46,160,67,0.15)";
const GRID = "#21262d";
const TICK = "#7d8590";
const TOOLTIP_BG = "#1c2128";

const last14 = (data) => {{
  const keys = Object.keys(data).sort().slice(-14);
  return {{ keys, counts: keys.map(k => data[k].count), uniques: keys.map(k => data[k].uniques) }};
}};

const lineOpts = (label, unit) => ({{
  responsive: true,
  interaction: {{ mode: "index", intersect: false }},
  plugins: {{
    legend: {{ display: false }},
    tooltip: {{
      backgroundColor: TOOLTIP_BG,
      borderColor: "#30363d",
      borderWidth: 1,
      titleColor: "#e6edf3",
      bodyColor: "#e6edf3",
      callbacks: {{
        title: items => items[0].label.split("T")[0],
        label: ctx => ` ${{label}}: ${{ctx.parsed.y.toLocaleString()}}`,
      }},
    }},
  }},
  scales: {{
    x: {{ type: "time", time: {{ unit, displayFormats: {{ day: "MM/dd", week: "MM/dd" }} }},
          grid: {{ color: GRID }}, ticks: {{ color: TICK, font: {{ size: 11 }} }} }},
    y: {{ grid: {{ color: GRID }}, ticks: {{ color: TICK, font: {{ size: 11 }}, precision: 0 }},
          beginAtZero: true }},
  }},
}});

function makeLine(canvasId, statId, labels, values, statLabel) {{
  const total = values.reduce((a, b) => a + b, 0);
  if (statId) document.getElementById(statId).textContent =
    `${{total.toLocaleString()}} ${{statLabel}}`;

  new Chart(document.getElementById(canvasId), {{
    type: "line",
    data: {{
      labels,
      datasets: [{{
        data: values,
        borderColor: GREEN,
        backgroundColor: GREEN_FILL,
        borderWidth: 1.8,
        fill: true,
        tension: 0.1,
        pointRadius: 3,
        pointHoverRadius: 5,
        pointBackgroundColor: GREEN,
      }}],
    }},
    options: lineOpts(statLabel, "day"),
  }});
}}

const cv = last14(clones);
const vv = last14(views);

makeLine("chart-clones-total", "stat-clones-total", cv.keys, cv.counts, "Clones");
makeLine("chart-clones-unique", "stat-clones-unique", cv.keys, cv.uniques, "Unique cloners");
makeLine("chart-views-total", "stat-views-total", vv.keys, vv.counts, "Views");
makeLine("chart-views-unique", "stat-views-unique", vv.keys, vv.uniques, "Unique visitors");

const barOpts = {{
  indexAxis: "y",
  responsive: true,
  interaction: {{ mode: "index", intersect: false }},
  plugins: {{
    legend: {{ display: false }},
    tooltip: {{
      backgroundColor: TOOLTIP_BG, borderColor: "#30363d", borderWidth: 1,
      titleColor: "#e6edf3", bodyColor: "#e6edf3",
    }},
  }},
  scales: {{
    x: {{ grid: {{ color: GRID }}, ticks: {{ color: TICK, font: {{ size: 11 }}, precision: 0 }}, beginAtZero: true }},
    y: {{ grid: {{ display: false }}, ticks: {{ color: "#e6edf3", font: {{ size: 11 }} }} }},
  }},
}};

new Chart(document.getElementById("chart-referrers"), {{
  type: "bar",
  data: {{
    labels: referrers.slice(0, 8).map(r => r.referrer),
    datasets: [
      {{ label: "Total", data: referrers.slice(0, 8).map(r => r.count), backgroundColor: GREEN, borderRadius: 2 }},
      {{ label: "Unique", data: referrers.slice(0, 8).map(r => r.uniques), backgroundColor: "rgba(46,160,67,0.35)", borderRadius: 2 }},
    ],
  }},
  options: barOpts,
}});

new Chart(document.getElementById("chart-paths"), {{
  type: "bar",
  data: {{
    labels: popularPaths.slice(0, 8).map(p => p.path),
    datasets: [
      {{ label: "Total", data: popularPaths.slice(0, 8).map(p => p.count), backgroundColor: GREEN, borderRadius: 2 }},
      {{ label: "Unique", data: popularPaths.slice(0, 8).map(p => p.uniques), backgroundColor: "rgba(46,160,67,0.35)", borderRadius: 2 }},
    ],
  }},
  options: barOpts,
}});
</script>
</body>
</html>"""

    (GRAPHS_DIR / "index.html").write_text(html)


def write_traffic_md(views, clones, referrers, popular_paths):
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
        for r in referrers[:10]
    )

    path_rows = "\n".join(
        f"| `{p['path']}` | {p['count']:,} | {p['uniques']:,} |"
        for p in popular_paths[:10]
    )

    content = (
        f"# Traffic\n\n"
        f"> Last updated: {today} · Persisted daily via GitHub Actions · "
        f"[Interactive dashboard →](graphs/traffic/index.html)\n\n"
        f"## Page Views\n\n"
        f"![Views total](graphs/traffic/views_total.svg) "
        f"![Views unique](graphs/traffic/views_unique.svg)\n\n"
        f"## Git Clones\n\n"
        f"![Clones total](graphs/traffic/clones_total.svg) "
        f"![Clones unique](graphs/traffic/clones_unique.svg)\n\n"
        f"## Views & Clones — last 14 days\n\n"
        f"| Date | Views | Unique visitors | Clones | Unique cloners |\n"
        f"|------|------:|----------------:|-------:|---------------:|\n"
        f"{chr(10).join(rows)}\n\n"
        f"## Referring Sites\n\n"
        f"![Referrers](graphs/traffic/referrers.svg)\n\n"
        f"| Source | Views | Unique |\n"
        f"|--------|------:|-------:|\n"
        f"{ref_rows}\n\n"
        f"## Popular Content\n\n"
        f"![Popular paths](graphs/traffic/popular_paths.svg)\n\n"
        f"| Path | Views | Unique |\n"
        f"|------|------:|-------:|\n"
        f"{path_rows}\n"
    )

    Path("TRAFFIC.md").write_text(content)


def add_readme_link():
    readme = Path("README.md")
    content = readme.read_text()
    if "TRAFFIC.md" not in content:
        content = content.rstrip() + "\n\n---\n\n[Traffic →](TRAFFIC.md)\n"
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

    # 4 separate SVGs matching GitHub's layout
    generate_line_svg(views, "Total views in last 14 days", "Views", "count", "views_total.svg")
    generate_line_svg(views, "Unique visitors in last 14 days", "Unique visitors", "uniques", "views_unique.svg")
    generate_line_svg(clones, "Clones in last 14 days", "Clones", "count", "clones_total.svg")
    generate_line_svg(clones, "Unique cloners in last 14 days", "Unique cloners", "uniques", "clones_unique.svg")
    generate_bar_svg(referrers, "Referring sites", "referrer", "referrers.svg")
    generate_bar_svg(popular_paths, "Popular content", "path", "popular_paths.svg")

    generate_html_dashboard(views, clones, referrers, popular_paths)
    write_traffic_md(views, clones, referrers, popular_paths)
    add_readme_link()

    print(f"Updated: {len(views)} view records, {len(clones)} clone records")


if __name__ == "__main__":
    main()
