#!/usr/bin/env python3
"""Generate profile SVGs (typing header, top languages, trophies, contribution graph).

Runs inside GitHub Actions using the built-in GITHUB_TOKEN, so it does not depend on
any flaky third-party image service. Output goes to ./assets/.

    python scripts/generate_stats.py          # typing header + live GitHub data
    python scripts/generate_stats.py --demo   # fake data, for local testing
"""
import json
import os
import sys
import urllib.request
from html import escape

OUT = "assets"
BG, CARD, TXT, MUTED = "#020617", "#0B1224", "#E0F2FE", "#7DD3FC"
CYAN, BLUE, PURPLE = "#22D3EE", "#3B82F6", "#8B5CF6"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"

LANG_COLORS = {
    "Python": "#3572A5", "Jupyter Notebook": "#DA5B0B", "JavaScript": "#F1E05A",
    "TypeScript": "#3178C6", "HTML": "#E34C26", "CSS": "#563D7C", "Shell": "#89E051",
    "Dockerfile": "#384D54", "SQL": "#E38C00", "Java": "#B07219", "C++": "#F34B7D",
    "C": "#555555", "R": "#198CE7", "Go": "#00ADD8", "PLpgSQL": "#336790",
}
FALLBACK = [CYAN, BLUE, PURPLE, "#F472B6", "#FBBF24", "#34D399", "#FB7185", "#A3E635"]


# ----------------------------------------------------------------------------- typing
def typing_svg(lines, width=900, height=60, size=24, per_line=3.2):
    """Self-contained animated typing header (SMIL, no external requests)."""
    char_w = size * 0.6  # monospace advance
    total = per_line * len(lines)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(" | ".join(lines))}">',
        "<defs>",
    ]
    for i, text in enumerate(lines):
        w = len(text) * char_w
        x = (width - w) / 2
        s = i * per_line / total
        grow = s + 1.5 / total          # finish typing
        hold = s + (per_line - 0.3) / total  # start erasing
        end = s + per_line / total
        kt = [0.0, s, grow, hold, end, 1.0]
        vals = [0, 0, w + 4, w + 4, 0, 0]
        # keyTimes must be strictly valid: monotonic, start 0, end 1
        pairs = []
        for k, v in zip(kt, vals):
            pairs.append((min(max(k, 0.0), 1.0), v))
        pairs = sorted(pairs, key=lambda p: p[0])
        pairs[0] = (0.0, pairs[0][1])
        pairs[-1] = (1.0, pairs[-1][1])
        kts = ";".join(f"{p[0]:.4f}" for p in pairs)
        vs = ";".join(f"{p[1]:.1f}" for p in pairs)
        parts.append(
            f'<clipPath id="c{i}"><rect x="{x:.1f}" y="0" height="{height}" width="0">'
            f'<animate attributeName="width" dur="{total}s" repeatCount="indefinite" '
            f'keyTimes="{kts}" values="{vs}"/></rect></clipPath>'
        )
    parts.append("</defs>")
    for i, text in enumerate(lines):
        w = len(text) * char_w
        x = (width - w) / 2
        parts.append(
            f'<text x="{x:.1f}" y="{height/2 + size*0.35:.1f}" clip-path="url(#c{i})" '
            f'font-family="\'Courier New\', Consolas, monospace" font-size="{size}" '
            f'font-weight="700" fill="{CYAN}" xml:space="preserve">{escape(text)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


# ----------------------------------------------------------------------------- GitHub API
def _req(url, data=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-stats"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(login):
    repos, page = [], 1
    while True:
        chunk = _req(f"https://api.github.com/users/{login}/repos?per_page=100&type=owner&page={page}")
        repos += chunk
        if len(chunk) < 100:
            break
        page += 1

    langs = {}
    for r in repos:
        if r.get("fork"):
            continue
        for name, n in _req(r["languages_url"]).items():
            langs[name] = langs.get(name, 0) + n

    query = """query($login:String!){ user(login:$login){
      followers{totalCount}
      pullRequests{totalCount}
      issues{totalCount}
      contributionsCollection{
        totalCommitContributions
        contributionCalendar{ totalContributions weeks{ contributionDays{ date contributionCount } } }
      } } }"""
    res = _req("https://api.github.com/graphql", {"query": query, "variables": {"login": login}})
    u = res["data"]["user"]
    days = [d for w in u["contributionsCollection"]["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]]
    return {
        "langs": langs,
        "stars": sum(r["stargazers_count"] for r in repos),
        "repos": len(repos),
        "followers": u["followers"]["totalCount"],
        "prs": u["pullRequests"]["totalCount"],
        "issues": u["issues"]["totalCount"],
        "commits": u["contributionsCollection"]["totalCommitContributions"],
        "total_contrib": u["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "days": days,
    }


# ----------------------------------------------------------------------------- renderers
def _frame(w, h, title, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<rect width="{w}" height="{h}" rx="10" fill="{BG}" stroke="#1E293B"/>'
        f'<text x="24" y="34" font-family="{FONT}" font-size="18" font-weight="700" fill="{CYAN}">{escape(title)}</text>'
        f"{body}</svg>"
    )


def languages_svg(langs, top=6):
    w, h = 420, 220
    total = sum(langs.values()) or 1
    items = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:top]
    shown = sum(v for _, v in items) or 1
    bar, x, legend = [], 24.0, []
    bar_w = w - 48
    for i, (name, v) in enumerate(items):
        color = LANG_COLORS.get(name, FALLBACK[i % len(FALLBACK)])
        seg = bar_w * v / shown
        bar.append(f'<rect x="{x:.1f}" y="52" width="{seg:.1f}" height="10" fill="{color}"/>')
        x += seg
        col, row = i % 2, i // 2
        lx, ly = 24 + col * 200, 92 + row * 30
        pct = 100 * v / total
        legend.append(
            f'<circle cx="{lx+5}" cy="{ly-4}" r="5" fill="{color}"/>'
            f'<text x="{lx+18}" y="{ly}" font-family="{FONT}" font-size="13" fill="{TXT}">{escape(name)} '
            f'<tspan fill="{MUTED}">{pct:.1f}%</tspan></text>'
        )
    clip = f'<clipPath id="r"><rect x="24" y="52" width="{bar_w}" height="10" rx="5"/></clipPath>'
    return _frame(w, h, "Top Languages", clip + '<g clip-path="url(#r)">' + "".join(bar) + "</g>" + "".join(legend))


def trophies_svg(d):
    tiles = [
        ("Stars", d["stars"], (10, 50, 100, 500)),
        ("Commits", d["commits"], (50, 200, 500, 1000)),
        ("Followers", d["followers"], (5, 20, 100, 500)),
        ("Repos", d["repos"], (5, 15, 30, 60)),
        ("Pull Requests", d["prs"], (5, 25, 100, 300)),
        ("Issues", d["issues"], (5, 25, 100, 300)),
    ]
    ranks = [("C", "#64748B"), ("B", "#3B82F6"), ("A", "#8B5CF6"), ("S", "#22D3EE")]
    tw, th, gap = 120, 130, 12
    w = 24 + len(tiles) * (tw + gap) - gap + 24
    out = []
    for i, (label, val, thr) in enumerate(tiles):
        rank = "-" if val == 0 else ranks[max(j for j in range(4) if j == 0 or val >= thr[j - 1])][0]
        color = "#334155" if val == 0 else dict(ranks)[rank]
        x = 24 + i * (tw + gap)
        out.append(
            f'<g transform="translate({x},56)"><rect width="{tw}" height="{th}" rx="10" fill="{CARD}" stroke="{color}"/>'
            f'<circle cx="{tw/2}" cy="42" r="26" fill="none" stroke="{color}" stroke-width="3"/>'
            f'<text x="{tw/2}" y="50" text-anchor="middle" font-family="{FONT}" font-size="24" font-weight="800" fill="{color}">{rank}</text>'
            f'<text x="{tw/2}" y="94" text-anchor="middle" font-family="{FONT}" font-size="18" font-weight="700" fill="{TXT}">{val}</text>'
            f'<text x="{tw/2}" y="114" text-anchor="middle" font-family="{FONT}" font-size="11" fill="{MUTED}">{escape(label)}</text></g>'
        )
    return _frame(w, 56 + th + 24, "Trophies", "".join(out))


def graph_svg(days, window=60):
    w, h = 860, 260
    pts = [d["contributionCount"] for d in days[-window:]]
    labels = [d["date"][5:] for d in days[-window:]]
    left, right, top, bottom = 50, 24, 56, 40
    pw, ph = w - left - right, h - top - bottom
    ymax = max(max(pts), 1)
    ymax = ymax + (-ymax) % 2 if ymax > 1 else 2
    n = len(pts)
    xs = [left + pw * i / max(n - 1, 1) for i in range(n)]
    ys = [top + ph * (1 - v / ymax) for v in pts]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{left},{top+ph} " + line + f" {left+pw},{top+ph}"
    grid = "".join(
        f'<line x1="{left}" x2="{left+pw}" y1="{top+ph*k/4:.1f}" y2="{top+ph*k/4:.1f}" stroke="#1E293B"/>'
        f'<text x="{left-8}" y="{top+ph*k/4+4:.1f}" text-anchor="end" font-family="{FONT}" font-size="10" fill="{MUTED}">{round(ymax*(1-k/4))}</text>'
        for k in range(5)
    )
    xl = "".join(
        f'<text x="{xs[i]:.1f}" y="{h-14}" text-anchor="middle" font-family="{FONT}" font-size="10" fill="{MUTED}">{labels[i]}</text>'
        for i in range(0, n, max(n // 8, 1))
    )
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{PURPLE}"/>' for x, y in zip(xs, ys))
    grad = (f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{CYAN}" stop-opacity=".45"/>'
            f'<stop offset="1" stop-color="{CYAN}" stop-opacity="0"/></linearGradient></defs>')
    body = (grad + grid + f'<polygon points="{area}" fill="url(#g)"/>'
            f'<polyline points="{line}" fill="none" stroke="{CYAN}" stroke-width="2"/>' + dots + xl)
    return _frame(w, h, f"Contribution Graph (last {n} days)", body)


def streak_svg(days, total):
    from datetime import date, timedelta
    counts = {d["date"]: d["contributionCount"] for d in days}
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    # current streak: walk back from today (or yesterday if today has no contributions yet)
    cur, day = 0, date.fromisoformat(days[-1]["date"])
    if counts.get(day.isoformat(), 0) == 0:
        day -= timedelta(days=1)
    while counts.get(day.isoformat(), 0) > 0:
        cur += 1
        day -= timedelta(days=1)
    w, h = 420, 220
    def col(x, big, label, color):
        return (f'<text x="{x}" y="120" text-anchor="middle" font-family="{FONT}" font-size="34" font-weight="800" fill="{color}">{big}</text>'
                f'<text x="{x}" y="148" text-anchor="middle" font-family="{FONT}" font-size="12" fill="{MUTED}">{label}</text>')
    body = (col(70, total, "Contributions (1 yr)", TXT) + col(210, cur, "Current Streak", CYAN)
            + col(350, longest, "Longest Streak", PURPLE)
            + f'<circle cx="210" cy="95" r="52" fill="none" stroke="{CYAN}" stroke-width="3" opacity=".25"/>')
    return _frame(w, h, "Contribution Streak", body)


# ----------------------------------------------------------------------------- main
TYPING_LINES = [
    "Aspiring Data Scientist",
    "Machine Learning & AI Engineering Student",
    "Generative AI | LLMs | RAG | MCP",
    "MLOps | Docker | Kubernetes | MLflow",
    "Building Scalable Data-Driven AI Solutions",
]


def demo_data():
    import random
    random.seed(1)
    return {
        "langs": {"Python": 90000, "Jupyter Notebook": 60000, "TypeScript": 20000, "HTML": 8000, "Dockerfile": 3000, "Shell": 1500},
        "stars": 12, "repos": 18, "followers": 7, "prs": 14, "issues": 3, "commits": 240, "total_contrib": 400,
        "days": [{"date": f"2026-{1 + i // 30:02d}-{1 + i % 28:02d}", "contributionCount": random.randint(0, 9)} for i in range(120)],
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(f"{OUT}/typing.svg", "w", encoding="utf-8") as f:
        f.write(typing_svg(TYPING_LINES))
    if "--typing-only" in sys.argv:
        return
    d = demo_data() if "--demo" in sys.argv else fetch(os.environ.get("GITHUB_REPOSITORY_OWNER", "SanidhyaDS"))
    for name, svg in (("top-langs", languages_svg(d["langs"])), ("trophies", trophies_svg(d)),
                      ("streak", streak_svg(d["days"], d["total_contrib"])),
                      ("contribution-graph", graph_svg(d["days"]))):
        with open(f"{OUT}/{name}.svg", "w", encoding="utf-8") as f:
            f.write(svg)
    print("generated", os.listdir(OUT))


if __name__ == "__main__":
    main()
