import logging
from typing import Optional

import httpx

from schema.evidence import GitHubEvent
from .base import NonRetryableError, RetryableError, get_http_client
from backend.config import has_github, GITHUB_TOKEN, GITHUB_BASE_URL, repo_for_service

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PagerPilot/1.0",
    }


async def get_recent_deploys(service: str, window: str = "24h") -> list[GitHubEvent]:
    if not service:
        raise NonRetryableError("service is required")
    if not has_github():
        logger.warning(f"GitHub not configured, returning empty deploys for {service}")
        return []

    repo = repo_for_service(service)
    client = await get_http_client()
    url = f"{GITHUB_BASE_URL}/repos/{repo}/deployments"

    params = {
        "per_page": 10,
        "sort": "created_at",
        "direction": "desc",
    }

    resp = await client.get(url, headers=_headers(), params=params)
    if resp.status_code == 403:
        raise NonRetryableError(f"GitHub auth failed: {resp.text}")
    if resp.status_code == 404:
        logger.warning(f"Repo {repo} not found")
        return []
    if resp.status_code == 429:
        raise RetryableError(f"GitHub rate limited: {resp.text}")
    resp.raise_for_status()

    deployments = resp.json()
    events: list[GitHubEvent] = []

    for dep in deployments:
        sha = dep.get("sha", "")
        created_at = dep.get("created_at", "")
        description = dep.get("description") or ""
        environment = dep.get("environment", "production")

        creator = dep.get("creator", {}) or {}
        author = creator.get("login", "deploy-bot")

        events.append(GitHubEvent(
            type="deploy",
            repo=repo,
            title=f"Deploy to {environment}: {description}" if description else f"Deploy to {environment}",
            author=author,
            timestamp=created_at,
            sha=sha,
            description=description,
        ))

    return events


async def get_prs_and_commits(service: str, window: str = "72h") -> list[GitHubEvent]:
    if not service:
        raise NonRetryableError("service is required")
    if not has_github():
        logger.warning(f"GitHub not configured, returning empty events for {service}")
        return []

    repo = repo_for_service(service)
    client = await get_http_client()
    events: list[GitHubEvent] = []

    prs = await _fetch_recent_prs(client, repo)
    events.extend(prs)

    commits = await _fetch_recent_commits(client, repo)
    events.extend(commits)

    return events


async def _fetch_recent_prs(client: httpx.AsyncClient, repo: str) -> list[GitHubEvent]:
    url = f"{GITHUB_BASE_URL}/repos/{repo}/pulls"
    params = {
        "state": "all",
        "sort": "updated",
        "direction": "desc",
        "per_page": 10,
    }

    resp = await client.get(url, headers=_headers(), params=params)
    if resp.status_code != 200:
        logger.warning(f"Failed to fetch PRs for {repo}: {resp.status_code}")
        return []

    prs = resp.json()
    events: list[GitHubEvent] = []

    for pr in prs:
        user = pr.get("user", {}) or {}
        author = user.get("login", "unknown")
        title = pr.get("title", "")
        pr_number = pr.get("number", 0)
        updated_at = pr.get("updated_at", "")
        body = pr.get("body") or ""

        events.append(GitHubEvent(
            type="pr",
            repo=repo,
            title=title,
            author=author,
            timestamp=updated_at,
            sha=pr.get("head", {}).get("sha", "") if pr.get("head") else "",
            pr_number=pr_number,
            description=body[:500] if body else "",
        ))

    return events


async def _fetch_recent_commits(client: httpx.AsyncClient, repo: str) -> list[GitHubEvent]:
    url = f"{GITHUB_BASE_URL}/repos/{repo}/commits"
    params = {
        "per_page": 10,
        "sort": "committer-date",
        "direction": "desc",
    }

    resp = await client.get(url, headers=_headers(), params=params)
    if resp.status_code != 200:
        logger.warning(f"Failed to fetch commits for {repo}: {resp.status_code}")
        return []

    commits = resp.json()
    events: list[GitHubEvent] = []

    for commit in commits:
        commit_data = commit.get("commit", {}) or {}
        author_data = commit_data.get("author", {}) or {}
        author = author_data.get("name", "unknown")
        message = commit_data.get("message", "").split("\n")[0]
        sha = commit.get("sha", "")
        timestamp = author_data.get("date", "")

        events.append(GitHubEvent(
            type="commit",
            repo=repo,
            title=message[:100],
            author=author,
            timestamp=timestamp,
            sha=sha,
            description=commit_data.get("message", "")[:500],
        ))

    return events
