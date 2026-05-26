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

def build_table(repos: dict[str, int]) -> str:
    header = (
        "| Organization | Repository | Status |\n"
        "|:---:|:---:|:---:|\n"
    )
    if not repos:
        return header + "| — | No external contributions found yet | — |\n"

    rows = ""
    for full_name, count in sorted(repos.items(), key=sort_key):
        org, repo = full_name.split("/", 1)
        rows += (
            f"| `@{org}` "
            f"| [{repo}](https://github.com/{full_name}) "
            f"| {status_label(count)} |\n"
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
        print("Markers not found in README — skipping.")
        return

    updated = pattern.sub(block, content)
    with open(README, "w", encoding="utf-8") as f:
        f.write(updated)

if __name__ == "__main__":
    print("Fetching merged PRs …")
    repos = fetch_merged_prs()
    print(f"Found {len(repos)} repo(s): {list(repos.keys())}")
    table = build_table(repos)
    update_readme(table)
    print("README updated.")
