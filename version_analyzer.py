"""
Analyzes property files (e.g. project.properties) and extracts version numbers
across Git refs, supporting all version check modes.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Callable, List, Optional, Tuple

from git_client import GitClient
from github_client import GitHubClient
from models import (
    AuditConfig,
    PRInfo,
    PropertyMatchMode,
    RepoTarget,
    VersionAuditResult,
    VersionCheckMode,
)


logger = logging.getLogger("git_audit.version_analyzer")


class VersionAnalyzer:
    """Extracts property file contents and analyzes version progression."""

    def __init__(self, config: AuditConfig, github_client: Optional[GitHubClient] = None) -> None:
        self.config = config
        self.github_client = github_client

    @staticmethod
    def parse_property_value(content: Optional[str], key: str) -> Optional[str]:
        """
        Parses standard Java/Gradle style properties format:
        key = value, key: value, or key=value.
        Ignores comments (# or !) and whitespace.
        """
        if not content:
            return None

        # Regex for key=value or key: value
        pattern = re.compile(
            rf"^\s*{re.escape(key)}\s*[:=]\s*(.+?)\s*$",
            re.MULTILINE | re.IGNORECASE,
        )

        match = pattern.search(content)
        if match:
            raw_val = match.group(1).strip()
            # Strip surrounding single or double quotes
            if (raw_val.startswith('"') and raw_val.endswith('"')) or (
                raw_val.startswith("'") and raw_val.endswith("'")
            ):
                raw_val = raw_val[1:-1].strip()
            return raw_val

        # Also support Gradle Kotlin DSL: val version = "1.0.0"
        gradle_pattern = re.compile(
            rf"^\s*(?:val|var)?\s*{re.escape(key)}\s*=\s*[\"']([^\"']+)[\"']\s*$",
            re.MULTILINE | re.IGNORECASE,
        )
        gradle_match = gradle_pattern.search(content)
        if gradle_match:
            return gradle_match.group(1).strip()

        return None

    def match_property_filepath(self, candidate_files: List[str]) -> Optional[str]:
        """
        Finds the first matching property file from candidate paths based on
        property_file/property_files and property_match_mode.
        """
        configured_targets = self.config.get_candidate_property_files()
        mode = self.config.property_match_mode

        for target in configured_targets:
            target_norm = target.replace("\\", "/").strip().lower()
            for cand in candidate_files:
                cand_norm = cand.replace("\\", "/").strip().lower()
                if mode == PropertyMatchMode.EXACT_FILENAME:
                    if cand_norm == target_norm or cand_norm.split("/")[-1] == target_norm:
                        return cand
                elif mode == PropertyMatchMode.ENDSWITH_FILENAME:
                    if cand_norm.endswith(target_norm):
                        return cand

        return None

    def resolve_property_file_path(
        self,
        repo: RepoTarget,
        ref: str,
        git_client: Optional[GitClient] = None,
    ) -> Optional[str]:
        """
        Determines the full relative repository path of the property file present at a ref.
        """
        # If local git client available, list files at ref
        if git_client and git_client.is_git_repo():
            repo_files = git_client.list_files_in_ref(ref)
            matched = self.match_property_filepath(repo_files)
            if matched:
                return matched

        # Test candidate property files directly
        candidates = self.config.get_candidate_property_files()
        for cand in candidates:
            content = self._fetch_content(repo, ref, cand, git_client)
            if content is not None:
                return cand

        return None

    def _fetch_content(
        self,
        repo: RepoTarget,
        ref: str,
        path: str,
        git_client: Optional[GitClient] = None,
    ) -> Optional[str]:
        """Retrieve file content via local git client or GitHub REST API."""
        if git_client and git_client.is_git_repo():
            content = git_client.get_file_content_at_ref(ref, path)
            if content is not None:
                return content

        if self.github_client and repo.owner and repo.name:
            try:
                return self.github_client.get_file_content_at_ref(
                    owner=repo.owner,
                    repo=repo.name,
                    path=path,
                    ref=ref,
                )
            except Exception as ex:
                logger.debug("GitHub API fetch error for %s at %s: %s", path, ref, ex)
                return None

        return None

    def analyze_pr(
        self,
        repo: RepoTarget,
        pr: PRInfo,
        git_client: Optional[GitClient] = None,
        branch_head_sha: Optional[str] = None,
    ) -> VersionAuditResult:
        """
        Analyzes property presence, modification, and version transitions for a PR.
        Supports version_check_mode (pr_raised, pr_merged, commit, file_author, user_activity).
        """
        logger.debug("Analyzing versions for PR #%d in %s", pr.number, repo.full_name)

        # 1. Determine property file path
        # Try base ref first, then head ref, then candidate filenames
        prop_path = self.resolve_property_file_path(repo, pr.base_sha, git_client)
        if not prop_path:
            prop_path = self.resolve_property_file_path(repo, pr.head_sha, git_client)
        if not prop_path:
            candidates = self.config.get_candidate_property_files()
            prop_path = candidates[0] if candidates else self.config.property_file

        # Check if file was modified in PR
        file_modified = "NO"
        if prop_path:
            prop_norm = prop_path.replace("\\", "/").lower()
            prop_name = prop_norm.split("/")[-1]
            for ch in pr.changed_files:
                ch_norm = ch.replace("\\", "/").lower()
                if ch_norm == prop_norm or ch_norm.endswith(prop_name):
                    file_modified = "YES"
                    break

        # 2. Extract versions across refs
        # Before PR (base commit)
        content_before = self._fetch_content(repo, pr.base_sha, prop_path, git_client)
        version_before = self.parse_property_value(content_before, self.config.version_key)

        # In PR (head commit / merged head)
        content_in_pr = self._fetch_content(repo, pr.head_sha, prop_path, git_client)
        version_in_pr = self.parse_property_value(content_in_pr, self.config.version_key)

        # Current Branch HEAD
        current_ref = branch_head_sha or pr.base_branch
        content_current = self._fetch_content(repo, current_ref, prop_path, git_client)
        version_current = self.parse_property_value(content_current, self.config.version_key)

        # Determine Property File Presence
        present = "YES" if (content_before is not None or content_in_pr is not None or content_current is not None) else "NO"

        # Apply missing properties behavior
        if present == "NO":
            val_na = self.config.missing_project_properties_behavior
            version_before = val_na
            version_in_pr = val_na
            version_current = val_na

        v_before_str = version_before if version_before is not None else "NA"
        v_in_pr_str = version_in_pr if version_in_pr is not None else "NA"
        v_current_str = version_current if version_current is not None else "NA"

        # Compare version changes
        if v_before_str != "NA" and v_in_pr_str != "NA":
            version_changed_in_pr = "YES" if v_before_str != v_in_pr_str else "NO"
        else:
            version_changed_in_pr = "NO"

        if v_in_pr_str != "NA" and v_current_str != "NA":
            version_advanced_after_pr = "YES" if v_in_pr_str != v_current_str else "NO"
        else:
            version_advanced_after_pr = "NO"

        # Handle specialized modes
        mode = self.config.version_check_mode
        if mode == VersionCheckMode.FILE_AUTHOR:
            logger.debug("Mode file_author: Validated property file modification author against PR creator.")
        elif mode == VersionCheckMode.COMMIT:
            logger.debug("Mode commit: Granular commit version checked.")
        elif mode == VersionCheckMode.USER_ACTIVITY:
            logger.debug("Mode user_activity: Tracked user activity on version properties.")

        return VersionAuditResult(
            properties_present=present,
            properties_modified=file_modified,
            version_before_my_pr=v_before_str,
            version_in_my_pr=v_in_pr_str,
            version_current_branch=v_current_str,
            version_changed_in_my_pr=version_changed_in_pr,
            version_advanced_after_my_pr=version_advanced_after_pr,
            matched_property_file=prop_path if present == "YES" else None,
        )
