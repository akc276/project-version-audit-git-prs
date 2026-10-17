"""
git-audit-tool: Main entry point and orchestration engine.
Audits GitHub Pull Requests and local repositories for project.properties version progression,
contributor metrics, and Jira traceability with real-time CSV and XLSX streaming.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
import yaml

from git_client import GitClient
from github_client import GitHubClient, GitHubAPIError
from jira_parser import JiraParser
from models import (
    AuditConfig,
    AuditRecord,
    AuditStatus,
    AuthorMatchingMode,
    AuthorMatchTarget,
    ContributorCountMode,
    ContributorHistoryScope,
    DiscoveryMode,
    PRInfo,
    PRLookupMode,
    PRStateFilter,
    PropertyMatchMode,
    RepoTarget,
    VersionCheckMode,
    VersionSourceInPR,
)
from repo_discovery import RepositoryDiscovery
from report_writer import ReportWriter
from utils import (
    is_within_days,
    mask_token,
    matches_any_filter,
    setup_logging,
)


logger = logging.getLogger("git_audit")


class GitAuditOrchestrator:
    """Coordinates repository discovery, PR inspection, version analysis, and reporting."""

    def __init__(self, config: AuditConfig) -> None:
        self.config = config
        self.github_client: Optional[GitHubClient] = None
        self.report_writer: Optional[ReportWriter] = None

        # Statistics counters
        self.repositories_scanned = 0
        self.prs_analyzed = 0
        self.pass_count = 0
        self.review_count = 0
        self.error_count = 0

    def initialize(self) -> None:
        """Initialize GitHub client and report writers."""
        logger.info("Initializing Git Audit Tool...")
        if self.config.github_token:
            logger.info("Loaded GitHub token from env '%s': %s", self.config.github_token_env, mask_token(self.config.github_token))
        else:
            logger.warning("No GitHub token discovered under environment variable '%s'", self.config.github_token_env)

        # Initialize GitHub Client
        self.github_client = GitHubClient(
            base_url=self.config.github_base_url,
            token=self.config.github_token,
        )

        # Initialize Report Writer
        self.report_writer = ReportWriter(
            csv_path=self.config.csv_report,
            xlsx_path=self.config.xlsx_report,
            progress_path=self.config.progress_file,
            realtime_save=self.config.xlsx_realtime_save,
            status_colors=self.config.xlsx_status_colors,
        )

    def run(self) -> int:
        """Execute full audit workflow and print summary."""
        start_time = time.time()
        self.initialize()

        logger.info("==================================================")
        logger.info("STARTING GIT AUDIT")
        logger.info("Repository Discovery Mode: %s", self.config.repository_discovery_mode.value)
        logger.info("Author Filters: %s", self.config.author_filters)
        logger.info("Target Branches: %s", self.config.branches)
        logger.info("Lookback Days: %d", self.config.days)
        logger.info("Version Check Mode: %s", self.config.version_check_mode.value)
        logger.info("==================================================")

        try:
            # 1. Discover Repositories
            discovery = RepositoryDiscovery(self.config, self.github_client)
            repositories = discovery.discover_repositories()
            self.repositories_scanned = len(repositories)

            if not repositories:
                logger.warning("No repositories found matching discovery configuration.")
                if self.report_writer:
                    self.report_writer.update_status_message("Scan finished: 0 repositories discovered.")
                self._print_summary(time.time() - start_time)
                return 0

            # 2. Parallel Asynchronous Pre-fetch across local repositories
            self._prefetch_repositories_parallel(repositories)

            # 3. Process each repository
            for repo in repositories:
                self._audit_repository(repo)

        except Exception as ex:
            logger.error("Fatal audit execution error: %s", ex, exc_info=True)
            self.error_count += 1
            return 1
        finally:
            if self.report_writer:
                self.report_writer.close()

        duration = time.time() - start_time
        self._print_summary(duration)
        return 0 if self.error_count == 0 else 1

    def _prefetch_repositories_parallel(self, repositories: List[RepoTarget]) -> None:
        """Fetches all local repositories in parallel using background worker threads."""
        if not self.config.fetch_before_scan:
            return

        local_repos = [r for r in repositories if r.local_path and Path(r.local_path).exists()]
        if not local_repos:
            return

        workers = max(1, min(len(local_repos), self.config.parallel_fetch_workers))
        logger.info("==================================================")
        logger.info(
            "Starting parallel asynchronous pre-fetch on %d local repositories (workers=%d)...",
            len(local_repos), workers,
        )
        if self.report_writer:
            self.report_writer.update_status_message(
                f"Pre-fetching {len(local_repos)} repositories in parallel..."
            )

        def _fetch_single_repo(target: RepoTarget) -> tuple[str, bool]:
            try:
                client = GitClient(target.local_path)
                success = client.fetch_all()
                return target.full_name, success
            except Exception as ex:
                logger.warning("Background fetch failed for %s: %s", target.full_name, ex)
                return target.full_name, False

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_repo = {executor.submit(_fetch_single_repo, repo): repo for repo in local_repos}
            for future in as_completed(future_to_repo):
                repo_name, success = future.result()
                logger.debug("Parallel fetch finished for %s (success=%s)", repo_name, success)

        logger.info("Completed parallel pre-fetch for all local repositories.")
        logger.info("==================================================")

    def _audit_repository(self, repo: RepoTarget) -> None:
        """Run audit checks against a single repository."""
        logger.info("--------------------------------------------------")
        logger.info("Scanning repository: %s (Path: %s)", repo.full_name, repo.local_path or "Remote")
        if self.report_writer:
            self.report_writer.update_status_message(f"Starting audit on repo: {repo.full_name}")

        git_client: Optional[GitClient] = None
        if repo.local_path and Path(repo.local_path).exists():
            git_client = GitClient(repo.local_path)

        try:
            prs = self._collect_repository_prs(repo, git_client)
            logger.info("Found %d candidate PR(s) matching branch and author criteria in %s", len(prs), repo.full_name)
            if not prs:
                logger.warning(
                    "No pull requests in %s matched author filters %s with mode '%s'. "
                    "(Tip: Use '--author-matching-mode both' to check both PR creator and commit contributors/authors)",
                    repo.full_name, self.config.author_filters, self.config.author_matching_mode.value,
                )

            from version_analyzer import VersionAnalyzer
            analyzer = VersionAnalyzer(self.config, self.github_client)

            for pr in prs:
                self._audit_pull_request(repo, pr, analyzer, git_client)

        except Exception as ex:
            logger.error("Error auditing repository %s: %s", repo.full_name, ex, exc_info=True)
            self._record_repo_error(repo, str(ex))

    def _collect_repository_prs(self, repo: RepoTarget, git_client: Optional[GitClient]) -> List[PRInfo]:
        """Fetch and filter pull requests based on branch, author, and lookup mode."""
        candidate_prs: List[PRInfo] = []

        # Strategy 1: Remote GitHub API
        if self.github_client and repo.owner and repo.name and self.config.github_organization != "CHANGE_ME":
            try:
                raw_prs = self.github_client.list_repository_pull_requests(
                    owner=repo.owner,
                    repo=repo.name,
                    state="all",
                )
                for raw in raw_prs:
                    pr_info = self._parse_github_pr(repo, raw)
                    if pr_info and self._matches_pr_criteria(pr_info):
                        # Fetch commits & changed files
                        pr_info.commits = self.github_client.list_pull_request_commits(repo.owner, repo.name, pr_info.number)
                        pr_info.changed_files = self.github_client.list_pull_request_files(repo.owner, repo.name, pr_info.number)
                        # Re-verify author matching with commits included
                        if self._matches_author(pr_info):
                            candidate_prs.append(pr_info)
            except Exception as ex:
                logger.warning("GitHub API PR fetch failed for %s: %s", repo.full_name, ex)

        # Strategy 2: Local Git merge analysis (offline fallback or local mode)
        if not candidate_prs and git_client and git_client.is_git_repo():
            local_prs = git_client.discover_local_simulated_prs(self.config.branches, self.config.days)
            for pr in local_prs:
                if self._matches_pr_criteria(pr) and self._matches_author(pr):
                    candidate_prs.append(pr)

        # Handle pr_lookup_mode == latest_pr_for_author
        if self.config.pr_lookup_mode == PRLookupMode.LATEST_PR_FOR_AUTHOR and candidate_prs:
            author_latest: Dict[str, PRInfo] = {}
            for p in candidate_prs:
                creator = p.creator_login or p.creator_name
                if creator not in author_latest:
                    author_latest[creator] = p
                else:
                    curr_dt = p.created_at or ""
                    prev_dt = author_latest[creator].created_at or ""
                    if curr_dt > prev_dt:
                        author_latest[creator] = p
            candidate_prs = list(author_latest.values())

        return candidate_prs

    def _parse_github_pr(self, repo: RepoTarget, raw: Dict[str, Any]) -> Optional[PRInfo]:
        """Parse raw GitHub API dictionary into PRInfo dataclass."""
        base_dict = raw.get("base", {})
        head_dict = raw.get("head", {})
        user_dict = raw.get("user") or {}
        merged_by_dict = raw.get("merged_by") or {}

        base_branch = base_dict.get("ref", "")
        base_sha = base_dict.get("sha", "")
        head_branch = head_dict.get("ref", "")
        head_sha = head_dict.get("sha", "")

        is_merged = raw.get("merged_at") is not None
        merged_date = raw.get("merged_at") or "NA"
        merged_by = merged_by_dict.get("login") or "NA"

        return PRInfo(
            number=raw.get("number", 0),
            title=raw.get("title", ""),
            url=raw.get("html_url", f"https://{self.config.github_base_url}/{repo.full_name}/pull/{raw.get('number')}"),
            creator_login=user_dict.get("login", ""),
            creator_name=user_dict.get("name") or user_dict.get("login", ""),
            creator_email=user_dict.get("email") or "",
            created_at=raw.get("created_at", ""),
            merged_by_login=merged_by,
            merged_at=merged_date,
            state=raw.get("state", "open"),
            base_branch=base_branch,
            base_sha=base_sha,
            head_branch=head_branch,
            head_sha=head_sha,
            is_merged=is_merged,
            body=raw.get("body") or "",
        )

    def _matches_pr_criteria(self, pr: PRInfo) -> bool:
        """Validate branch target, state filter, and date lookback."""
        # 1. Target branch filter
        if self.config.branches and pr.base_branch not in self.config.branches:
            logger.debug("PR #%d skipped: target branch '%s' not in %s", pr.number, pr.base_branch, self.config.branches)
            return False

        # 2. PR State filter
        state_filter = self.config.pr_state_filter
        if state_filter == PRStateFilter.MERGED_ONLY and not pr.is_merged:
            return False
        elif state_filter == PRStateFilter.OPEN_AND_MERGED and pr.state == "closed" and not pr.is_merged:
            return False

        # 3. Lookup mode & date filter
        mode = self.config.pr_lookup_mode
        if mode == PRLookupMode.CREATED_WITHIN_DAYS:
            if not is_within_days(pr.created_at, self.config.days):
                logger.debug("PR #%d skipped: created_at %s exceeds %d days", pr.number, pr.created_at, self.config.days)
                return False
        elif mode == PRLookupMode.MERGED_WITHIN_DAYS:
            if not pr.is_merged or not is_within_days(pr.merged_at, self.config.days):
                logger.debug("PR #%d skipped: merged_at %s exceeds %d days", pr.number, pr.merged_at, self.config.days)
                return False

        return True

    def _matches_author(self, pr: PRInfo) -> bool:
        """Evaluate author matching rules against filters, modes, and targets."""
        filters = self.config.author_filters
        if not filters:
            return True

        matching_mode = self.config.author_matching_mode
        match_against = self.config.author_filters_match_against

        def _check_user(login: str, name: str, email: str = "") -> bool:
            if match_against == AuthorMatchTarget.GITHUB_LOGIN:
                return matches_any_filter(login, filters)
            elif match_against == AuthorMatchTarget.GITHUB_NAME:
                return matches_any_filter(name, filters) or matches_any_filter(email, filters)
            else:  # BOTH
                return (
                    matches_any_filter(login, filters)
                    or matches_any_filter(name, filters)
                    or matches_any_filter(email, filters)
                )

        creator_matched = _check_user(pr.creator_login, pr.creator_name, pr.creator_email)

        commits_matched = False
        if matching_mode in (AuthorMatchingMode.COMMIT_AUTHOR, AuthorMatchingMode.BOTH):
            for c in pr.commits:
                if _check_user(c.author_login, c.author_name, c.author_email):
                    commits_matched = True
                    break

        matched = False
        if matching_mode == AuthorMatchingMode.PR_CREATOR:
            matched = creator_matched
        elif matching_mode == AuthorMatchingMode.COMMIT_AUTHOR:
            matched = commits_matched
        elif matching_mode == AuthorMatchingMode.BOTH:
            matched = creator_matched or commits_matched

        logger.debug(
            "PR #%d author evaluation [matched=%s, mode=%s]: creator='%s'/'%s'/'%s' (creator_match=%s), commits=%d (commits_match=%s), filters=%s",
            pr.number, matched, matching_mode.value, pr.creator_login, pr.creator_name, pr.creator_email, creator_matched, len(pr.commits), commits_matched, filters,
        )
        return matched

    def _audit_pull_request(
        self,
        repo: RepoTarget,
        pr: PRInfo,
        analyzer: Any,
        git_client: Optional[GitClient],
    ) -> None:
        """Audit single pull request, evaluate versions and contributors, and write report."""
        logger.info("Auditing PR #%d: '%s' (Base: %s, Head: %s)", pr.number, pr.title, pr.base_branch, pr.head_branch)
        self.prs_analyzed += 1

        try:
            # 1. Contributor Metrics
            stats = self._analyze_contributors(pr)

            # 2. Jira Extraction
            jira_ids = JiraParser.extract_and_format(
                title=pr.title,
                description=pr.body,
                commit_messages=[c.message for c in pr.commits],
            )

            # 3. Target branch HEAD SHA
            branch_head_sha: Optional[str] = None
            if git_client and git_client.is_git_repo():
                branch_head_sha = git_client.get_commit_sha(pr.base_branch)
            elif self.github_client and repo.owner and repo.name:
                branch_head_sha = self.github_client.get_branch_head_sha(repo.owner, repo.name, pr.base_branch)

            # 4. Version and Property File Analysis
            v_res = analyzer.analyze_pr(
                repo=repo,
                pr=pr,
                git_client=git_client,
                branch_head_sha=branch_head_sha,
            )

            # 5. Evaluate Status and Action
            status, action = self._determine_status_and_action(v_res)

            # Update counters
            if status == AuditStatus.PASS.value:
                self.pass_count += 1
            elif status == AuditStatus.REVIEW.value:
                self.review_count += 1
            else:
                self.error_count += 1

            # 6. Build Audit Record
            record = AuditRecord(
                repository=repo.full_name,
                branch=pr.base_branch,
                pr_number=str(pr.number),
                pr_title=pr.title,
                pr_url=pr.url,
                pr_created_by=pr.creator_login or pr.creator_name or "NA",
                pr_created_date=pr.created_at or "NA",
                merged_by=pr.merged_by_login or "NA",
                merged_date=pr.merged_at or "NA",
                commit_count=stats.commit_count,
                distinct_contributors=stats.distinct_count,
                contributor_names=stats.names,
                contributor_emails=stats.emails,
                jira_ids=jira_ids,
                project_properties_present=v_res.properties_present,
                project_properties_modified=v_res.properties_modified,
                project_properties_version_before_my_pr=v_res.version_before_my_pr,
                project_properties_version_in_my_pr=v_res.version_in_my_pr,
                project_properties_version_current_branch=v_res.version_current_branch,
                version_changed_in_my_pr=v_res.version_changed_in_my_pr,
                version_advanced_after_my_pr=v_res.version_advanced_after_my_pr,
                status=status,
                action=action,
            )

            # 7. Write Realtime Record
            if self.report_writer:
                self.report_writer.write_record(record, self.prs_analyzed, repo.full_name)

        except Exception as ex:
            logger.error("Failed auditing PR #%d in %s: %s", pr.number, repo.full_name, ex, exc_info=True)
            self._record_pr_error(repo, pr, str(ex))

    def _analyze_contributors(self, pr: PRInfo) -> Any:
        """Calculate commit count, distinct contributor count, names, and emails."""
        from models import ContributorStats

        mode = self.config.contributor_count_mode
        names: List[str] = []
        emails: List[str] = []
        seen_identities: Set[str] = set()

        # Commits
        for c in pr.commits:
            name = c.author_name or c.author_login or "Unknown"
            email = c.author_email or ""
            ident = f"{name}<{email}>"
            if ident not in seen_identities:
                seen_identities.add(ident)
                if name and name not in names:
                    names.append(name)
                if email and email not in emails:
                    emails.append(email)

        # Include PR creator if configured
        if mode == ContributorCountMode.COMMIT_AUTHORS_AND_PR_CREATOR:
            creator_name = pr.creator_name or pr.creator_login
            if creator_name and creator_name not in names:
                names.append(creator_name)
                seen_identities.add(f"{creator_name}<>")

        commit_count = len(pr.commits) if pr.commits else 1
        distinct_count = max(len(seen_identities), 1)
        names_str = ";".join(names) if names else (pr.creator_login or "NA")
        emails_str = ";".join(emails) if emails else "NA"

        return ContributorStats(
            commit_count=commit_count,
            distinct_count=distinct_count,
            names=names_str,
            emails=emails_str,
        )

    @staticmethod
    def _determine_status_and_action(v_res: Any) -> tuple[str, str]:
        """Determine PASS, REVIEW, or ERROR status and accompanying action."""
        if v_res.properties_present == "NO":
            return AuditStatus.REVIEW.value, "Property file missing in repository"

        if v_res.version_changed_in_my_pr == "YES":
            return AuditStatus.PASS.value, "None"

        if v_res.properties_modified == "YES" and v_res.version_changed_in_my_pr == "NO":
            return AuditStatus.REVIEW.value, "Property file modified but version key unchanged"

        # Properties present, but version not changed in PR
        return AuditStatus.REVIEW.value, "Version was not modified in PR"

    def _record_pr_error(self, repo: RepoTarget, pr: PRInfo, error_msg: str) -> None:
        """Write error row for failed PR audit."""
        self.error_count += 1
        record = AuditRecord(
            repository=repo.full_name,
            branch=pr.base_branch or "NA",
            pr_number=str(pr.number),
            pr_title=pr.title,
            pr_url=pr.url,
            pr_created_by=pr.creator_login or "NA",
            pr_created_date=pr.created_at or "NA",
            merged_by="NA",
            merged_date="NA",
            commit_count=0,
            distinct_contributors=0,
            contributor_names="NA",
            contributor_emails="NA",
            jira_ids="NA",
            project_properties_present="NA",
            project_properties_modified="NA",
            project_properties_version_before_my_pr="NA",
            project_properties_version_in_my_pr="NA",
            project_properties_version_current_branch="NA",
            version_changed_in_my_pr="NA",
            version_advanced_after_my_pr="NA",
            status=AuditStatus.ERROR.value,
            action=f"Error: {error_msg[:120]}",
        )
        if self.report_writer:
            self.report_writer.write_record(record, self.prs_analyzed, repo.full_name)

    def _record_repo_error(self, repo: RepoTarget, error_msg: str) -> None:
        """Write error row when repository discovery/fetch fails."""
        self.error_count += 1
        record = AuditRecord(
            repository=repo.full_name,
            branch=self.config.branches[0] if self.config.branches else "NA",
            pr_number="NA",
            pr_title="Scan Failed",
            pr_url=repo.clone_url or "NA",
            pr_created_by="NA",
            pr_created_date="NA",
            merged_by="NA",
            merged_date="NA",
            commit_count=0,
            distinct_contributors=0,
            contributor_names="NA",
            contributor_emails="NA",
            jira_ids="NA",
            project_properties_present="NA",
            project_properties_modified="NA",
            project_properties_version_before_my_pr="NA",
            project_properties_version_in_my_pr="NA",
            project_properties_version_current_branch="NA",
            version_changed_in_my_pr="NA",
            version_advanced_after_my_pr="NA",
            status=AuditStatus.ERROR.value,
            action=f"Repo Error: {error_msg[:120]}",
        )
        if self.report_writer:
            self.report_writer.write_record(record, self.prs_analyzed, repo.full_name)

    def _print_summary(self, duration: float) -> None:
        """Output execution statistics to console and log."""
        summary = (
            "\n"
            "==================================================\n"
            "AUDIT EXECUTION SUMMARY\n"
            "==================================================\n"
            f"Repositories Scanned : {self.repositories_scanned}\n"
            f"PRs Analyzed         : {self.prs_analyzed}\n"
            f"PASS Count           : {self.pass_count}\n"
            f"REVIEW Count         : {self.review_count}\n"
            f"ERROR Count          : {self.error_count}\n"
            f"Duration             : {duration:.2f} seconds\n"
            "=================================================="
        )
        print(summary)
        logger.info(summary)


def parse_cli_args() -> argparse.Namespace:
    """Configures and parses command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="git-audit-tool",
        description="Audit GitHub PRs for project.properties version changes, Jira tags, and contributors.",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml configuration file")
    parser.add_argument("--root", help="Local repository root directory path")
    parser.add_argument("--days", type=int, help="Number of lookback days for PR discovery")
    parser.add_argument("--author", help="Author filter pattern(s), comma-separated")
    parser.add_argument("--branches", help="Target branch(es) to inspect, comma-separated")
    parser.add_argument(
        "--repository-discovery-mode",
        choices=["local", "github_org", "github_contributor"],
        help="Repository discovery mode",
    )
    parser.add_argument(
        "--version-check-mode",
        choices=["pr_raised", "pr_merged", "commit", "file_author", "user_activity"],
        help="Version check mode",
    )
    parser.add_argument("--csv-report", help="Output file path for CSV report")
    parser.add_argument("--xlsx-report", help="Output file path for XLSX report")
    parser.add_argument("--log-file", help="Output file path for execution log")
    parser.add_argument("--progress-file", help="Output file path for progress status")
    parser.add_argument("--github-organization", help="GitHub organization name")
    parser.add_argument("--repo-filter", "--repository-name-filter", dest="repo_filter", help="Repository name filter(s), comma-separated")
    parser.add_argument("--property-file", help="Property file name to inspect (e.g. project.properties, gradle.properties)")
    parser.add_argument("--version-key", help="Key name to inspect in property file (e.g. version, springBootVersion)")
    parser.add_argument(
        "--parallel-fetch-workers",
        type=int,
        default=None,
        help="Number of concurrent worker threads for pre-fetching local repositories (default: 8)",
    )
    parser.add_argument(
        "--author-matching-mode",
        choices=["pr_creator", "commit_author", "both"],
        help="Author matching mode: 'pr_creator', 'commit_author', or 'both'",
    )
    parser.add_argument(
        "--author-match-against",
        choices=["github_login", "github_name", "both"],
        help="Match against 'github_login', 'github_name', or 'both'",
    )
    parser.add_argument("--no-fetch", action="store_true", help="Disable git fetch before scanning")

    return parser.parse_args()


def load_configuration(args: argparse.Namespace) -> AuditConfig:
    """
    Builds AuditConfig combining defaults, config.yaml, and CLI overrides with priority:
    CLI > config.yaml > defaults.
    """
    config_file_path = Path(args.config)
    raw_cfg: Dict[str, Any] = {}

    if config_file_path.exists():
        try:
            with open(config_file_path, "r", encoding="utf-8") as f:
                raw_cfg = yaml.safe_load(f) or {}
        except Exception as ex:
            print(f"Warning: Failed to parse YAML file {config_file_path}: {ex}", file=sys.stderr)

    # 1. Environment Loading (.env)
    dotenv_target = raw_cfg.get("dotenv_file", ".env")
    if Path(dotenv_target).exists():
        load_dotenv(dotenv_target)
    else:
        load_dotenv()

    # 2. Defaults and config.yaml values
    cfg = AuditConfig()

    if "root_folder" in raw_cfg:
        cfg.root_folder = Path(raw_cfg["root_folder"])
    if "repository_discovery_mode" in raw_cfg:
        cfg.repository_discovery_mode = DiscoveryMode(raw_cfg["repository_discovery_mode"])
    if "github_base_url" in raw_cfg:
        cfg.github_base_url = str(raw_cfg["github_base_url"]).strip()
    if "github_organization" in raw_cfg:
        cfg.github_organization = str(raw_cfg["github_organization"]).strip()
    if "github_token_env" in raw_cfg:
        cfg.github_token_env = str(raw_cfg["github_token_env"]).strip()
    if "repository_name_filters" in raw_cfg:
        cfg.repository_name_filters = list(raw_cfg["repository_name_filters"] or [])
    if "repository_contributor_filters" in raw_cfg:
        cfg.repository_contributor_filters = list(raw_cfg["repository_contributor_filters"] or [])
    if "repository_contributor_history_scope" in raw_cfg:
        cfg.repository_contributor_history_scope = ContributorHistoryScope(raw_cfg["repository_contributor_history_scope"])
    if "days" in raw_cfg:
        cfg.days = int(raw_cfg["days"])
    if "author_filters" in raw_cfg:
        cfg.author_filters = list(raw_cfg["author_filters"] or [])
    if "author_matching_mode" in raw_cfg:
        cfg.author_matching_mode = AuthorMatchingMode(raw_cfg["author_matching_mode"])
    if "author_filters_match_against" in raw_cfg:
        cfg.author_filters_match_against = AuthorMatchTarget(raw_cfg["author_filters_match_against"])
    if "branches" in raw_cfg:
        cfg.branches = list(raw_cfg["branches"] or [])
    if "pr_lookup_mode" in raw_cfg:
        cfg.pr_lookup_mode = PRLookupMode(raw_cfg["pr_lookup_mode"])
    if "pr_state_filter" in raw_cfg:
        cfg.pr_state_filter = PRStateFilter(raw_cfg["pr_state_filter"])
    if "property_file" in raw_cfg:
        cfg.property_file = str(raw_cfg["property_file"])
    if "property_files" in raw_cfg:
        cfg.property_files = list(raw_cfg["property_files"] or [])
    if "property_match_mode" in raw_cfg:
        cfg.property_match_mode = PropertyMatchMode(raw_cfg["property_match_mode"])
    if "version_key" in raw_cfg:
        cfg.version_key = str(raw_cfg["version_key"])
    if "version_check_mode" in raw_cfg:
        cfg.version_check_mode = VersionCheckMode(raw_cfg["version_check_mode"])
    if "version_source_in_pr" in raw_cfg:
        cfg.version_source_in_pr = VersionSourceInPR(raw_cfg["version_source_in_pr"])
    if "missing_project_properties_behavior" in raw_cfg:
        cfg.missing_project_properties_behavior = str(raw_cfg["missing_project_properties_behavior"])
    if "contributor_count_mode" in raw_cfg:
        cfg.contributor_count_mode = ContributorCountMode(raw_cfg["contributor_count_mode"])
    if "jira_sources" in raw_cfg:
        cfg.jira_sources = str(raw_cfg["jira_sources"])
    if "fetch_before_scan" in raw_cfg:
        cfg.fetch_before_scan = bool(raw_cfg["fetch_before_scan"])
    if "parallel_fetch_workers" in raw_cfg:
        cfg.parallel_fetch_workers = int(raw_cfg["parallel_fetch_workers"])
    if "log_file" in raw_cfg:
        cfg.log_file = Path(raw_cfg["log_file"])
    if "csv_report" in raw_cfg:
        cfg.csv_report = Path(raw_cfg["csv_report"])
    if "xlsx_report" in raw_cfg:
        cfg.xlsx_report = Path(raw_cfg["xlsx_report"])
    if "xlsx_realtime_save" in raw_cfg:
        cfg.xlsx_realtime_save = bool(raw_cfg["xlsx_realtime_save"])
    if "xlsx_status_colors" in raw_cfg:
        cfg.xlsx_status_colors = bool(raw_cfg["xlsx_status_colors"])
    if "progress_file" in raw_cfg:
        cfg.progress_file = Path(raw_cfg["progress_file"])
    if "dotenv_file" in raw_cfg:
        cfg.dotenv_file = Path(raw_cfg["dotenv_file"])

    # 3. CLI Overrides (Highest Priority)
    if args.root:
        cfg.root_folder = Path(args.root)
    if args.days is not None:
        cfg.days = args.days
    if args.author:
        cfg.author_filters = [a.strip() for a in args.author.split(",") if a.strip()]
    if args.branches:
        cfg.branches = [b.strip() for b in args.branches.split(",") if b.strip()]
    if args.repository_discovery_mode:
        cfg.repository_discovery_mode = DiscoveryMode(args.repository_discovery_mode)
    if args.version_check_mode:
        cfg.version_check_mode = VersionCheckMode(args.version_check_mode)
    if args.csv_report:
        cfg.csv_report = Path(args.csv_report)
    if args.xlsx_report:
        cfg.xlsx_report = Path(args.xlsx_report)
    if args.log_file:
        cfg.log_file = Path(args.log_file)
    if args.progress_file:
        cfg.progress_file = Path(args.progress_file)
    if args.github_organization:
        cfg.github_organization = args.github_organization.strip()
    if getattr(args, "repo_filter", None) is not None:
        if args.repo_filter.strip():
            cfg.repository_name_filters = [f.strip() for f in args.repo_filter.split(",") if f.strip()]
        else:
            cfg.repository_name_filters = []
    if getattr(args, "property_file", None):
        cfg.property_file = args.property_file.strip()
        cfg.property_files = [args.property_file.strip()]
    if getattr(args, "author_matching_mode", None):
        cfg.author_matching_mode = AuthorMatchingMode(args.author_matching_mode)
    if getattr(args, "author_match_against", None):
        cfg.author_filters_match_against = AuthorMatchTarget(args.author_match_against)
    if getattr(args, "parallel_fetch_workers", None) is not None:
        cfg.parallel_fetch_workers = args.parallel_fetch_workers
    if args.no_fetch:
        cfg.fetch_before_scan = False

    # 4. Resolve GitHub Token from environment
    token_val = os.getenv(cfg.github_token_env, "").strip()
    cfg.github_token = token_val

    return cfg


def main() -> int:
    """CLI launcher."""
    args = parse_cli_args()
    config = load_configuration(args)

    # Setup Logging
    setup_logging(config.log_file, config.github_token)

    orchestrator = GitAuditOrchestrator(config)
    return orchestrator.run()


if __name__ == "__main__":
    sys.exit(main())
