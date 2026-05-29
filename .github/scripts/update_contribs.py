"""
update_contribs.py
──────────────────
Fetches all merged PRs by the user to external repos, sorts well-known
organizations to the top, and writes the result between the README markers.

Place this file at: .github/scripts/update_contribs.py
"""

import os
import json
import re
import urllib.request

USERNAME  = "thedigitalbeni"
README    = "README.md"
START_TAG = "<!-- OPEN_SOURCE_START -->"
END_TAG   = "<!-- OPEN_SOURCE_END -->"

# Known major orgs — these always float to the top regardless of PR count
MAJOR_ORGS = {
    "google", "google-gemini", "google-deepmind", "googlecodelabs",
    "microsoft", "azure", "dotnet",
    "meta", "facebookresearch", "pytorch",
    "openai", "anthropics",
    "apple",
    "amazon", "aws", "awslabs",
    "vercel", "nextjs",
    "nodejs", "npm",
    "docker",
    "kubernetes", "helm",
    "facebook", "instagram",
    "twitter", "twitterdev",
    "github", "actions",
    "mozilla",
    "apache",
    "linux", "torvalds",
    "rust-lang",
    "golang",
    "python",
}

def gh_get(path: str) -> dict:
    token = os.environ.get("GH_TOKEN", "")
    url   = f"https://api.github.com{path}"
    req   = urllib.request.Request(url)
    req.add_header("Accept",     "application/vnd.github.v3+json")
    req.add_header("User-Agent", "readme-contrib-updater")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def fetch_merged_prs() -> dict[str, int]:
    """Return {full_repo_name: merged_pr_count} for all external repos."""
    repos: dict[str, int] = {}
    page = 1
    while True:
        query = (
            f"is:pr+is:merged+author:{USERNAME}"
            f"+-user:{USERNAME}"
            f"&per_page=100&page={page}"
        )
        data  = gh_get(f"/search/issues?q={query}")
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

def status_label(count: int) -> str:
    if count == 1:
        return "✅ 1 PR merged"
    return f"✅ {count} PRs merged"

def sort_key(item: tuple[str, int]) -> tuple[int, int]:
    full_name, count = item
    org = full_name.split("/")[0].lower()
    is_major = 0 if org in MAJOR_ORGS else 1   # major orgs sort first
    return (is_major, -count)                   # then by PR count descending

SCRIPT_STATUS_RE = re.compile(r"✅ \d+ PRs? merged")

def parse_existing_rows(content: str) -> list[str]:
    """Extract existing HTML table rows from between the markers."""
    pattern = re.compile(
        re.escape(START_TAG) + r".*?" + re.escape(END_TAG),
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return []
    block = match.group()
    return re.findall(r"<tr>.*?</tr>", block, re.DOTALL)

def is_script_managed(row: str) -> bool:
    """Rows with '✅ X PR(s) merged' were added by this script — safe to update."""
    return bool(SCRIPT_STATUS_RE.search(row))

def row_has_repo(row: str, full_name: str) -> bool:
    repo_part = full_name.split("/", 1)[1]
    return repo_part.lower() in row.lower()

def build_table(dynamic: dict[str, int], existing_rows: list[str]) -> str:
    header = (
        "<table>\n"
        "<thead><tr><th>Organization</th><th>Repository</th><th>Status</th></tr></thead>\n"
        "<tbody>\n"
    )
    footer = "</tbody>\n</table>\n"

    rows = ""

    # 1. Keep all manually-added rows untouched (custom status, e.g. gemini-cli)
    for row in existing_rows:
        if not is_script_managed(row):
            rows += row + "\n"

    # 2. Script-managed rows: update count if repo found in API, keep if not
    for row in existing_rows:
        if not is_script_managed(row):
            continue
        # Find which repo this row belongs to
        matched_repo = next(
            (fn for fn in dynamic if row_has_repo(row, fn)), None
        )
        if matched_repo:
            # Update with fresh count
            org, repo = matched_repo.split("/", 1)
            count = dynamic[matched_repo]
            rows += (
                f"<tr><td><code>@{org}</code></td>"
                f"<td><a href=\"https://github.com/{matched_repo}\">{repo}</a></td>"
                f"<td>{status_label(count)}</td></tr>\n"
            )
        else:
            # Repo not in API results this run — keep existing row as-is
            rows += row + "\n"

    # 3. Add brand new repos not yet in the table at all
    for full_name, count in sorted(dynamic.items(), key=sort_key):
        already_there = any(row_has_repo(r, full_name) for r in existing_rows)
        if already_there:
            continue
        org, repo = full_name.split("/", 1)
        rows += (
            f"<tr><td><code>@{org}</code></td>"
            f"<td><a href=\"https://github.com/{full_name}\">{repo}</a></td>"
            f"<td>{status_label(count)}</td></tr>\n"
        )

    if not rows.strip():
        rows = "<tr><td>—</td><td>No external contributions found yet</td><td>—</td></tr>\n"

    return header + rows + footer

def update_readme(table: str) -> None:
    with open(README, "r", encoding="utf-8") as f:
        content = f.read()

    block   = f"{START_TAG}\n{table}{END_TAG}"
    pattern = re.compile(
        re.escape(START_TAG) + r".*?" + re.escape(END_TAG),
        re.DOTALL,
    )
    if not pattern.search(content):
        print("Markers not found in README — skipping.")
        return

    updated = pattern.sub(block, content)
    with open(README, "w", encoding="utf-8") as f:
        f.write(updated)

if __name__ == "__main__":
    print("Reading existing rows …")
    with open(README, "r", encoding="utf-8") as f:
        current = f.read()
    existing = parse_existing_rows(current)
    print(f"Found {len(existing)} existing row(s) — these will be preserved.")

    print("Fetching merged PRs …")
    repos = fetch_merged_prs()
    print(f"Found {len(repos)} external repo(s): {list(repos.keys())}")

    table = build_table(repos, existing)
    update_readme(table)
    print("README updated — existing rows kept, new ones added.")
