"""
Repository discovery implementations for local, github_org, and github_contributor modes.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging
import os
from pathlib import Path
from typing import List, Optional

from git_client import GitClient
from github_client import GitHubClient
from models import AuditConfig, ContributorHistoryScope, DiscoveryMode, RepoTarget
from utils import matches_any_filter


logger = logging.getLogger("git_audit.repo_discovery")


class RepositoryDiscovery:
    """Discovers repositories based on configured mode and filtering rules."""

    def __init__(self, config: AuditConfig, github_client: Optional[GitHubClient] = None) -> None:
        self.config = config
        self.github_client = github_client

    def discover_repositories(self) -> List[RepoTarget]:
        """Entry point: Dispatches to the appropriate discovery mode."""
        mode = self.config.repository_discovery_mode
        logger.info("Starting repository discovery in mode: %s", mode.value)

        if mode == DiscoveryMode.LOCAL:
            return self._discover_local()
        elif mode == DiscoveryMode.GITHUB_ORG:
            return self._discover_github_org()
        elif mode == DiscoveryMode.GITHUB_CONTRIBUTOR:
            return self._discover_github_contributor()
        else:
            raise ValueError(f"Unsupported repository discovery mode: {mode}")

    def _discover_local(self) -> List[RepoTarget]:
        """Recursively scan root_folder to locate all local Git repositories."""
        root = Path(self.config.root_folder)
        logger.info("Scanning local directory for Git repositories: %s", root)

        if not root.exists():
            logger.warning("Local root folder does not exist: %s", root)
            return []

        discovered: List[RepoTarget] = []
        seen_paths = set()

        for dirpath, dirnames, filenames in os.walk(root):
            path_obj = Path(dirpath)
            # If current directory is a git repo directory
            if (path_obj / ".git").exists() or (path_obj / "HEAD").exists() and (path_obj / "objects").exists():
                resolved = path_obj.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)

                # Prune subdirectories so os.walk does not dive into this repo's internals
                dirnames.clear()

                git = GitClient(resolved)
                remote_url = git.get_remote_url() or ""
                owner, repo_name = GitClient.parse_github_owner_repo(remote_url)

                if not repo_name:
                    repo_name = resolved.name
                if not owner:
                    owner = self.config.github_organization if self.config.github_organization != "CHANGE_ME" else "local"

                # Apply repository name filters if specified
                if self.config.repository_name_filters:
                    if not matches_any_filter(repo_name, self.config.repository_name_filters):
                        logger.debug("Local repo '%s' filtered out by repository_name_filters", repo_name)
                        continue

                target = RepoTarget(
                    name=repo_name,
                    owner=owner,
                    full_name=f"{owner}/{repo_name}",
                    local_path=resolved,
                    clone_url=remote_url,
                )
                logger.info("Discovered local repository: %s (Path: %s)", target.full_name, resolved)
                discovered.append(target)

        logger.info("Total local repositories discovered: %d", len(discovered))
        return discovered

    def _discover_github_org(self) -> List[RepoTarget]:
        """Discover repositories belonging to the specified GitHub organization."""
        org = self.config.github_organization.strip()
        if not org or org == "CHANGE_ME":
            logger.error("Cannot run github_org discovery: github_organization is not configured (current: '%s').", org)
            return []

        if not self.github_client:
            logger.error("GitHub client is required for github_org discovery mode.")
            return []

        logger.info("Querying GitHub organization repositories for '%s'...", org)
        raw_repos = self.github_client.list_org_repositories(org)
        discovered: List[RepoTarget] = []

        for repo in raw_repos:
            repo_name = repo.get("name", "")
            full_name = repo.get("full_name", f"{org}/{repo_name}")
            owner_login = repo.get("owner", {}).get("login", org)
            clone_url = repo.get("clone_url", "")
            default_branch = repo.get("default_branch", "main")

            # Apply repository_name_filters
            if self.config.repository_name_filters:
                if not matches_any_filter(repo_name, self.config.repository_name_filters):
                    logger.debug("Org repo '%s' filtered out by repository_name_filters", repo_name)
                    continue

            target = RepoTarget(
                name=repo_name,
                owner=owner_login,
                full_name=full_name,
                local_path=None,
                clone_url=clone_url,
                default_branch=default_branch,
            )
            logger.info("Discovered GitHub Org repository: %s", full_name)
            discovered.append(target)

        logger.info("Total github_org repositories discovered: %d", len(discovered))
        return discovered

    def _discover_github_contributor(self) -> List[RepoTarget]:
        """
        Discover repositories where contributor matches repository_contributor_filters
        within the configured repository_contributor_history_scope.
        """
        org = self.config.github_organization.strip()
        if not org or org == "CHANGE_ME":
            logger.error("Cannot run github_contributor discovery: github_organization is not configured.")
            return []

        if not self.github_client:
            logger.error("GitHub client is required for github_contributor discovery mode.")
            return []

        filters = self.config.repository_contributor_filters
        scope = self.config.repository_contributor_history_scope
        days = self.config.days

        logger.info(
            "Discovering repos by contributor in org '%s' (Filters: %s, Scope: %s, Days: %d)",
            org, filters, scope.value, days,
        )

        all_org_repos = self.github_client.list_org_repositories(org)
        discovered: List[RepoTarget] = []

        cutoff_iso: Optional[str] = None
        if scope == ContributorHistoryScope.LOOKBACK:
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_iso = cutoff_dt.isoformat()

        for repo in all_org_repos:
            repo_name = repo.get("name", "")
            owner_login = repo.get("owner", {}).get("login", org)
            full_name = repo.get("full_name", f"{owner_login}/{repo_name}")
            default_branch = repo.get("default_branch", "main")

            # Optional name filter
            if self.config.repository_name_filters:
                if not matches_any_filter(repo_name, self.config.repository_name_filters):
                    continue

            contributor_matched = False

            if scope == ContributorHistoryScope.LOOKBACK:
                # Check commits in the lookback window
                try:
                    commits = self.github_client.list_repo_commits(
                        owner=owner_login,
                        repo=repo_name,
                        since=cutoff_iso,
                    )
                    for c in commits:
                        author_data = c.get("author") or {}
                        commit_author = c.get("commit", {}).get("author", {}) or {}
                        login = author_data.get("login", "")
                        name = commit_author.get("name", "")
                        email = commit_author.get("email", "")

                        if (
                            matches_any_filter(login, filters)
                            or matches_any_filter(name, filters)
                            or matches_any_filter(email, filters)
                        ):
                            contributor_matched = True
                            logger.info("Repo %s matched contributor '%s'/'%s' in lookback window", full_name, login, name)
                            break
                except Exception as ex:
                    logger.warning("Error fetching lookback commits for %s: %s", full_name, ex)

            else:  # ALL_HISTORY
                try:
                    contributors = self.github_client.list_repo_contributors(owner=owner_login, repo=repo_name)
                    for contrib in contributors:
                        login = contrib.get("login", "")
                        if matches_any_filter(login, filters):
                            contributor_matched = True
                            logger.info("Repo %s matched contributor '%s' in all_history", full_name, login)
                            break
                except Exception as ex:
                    logger.warning("Error fetching contributors for %s: %s", full_name, ex)

            if contributor_matched:
                target = RepoTarget(
                    name=repo_name,
                    owner=owner_login,
                    full_name=full_name,
                    local_path=None,
                    clone_url=repo.get("clone_url", ""),
                    default_branch=default_branch,
                )
                discovered.append(target)

        logger.info("Total contributor-matched repositories discovered: %d", len(discovered))
        return discovered
