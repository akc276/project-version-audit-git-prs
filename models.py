"""
Domain models, configuration structures, and dataclasses for git-audit-tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class DiscoveryMode(str, Enum):
    LOCAL = "local"
    GITHUB_ORG = "github_org"
    GITHUB_CONTRIBUTOR = "github_contributor"


class ContributorHistoryScope(str, Enum):
    LOOKBACK = "lookback"
    ALL_HISTORY = "all_history"


class AuthorMatchingMode(str, Enum):
    COMMIT_AUTHOR = "commit_author"
    PR_CREATOR = "pr_creator"
    BOTH = "both"


class AuthorMatchTarget(str, Enum):
    GITHUB_LOGIN = "github_login"
    GITHUB_NAME = "github_name"
    BOTH = "both"


class PRLookupMode(str, Enum):
    CREATED_WITHIN_DAYS = "created_within_days"
    MERGED_WITHIN_DAYS = "merged_within_days"
    LATEST_PR_FOR_AUTHOR = "latest_pr_for_author"


class PRStateFilter(str, Enum):
    OPENED_BY_AUTHOR = "opened_by_author"
    MERGED_ONLY = "merged_only"
    OPEN_AND_MERGED = "open_and_merged"


class PropertyMatchMode(str, Enum):
    EXACT_FILENAME = "exact_filename"
    ENDSWITH_FILENAME = "endswith_filename"


class VersionCheckMode(str, Enum):
    COMMIT = "commit"
    FILE_AUTHOR = "file_author"
    USER_ACTIVITY = "user_activity"
    PR_RAISED = "pr_raised"
    PR_MERGED = "pr_merged"


class VersionSourceInPR(str, Enum):
    MERGED_HEAD = "merged_head"


class ContributorCountMode(str, Enum):
    COMMIT_AUTHORS_ONLY = "commit_authors_only"
    COMMIT_AUTHORS_AND_PR_CREATOR = "commit_authors_and_pr_creator"


class AuditStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    ERROR = "ERROR"


REPORT_COLUMNS: List[str] = [
    "Repository",
    "Branch",
    "PRNumber",
    "PRTitle",
    "PRUrl",
    "PRCreatedBy",
    "PRCreatedDate",
    "MergedBy",
    "MergedDate",
    "CommitCount",
    "DistinctContributors",
    "ContributorNames",
    "ContributorEmails",
    "JiraIds",
    "ProjectPropertiesPresent",
    "ProjectPropertiesModified",
    "ProjectPropertiesVersionBeforeMyPR",
    "ProjectPropertiesVersionInMyPR",
    "ProjectPropertiesVersionCurrentBranch",
    "VersionChangedInMyPR",
    "VersionAdvancedAfterMyPR",
    "Status",
    "Action",
]


@dataclass
class AuditConfig:
    """Holds runtime configuration derived from CLI, config.yaml, and defaults."""
    root_folder: Path = field(default_factory=lambda: Path(r"D:\Cariad\Repos"))
    repository_discovery_mode: DiscoveryMode = DiscoveryMode.LOCAL
    github_base_url: str = "github.com"
    github_organization: str = "CHANGE_ME"
    github_token_env: str = "GITHUB_TOKEN"
    repository_name_filters: List[str] = field(default_factory=lambda: ["service"])
    repository_contributor_filters: List[str] = field(default_factory=lambda: ["ankit"])
    repository_contributor_history_scope: ContributorHistoryScope = ContributorHistoryScope.LOOKBACK
    days: int = 3
    author_filters: List[str] = field(default_factory=lambda: ["ankit"])
    author_matching_mode: AuthorMatchingMode = AuthorMatchingMode.BOTH
    author_filters_match_against: AuthorMatchTarget = AuthorMatchTarget.BOTH
    branches: List[str] = field(default_factory=lambda: ["test", "preprod"])
    pr_lookup_mode: PRLookupMode = PRLookupMode.CREATED_WITHIN_DAYS
    pr_state_filter: PRStateFilter = PRStateFilter.OPENED_BY_AUTHOR
    property_file: str = "project.properties"
    property_files: List[str] = field(default_factory=list)
    property_match_mode: PropertyMatchMode = PropertyMatchMode.EXACT_FILENAME
    version_key: str = "version"
    version_check_mode: VersionCheckMode = VersionCheckMode.PR_RAISED
    version_source_in_pr: VersionSourceInPR = VersionSourceInPR.MERGED_HEAD
    missing_project_properties_behavior: str = "NA"
    contributor_count_mode: ContributorCountMode = ContributorCountMode.COMMIT_AUTHORS_AND_PR_CREATOR
    jira_sources: str = "all"
    fetch_before_scan: bool = True
    parallel_fetch_workers: int = 8
    log_file: Path = field(default_factory=lambda: Path("output/audit.log"))
    csv_report: Path = field(default_factory=lambda: Path("output/audit_report.csv"))
    xlsx_report: Path = field(default_factory=lambda: Path("output/audit_report.xlsx"))
    xlsx_realtime_save: bool = True
    xlsx_status_colors: bool = True
    progress_file: Path = field(default_factory=lambda: Path("output/progress.txt"))
    dotenv_file: Path = field(default_factory=lambda: Path(".env"))
    github_token: str = ""

    def get_candidate_property_files(self) -> List[str]:
        """Returns ordered list of candidate property filenames to inspect."""
        if self.property_files:
            return self.property_files
        if self.property_file:
            return [self.property_file]
        return ["project.properties"]


@dataclass
class RepoTarget:
    """Represents a discovered repository (local, GitHub remote, or both)."""
    name: str
    owner: str = ""
    full_name: str = ""
    local_path: Optional[Path] = None
    clone_url: str = ""
    default_branch: str = "main"

    def __post_init__(self) -> None:
        if not self.full_name and self.owner and self.name:
            self.full_name = f"{self.owner}/{self.name}"
        elif self.full_name and not self.owner:
            parts = self.full_name.split("/")
            if len(parts) == 2:
                self.owner, self.name = parts[0], parts[1]


@dataclass
class CommitInfo:
    """Represents commit metadata."""
    sha: str
    author_name: str
    author_email: str
    author_login: str
    message: str
    date: str


@dataclass
class PRInfo:
    """Represents pull request metadata."""
    number: int
    title: str
    url: str
    creator_login: str
    creator_name: str
    created_at: str
    merged_by_login: str
    merged_at: str
    state: str
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    is_merged: bool
    body: str = ""
    creator_email: str = ""
    commits: List[CommitInfo] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)


@dataclass
class ContributorStats:
    """Aggregated contributor information for a PR."""
    commit_count: int
    distinct_count: int
    names: str
    emails: str


@dataclass
class VersionAuditResult:
    """Results of analyzing project properties and version indicators."""
    properties_present: str
    properties_modified: str
    version_before_my_pr: str
    version_in_my_pr: str
    version_current_branch: str
    version_changed_in_my_pr: str
    version_advanced_after_my_pr: str
    matched_property_file: Optional[str] = None


@dataclass
class AuditRecord:
    """Single audit output row matching exactly the 23 reporting columns."""
    repository: str
    branch: str
    pr_number: str
    pr_title: str
    pr_url: str
    pr_created_by: str
    pr_created_date: str
    merged_by: str
    merged_date: str
    commit_count: int
    distinct_contributors: int
    contributor_names: str
    contributor_emails: str
    jira_ids: str
    project_properties_present: str
    project_properties_modified: str
    project_properties_version_before_my_pr: str
    project_properties_version_in_my_pr: str
    project_properties_version_current_branch: str
    version_changed_in_my_pr: str
    version_advanced_after_my_pr: str
    status: str
    action: str

    def to_row(self) -> List[Any]:
        """Convert to ordered list of values matching REPORT_COLUMNS."""
        return [
            self.repository,
            self.branch,
            self.pr_number,
            self.pr_title,
            self.pr_url,
            self.pr_created_by,
            self.pr_created_date,
            self.merged_by,
            self.merged_date,
            self.commit_count,
            self.distinct_contributors,
            self.contributor_names,
            self.contributor_emails,
            self.jira_ids,
            self.project_properties_present,
            self.project_properties_modified,
            self.project_properties_version_before_my_pr,
            self.project_properties_version_in_my_pr,
            self.project_properties_version_current_branch,
            self.version_changed_in_my_pr,
            self.version_advanced_after_my_pr,
            self.status,
            self.action,
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary keyed by standard REPORT_COLUMNS."""
        return dict(zip(REPORT_COLUMNS, self.to_row()))
