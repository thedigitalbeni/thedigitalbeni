"""
update_contribs.py
──────────────────
Detects all 4 GitHub contribution types (issues, pull requests,
code reviews, commits) for external repos and updates the README
between OPEN_SOURCE_START / OPEN_SOURCE_END markers.

Rules:
  - Manually-added rows (custom status text) are NEVER touched.
  - Script-managed rows (auto-generated status) get their counts refreshed.
  - New repos discovered by the API are appended.
  - Major orgs (Google, Microsoft, etc.) always sort to the top.

Place at: .github/scripts/update_contribs.py
"""

import os
import json
import re
import urllib.request

USERNAME  = "thedigitalbeni"
README    = "README.md"
START_TAG = "<!-- OPEN_SOURCE_START -->"
END_TAG   = "<!-- OPEN_SOURCE_END -->"

# Matches any status line this script generates — used to tell manual vs auto rows apart
SCRIPT_ROW_RE = re.compile(
    r"✅\s+("
    r"\d+\s+PRs?\s+merged"
    r"|\d+\s+commits?"
    r"|\d+\s+issues?\s+filed"
    r"|\d+\s+code\s+reviews?"
    r"|Contributor"
    r")"
)

MAJOR_ORGS = {
    "google", "google-gemini", "google-deepmind", "googlecodelabs",
    "microsoft", "azure", "dotnet",
    "meta", "facebookresearch", "pytorch",
    "openai", "anthropics",
    "apple",
    "amazon", "aws", "awslabs",
    "vercel", "nextjs",
    "nodejs", "npm",
    "docker", "kubernetes", "helm",
    "facebook", "instagram",
    "twitter", "twitterdev",
    "github", "actions",
    "mozilla", "apache",
    "linux", "torvalds",
    "rust-lang", "golang", "python",
}

# ── GitHub API helpers ────────────────────────────────────────────────────────

def _request(url: str, extra_accept: str = "") -> dict:
    token = os.environ.get("GH_TOKEN", "")
    req   = urllib.request.Request(url)
    req.add_header("Accept",     extra_accept or "application/vnd.github.v3+json")
    req.add_header("User-Agent", "readme-contrib-updater")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())

def _paginate_issues(query: str) -> dict[str, int]:
    """Run a paginated GitHub issue-search query and return {repo: count}."""
    repos: dict[str, int] = {}
    page = 1
    while True:
        url  = f"https://api.github.com/search/issues?q={query}&per_page=100&page={page}"
        data = _request(url)
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            parts     = item["repository_url"].split("/")
            full_name = f"{parts[-2]}/{parts[-1]}"
            repos[full_name] = repos.get(full_name, 0) + 1
        if len(items) < 100:
            break
        page += 1
    return repos

# ── Fetch all 4 contribution types ───────────────────────────────────────────

def fetch_all_contributions() -> dict[str, dict]:
    """
    Returns {full_repo_name: {prs, issues, reviews, commits}}
    for every external repo the user has contributed to.
    """
    result: dict[str, dict] = {}

    def add(full_name: str, kind: str, n: int = 1) -> None:
        if full_name not in result:
            result[full_name] = {"prs": 0, "issues": 0, "reviews": 0, "commits": 0}
        result[full_name][kind] += n

    def exclude_own() -> str:
        return f"+-user:{USERNAME}"

    # 1. Merged pull requests authored by the user
    print("  → Fetching merged PRs …")
    for repo, n in _paginate_issues(
        f"type:pr+is:merged+author:{USERNAME}{exclude_own()}"
    ).items():
        add(repo, "prs", n)

    # 2. Issues filed by the user
    print("  → Fetching issues …")
    for repo, n in _paginate_issues(
        f"type:issue+author:{USERNAME}{exclude_own()}"
    ).items():
        add(repo, "issues", n)

    # 3. PRs reviewed by the user (but not authored)
    print("  → Fetching code reviews …")
    for repo, n in _paginate_issues(
        f"type:pr+reviewed-by:{USERNAME}+-author:{USERNAME}{exclude_own()}"
    ).items():
        add(repo, "reviews", n)

    # 4. Commits to external repos
    print("  → Fetching commits …")
    try:
        page = 1
        while True:
            url  = (
                f"https://api.github.com/search/commits"
                f"?q=author:{USERNAME}{exclude_own()}&per_page=100&page={page}"
            )
            data  = _request(url, extra_accept="application/vnd.github.cloak-preview")
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                repo_info = item.get("repository", {})
                owner     = repo_info.get("owner", {}).get("login", "")
                repo_name = repo_info.get("name", "")
                if owner and repo_name and owner.lower() != USERNAME.lower():
                    add(f"{owner}/{repo_name}", "commits")
            if len(items) < 100:
                break
            page += 1
    except Exception as exc:
        print(f"  ⚠  Commit search skipped ({exc})")

    return result

# ── Status label builder ──────────────────────────────────────────────────────

def status_label(data: dict) -> str:
    parts = []
    if data.get("prs"):
        n = data["prs"]
        parts.append(f"{n} PR{'s' if n > 1 else ''} merged")
    if data.get("commits"):
        n = data["commits"]
        parts.append(f"{n} commit{'s' if n > 1 else ''}")
    if data.get("issues"):
        n = data["issues"]
        parts.append(f"{n} issue{'s' if n > 1 else ''} filed")
    if data.get("reviews"):
        n = data["reviews"]
        parts.append(f"{n} code review{'s' if n > 1 else ''}")
    return "✅ " + (" · ".join(parts) if parts else "Contributor")

# ── Sort: major orgs first, then by total contribution count ─────────────────

def sort_key(item: tuple) -> tuple:
    full_name, data = item
    org      = full_name.split("/")[0].lower()
    is_major = 0 if org in MAJOR_ORGS else 1
    total    = sum(data.values())
    return (is_major, -total)

# ── README parsing ────────────────────────────────────────────────────────────

def parse_existing_rows(content: str) -> list[str]:
    """
    Extract <tr> rows from inside <tbody> only — never touches <thead>.
    This prevents the duplicate-header bug.
    """
    outer = re.compile(
        re.escape(START_TAG) + r".*?" + re.escape(END_TAG), re.DOTALL
    )
    outer_match = outer.search(content)
    if not outer_match:
        return []

    tbody_match = re.search(r"<tbody>(.*?)</tbody>", outer_match.group(), re.DOTALL)
    if not tbody_match:
        return []

    return re.findall(r"<tr>.*?</tr>", tbody_match.group(1), re.DOTALL)

def is_script_managed(row: str) -> bool:
    """True if the row was written by this script (safe to update)."""
    return bool(SCRIPT_ROW_RE.search(row))

def row_has_repo(row: str, full_name: str) -> bool:
    repo_part = full_name.split("/", 1)[1].lower()
    return repo_part in row.lower()

# ── Table builder ─────────────────────────────────────────────────────────────

def build_table(dynamic: dict[str, dict], existing_rows: list[str]) -> str:
    header = (
        "<table>\n"
        "<thead><tr>"
        "<th>Organization</th><th>Repository</th><th>Status</th>"
        "</tr></thead>\n"
        "<tbody>\n"
    )
    footer = "</tbody>\n</table>\n"
    rows   = ""

    # Step 1 — preserve all manually-added rows exactly as written
    for row in existing_rows:
        if not is_script_managed(row):
            rows += row + "\n"

    # Step 2 — refresh counts on script-managed rows
    for row in existing_rows:
        if not is_script_managed(row):
            continue
        matched = next((fn for fn in dynamic if row_has_repo(row, fn)), None)
        if matched:
            org, repo = matched.split("/", 1)
            rows += (
                f"<tr><td><code>@{org}</code></td>"
                f"<td><a href=\"https://github.com/{matched}\">{repo}</a></td>"
                f"<td>{status_label(dynamic[matched])}</td></tr>\n"
            )
        else:
            rows += row + "\n"   # repo not in API results this run — keep as-is

    # Step 3 — append brand-new repos not yet in the table
    for full_name, data in sorted(dynamic.items(), key=sort_key):
        if any(row_has_repo(r, full_name) for r in existing_rows):
            continue
        org, repo = full_name.split("/", 1)
        rows += (
            f"<tr><td><code>@{org}</code></td>"
            f"<td><a href=\"https://github.com/{full_name}\">{repo}</a></td>"
            f"<td>{status_label(data)}</td></tr>\n"
        )

    if not rows.strip():
        rows = (
            "<tr><td>—</td>"
            "<td>No external contributions found yet</td>"
            "<td>—</td></tr>\n"
        )

    return header + rows + footer

# ── README writer ─────────────────────────────────────────────────────────────

def update_readme(table: str) -> None:
    with open(README, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        re.escape(START_TAG) + r".*?" + re.escape(END_TAG), re.DOTALL
    )
    if not pattern.search(content):
        print("⚠  Markers not found in README — skipping.")
        return

    updated = pattern.sub(f"{START_TAG}\n{table}{END_TAG}", content)
    with open(README, "w", encoding="utf-8") as f:
        f.write(updated)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("📖  Reading existing rows …")
    with open(README, "r", encoding="utf-8") as f:
        current = f.read()
    existing = parse_existing_rows(current)
    print(f"    Preserved {len(existing)} existing row(s)")

    print("🔍  Fetching contributions (all 4 types) …")
    contribs = fetch_all_contributions()
    print(f"    Found activity in {len(contribs)} external repo(s)")

    table = build_table(contribs, existing)
    update_readme(table)
    print("✅  README updated — manual rows kept, dynamic rows refreshed.")
