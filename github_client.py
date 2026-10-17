"""
GitHub REST API client supporting github.com and GitHub Enterprise with
automatic pagination, exponential backoff retries, and token security.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, List, Optional
import urllib.parse

import requests

from models import CommitInfo, PRInfo
from utils import mask_token


logger = logging.getLogger("git_audit.github_client")


class GitHubAPIError(Exception):
    """Custom exception raised for unrecoverable GitHub API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_text: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class GitHubClient:
    """Client for interacting with GitHub REST API."""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url: str = "github.com",
        token: Optional[str] = None,
        max_retries: int = 5,
        backoff_factor: float = 1.5,
        timeout_seconds: int = 30,
    ) -> None:
        self.raw_base_url = base_url.strip()
        self.api_base_url = self._resolve_api_url(self.raw_base_url)
        self.token = token.strip() if token else ""
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout_seconds = timeout_seconds

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "User-Agent": "git-audit-tool/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
            logger.info("GitHub client initialized with token: %s", mask_token(self.token))
        else:
            logger.warning("GitHub client initialized without authentication token (rate limits will be strictly restricted).")

    @staticmethod
    def _resolve_api_url(base_url: str) -> str:
        """Resolve API root from domain or URL string."""
        url = base_url
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"

        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()

        if netloc in ("github.com", "api.github.com"):
            return "https://api.github.com"
        # GitHub Enterprise Server standard endpoint
        if parsed.path and parsed.path.rstrip("/").endswith("/api/v3"):
            return f"https://{netloc}{parsed.path.rstrip('/')}"
        return f"https://{netloc}/api/v3"

    def _request_with_retry(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        """Execute HTTP request with exponential backoff on transient errors and 429."""
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            url = endpoint
        else:
            url = f"{self.api_base_url}/{endpoint.lstrip('/')}"

        attempt = 0
        kwargs.setdefault("timeout", self.timeout_seconds)

        while True:
            attempt += 1
            try:
                logger.debug("GitHub API [%s] %s (Attempt %d/%d)", method, url, attempt, self.max_retries)
                response = self.session.request(method, url, **kwargs)

                if response.status_code in self.RETRYABLE_STATUS_CODES:
                    if attempt >= self.max_retries:
                        logger.error(
                            "GitHub API [%s] %s failed with status %d after %d retries.",
                            method, url, response.status_code, attempt,
                        )
                        raise GitHubAPIError(
                            f"GitHub API returned {response.status_code} after {attempt} attempts",
                            status_code=response.status_code,
                            response_text=response.text,
                        )

                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_time = int(retry_after)
                    else:
                        sleep_time = self.backoff_factor * (2 ** (attempt - 1))

                    logger.warning(
                        "GitHub API [%s] %s returned %d. Retrying in %.2f seconds (Attempt %d)...",
                        method, url, response.status_code, sleep_time, attempt,
                    )
                    time.sleep(sleep_time)
                    continue

                return response

            except (requests.ConnectionError, requests.Timeout) as ex:
                if attempt >= self.max_retries:
                    logger.error("GitHub API [%s] %s connection error: %s", method, url, ex)
                    raise GitHubAPIError(f"GitHub connection error: {ex}") from ex

                sleep_time = self.backoff_factor * (2 ** (attempt - 1))
                logger.warning(
                    "Network error during GitHub API [%s] %s: %s. Retrying in %.2f seconds...",
                    method, url, ex, sleep_time,
                )
                time.sleep(sleep_time)

    def _paginate(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Paginate through all available items by following GitHub Link headers."""
        all_items: List[Dict[str, Any]] = []
        request_params = dict(params or {})
        request_params.setdefault("per_page", 100)

        next_url: Optional[str] = endpoint
        while next_url:
            resp = self._request_with_retry("GET", next_url, params=request_params if next_url == endpoint else None)
            if resp.status_code != 200:
                raise GitHubAPIError(
                    f"Failed to fetch {next_url}: HTTP {resp.status_code} - {resp.text}",
                    status_code=resp.status_code,
                    response_text=resp.text,
                )

            data = resp.json()
            if isinstance(data, list):
                all_items.extend(data)
            elif isinstance(data, dict) and "items" in data:
                all_items.extend(data["items"])
            else:
                logger.debug("Unrecognized paginated response structure: %s", type(data))
                break

            # Follow Link header
            next_url = None
            link_header = resp.headers.get("Link", "")
            if link_header:
                links = requests.utils.parse_header_links(link_header)
                for link in links:
                    if link.get("rel") == "next":
                        next_url = link.get("url")
                        break

        return all_items

    def test_connection(self) -> Dict[str, Any]:
        """Validate token and connection by querying authenticated user or API root."""
        if self.token:
            resp = self._request_with_retry("GET", "user")
        else:
            resp = self._request_with_retry("GET", "zen")
        if resp.status_code not in (200, 204):
            raise GitHubAPIError(f"Connection test failed: HTTP {resp.status_code} {resp.text}", status_code=resp.status_code)
        return resp.json() if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/json") else {}

    def list_org_repositories(self, org: str) -> List[Dict[str, Any]]:
        """List all repositories belonging to an organization."""
        logger.info("Fetching repositories for organization: %s", org)
        return self._paginate(f"orgs/{org}/repos", {"type": "all", "sort": "full_name"})

    def list_repository_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        base: Optional[str] = None,
        sort: str = "created",
        direction: str = "desc",
    ) -> List[Dict[str, Any]]:
        """List pull requests for a repository."""
        params: Dict[str, Any] = {
            "state": state,
            "sort": sort,
            "direction": direction,
        }
        if base:
            params["base"] = base
        logger.debug("Listing PRs for %s/%s (state=%s, base=%s)", owner, repo, state, base)
        return self._paginate(f"repos/{owner}/{repo}/pulls", params)

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> Dict[str, Any]:
        """Fetch full pull request metadata."""
        resp = self._request_with_retry("GET", f"repos/{owner}/{repo}/pulls/{pull_number}")
        if resp.status_code != 200:
            raise GitHubAPIError(f"Failed to get PR #{pull_number}: {resp.status_code} {resp.text}", status_code=resp.status_code)
        return resp.json()

    def list_pull_request_commits(self, owner: str, repo: str, pull_number: int) -> List[CommitInfo]:
        """Fetch list of commits included in a pull request."""
        logger.debug("Fetching commits for PR #%d in %s/%s", pull_number, owner, repo)
        raw_commits = self._paginate(f"repos/{owner}/{repo}/pulls/{pull_number}/commits")
        commit_infos: List[CommitInfo] = []
        for c in raw_commits:
            sha = c.get("sha", "")
            commit_dict = c.get("commit", {})
            author_dict = commit_dict.get("author", {}) or {}
            gh_author = c.get("author") or {}

            name = author_dict.get("name", "")
            email = author_dict.get("email", "")
            login = gh_author.get("login", "") or name
            msg = commit_dict.get("message", "")
            dt = author_dict.get("date", "")

            commit_infos.append(CommitInfo(
                sha=sha,
                author_name=name,
                author_email=email,
                author_login=login,
                message=msg,
                date=dt,
            ))
        return commit_infos

    def list_pull_request_files(self, owner: str, repo: str, pull_number: int) -> List[str]:
        """Fetch list of changed filenames in a pull request."""
        logger.debug("Fetching changed files for PR #%d in %s/%s", pull_number, owner, repo)
        raw_files = self._paginate(f"repos/{owner}/{repo}/pulls/{pull_number}/files")
        return [f.get("filename", "") for f in raw_files if f.get("filename")]

    def get_file_content_at_ref(self, owner: str, repo: str, path: str, ref: str) -> Optional[str]:
        """
        Fetch file contents at a specific git ref (branch, tag, or SHA).
        Returns None if file does not exist (404).
        """
        logger.debug("Fetching file '%s' at ref '%s' from %s/%s", path, ref, owner, repo)
        encoded_path = urllib.parse.quote(path.lstrip("/"))
        url = f"repos/{owner}/{repo}/contents/{encoded_path}?ref={urllib.parse.quote(ref)}"
        resp = self._request_with_retry("GET", url)

        if resp.status_code == 404:
            logger.debug("File '%s' not found at ref '%s' in %s/%s", path, ref, owner, repo)
            return None

        if resp.status_code != 200:
            raise GitHubAPIError(
                f"Error fetching '{path}' at '{ref}': HTTP {resp.status_code} {resp.text}",
                status_code=resp.status_code,
            )

        data = resp.json()
        encoding = data.get("encoding", "")
        content = data.get("content", "")

        if encoding == "base64" and content:
            try:
                decoded_bytes = base64.b64decode(content)
                return decoded_bytes.decode("utf-8", errors="replace")
            except Exception as ex:
                logger.warning("Error decoding base64 content for %s at %s: %s", path, ref, ex)
                return None

        # If file is too large or raw blob returned
        download_url = data.get("download_url")
        if download_url:
            raw_resp = self._request_with_retry("GET", download_url)
            if raw_resp.status_code == 200:
                return raw_resp.text

        return None

    def list_repo_contributors(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        """List contributors for a repository."""
        logger.debug("Listing contributors for %s/%s", owner, repo)
        return self._paginate(f"repos/{owner}/{repo}/contributors")

    def list_repo_commits(
        self,
        owner: str,
        repo: str,
        since: Optional[str] = None,
        author: Optional[str] = None,
        sha: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List repository commits with optional time window or author filter."""
        params: Dict[str, Any] = {}
        if since:
            params["since"] = since
        if author:
            params["author"] = author
        if sha:
            params["sha"] = sha
        return self._paginate(f"repos/{owner}/{repo}/commits", params)

    def get_branch_head_sha(self, owner: str, repo: str, branch: str) -> Optional[str]:
        """Fetch the commit SHA of the HEAD of a branch."""
        resp = self._request_with_retry("GET", f"repos/{owner}/{repo}/branches/{urllib.parse.quote(branch)}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise GitHubAPIError(f"Failed to query branch {branch}: HTTP {resp.status_code}", status_code=resp.status_code)
        data = resp.json()
        return data.get("commit", {}).get("sha")
