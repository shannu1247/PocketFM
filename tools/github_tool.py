"""
GitHub tool — fetch issue details, comments, and related PRs via GitHub REST API.
No dependencies beyond stdlib. Uses token if provided, works without for public repos.
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GitHubIssue:
    number: int
    title: str
    body: str
    state: str
    labels: List[str]
    comments: List[str]
    repo_owner: str
    repo_name: str
    url: str
    linked_prs: List[dict] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        parts = [
            f"Issue #{self.number}: {self.title}",
            f"Labels: {', '.join(self.labels) or 'none'}",
            "",
            "== Description ==",
            self.body or "(no description)",
        ]
        if self.comments:
            parts.append("\n== Comments ==")
            for i, c in enumerate(self.comments, 1):
                parts.append(f"[Comment {i}]\n{c}")
        return "\n".join(parts)


def parse_issue_url(url: str):
    """Parse https://github.com/owner/repo/issues/123 → (owner, repo, number)"""
    url = url.rstrip("/")
    parts = url.replace("https://github.com/", "").split("/")
    if len(parts) < 4 or parts[2] != "issues":
        raise ValueError(f"Invalid GitHub issue URL: {url}")
    return parts[0], parts[1], int(parts[3])


class GitHubTool:
    BASE = "https://api.github.com"

    def __init__(self, token: str = ""):
        self.token = token

    def _get(self, path: str) -> dict | list:
        url = f"{self.BASE}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-go-contributor/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"GitHub API error {e.code} for {url}: {body}")

    def fetch_issue(self, owner: str, repo: str, number: int) -> GitHubIssue:
        print(f"   📥 Fetching issue #{number} from {owner}/{repo}...")

        issue_data = self._get(f"/repos/{owner}/{repo}/issues/{number}")
        labels = [l["name"] for l in issue_data.get("labels", [])]

        # Fetch comments
        comments_data = self._get(f"/repos/{owner}/{repo}/issues/{number}/comments")
        comments = [c["body"] for c in comments_data if c.get("body")]

        # Try to find linked PRs (search for PRs mentioning this issue)
        linked_prs = []
        try:
            prs = self._get(f"/repos/{owner}/{repo}/pulls?state=all&per_page=20")
            for pr in prs:
                body = (pr.get("body") or "").lower()
                if f"#{number}" in body or f"fixes #{number}" in body or f"closes #{number}" in body:
                    linked_prs.append({
                        "number": pr["number"],
                        "title": pr["title"],
                        "url": pr["html_url"],
                        "state": pr["state"],
                    })
        except Exception:
            pass  # Linked PRs are best-effort

        return GitHubIssue(
            number=number,
            title=issue_data["title"],
            body=issue_data.get("body") or "",
            state=issue_data["state"],
            labels=labels,
            comments=comments,
            repo_owner=owner,
            repo_name=repo,
            url=issue_data["html_url"],
            linked_prs=linked_prs,
        )

    def fetch_issue_from_url(self, url: str) -> GitHubIssue:
        owner, repo, number = parse_issue_url(url)
        return self.fetch_issue(owner, repo, number)

    def get_repo_default_branch(self, owner: str, repo: str) -> str:
        data = self._get(f"/repos/{owner}/{repo}")
        return data.get("default_branch", "main")
