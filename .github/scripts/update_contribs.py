"""
update_contribs.py
──────────────────
Fetches all merged PRs by thedigitalbeni to repos outside their own account,
then rewrites the README.md section between the OPEN_SOURCE_START / OPEN_SOURCE_END
markers with a clean table — one row per repo, sorted by number of merged PRs.

Place this file at: .github/scripts/update_contribs.py
"""

import os
import json
import re
import urllib.request
import urllib.error

USERNAME  = "thedigitalbeni"
README    = "README.md"
START_TAG = "<!-- OPEN_SOURCE_START -->"
END_TAG   = "<!-- OPEN_SOURCE_END -->"

def gh_get(path: str) -> dict:
    token = os.environ.get("GH_TOKEN", "")
    url   = f"https://api.github.com{path}"
    req   = urllib.request.Request(url)
    req.add_header("Accept",        "application/vnd.github.v3+json")
    req.add_header("User-Agent",    "readme-contrib-updater")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def fetch_merged_prs() -> dict[str, int]:
    """Return {full_repo_name: merged_pr_count} for external repos."""
    repos: dict[str, int] = {}
    page = 1
    while True:
        query = (
            f"is:pr+is:merged+author:{USERNAME}"
            f"+-user:{USERNAME}"          # exclude user's own repos
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

def build_table(repos: dict[str, int]) -> str:
    header = (
        "| Organization | Repository | Status |\n"
        "|:---:|:---:|:---:|\n"
    )
    if not repos:
        rows = "| — | No external contributions found yet | — |\n"
    else:
        rows = ""
        for full_name, count in sorted(repos.items(), key=lambda x: -x[1]):
            org, repo = full_name.split("/", 1)
            label     = f"{count} PR{'s' if count != 1 else ''} merged"
            rows += (
                f"| `@{org}` "
                f"| [{repo}](https://github.com/{full_name}) "
                f"| ✅ {label} |\n"
            )
    return header + rows

def update_readme(table: str) -> None:
    with open(README, "r", encoding="utf-8") as f:
        content = f.read()

    block   = f"{START_TAG}\n{table}{END_TAG}"
    pattern = re.compile(
        re.escape(START_TAG) + r".*?" + re.escape(END_TAG),
        re.DOTALL,
    )
    if not pattern.search(content):
        print("⚠️  Markers not found in README — skipping update.")
        return

    updated = pattern.sub(block, content)
    with open(README, "w", encoding="utf-8") as f:
        f.write(updated)

if __name__ == "__main__":
    print("🔍  Fetching merged PRs …")
    repos = fetch_merged_prs()
    print(f"✅  Found {len(repos)} external repo(s): {list(repos.keys())}")
    table = build_table(repos)
    update_readme(table)
    print("📝  README updated.")
