# Required Updates Before First Run

Before running **git-audit-tool**, you must update the following settings:

1. **`.env`**:
   - `GITHUB_TOKEN`: Provide your GitHub Personal Access Token (classic with `repo` scope or fine-grained with Pull Requests and Contents read access).
2. **`config.yaml`**:
   - `github_organization`: Replace `CHANGE_ME` with your actual GitHub organization or user account name (e.g. `my-enterprise-org`).
   - `root_folder`: If using `repository_discovery_mode: local`, set this to the local path containing your cloned Git repositories (e.g. `D:\Cariad\Repos` or `/Users/username/repos`).
   - `author_filters`: Update the list of GitHub usernames or email domains to match your target developers (e.g., `["ankit", "@company.com"]`).
   - `branches`: Set the target branches your organization uses for deployment staging (e.g. `["test", "preprod", "main"]`).

---

# git-audit-tool

An enterprise-grade audit utility for Git repositories and GitHub Pull Requests. It analyzes PRs raised or contributed by configured authors, extracts Jira issue keys, assesses contributor statistics, and audits `project.properties` version changes across Git branches with real-time streaming to CSV, styled Excel (XLSX), logs, and progress trackers.

## Installation

### Prerequisites
- Python 3.12 or newer
- Git 2.30+ installed and available on system `PATH`

### Setup Virtual Environment
```bash
# Clone or navigate to the project directory
cd git-audit-tool

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

---

## Environment Variables

The tool loads environment variables from `.env` using `python-dotenv`.

| Variable | Description | Default |
|---|---|---|
| `GITHUB_TOKEN` | GitHub Personal Access Token or OAuth Bearer token | *None* |

Tokens are automatically masked in console outputs and log files (e.g., `ghp_********`).

---

## Configuration

Configuration is managed via `config.yaml` with full command-line override support.

### Complete `config.yaml` Reference

```yaml
# Root folder scanned recursively when repository_discovery_mode is 'local'
root_folder: D:\Cariad\Repos

# Repository discovery mode: 'local', 'github_org', or 'github_contributor'
repository_discovery_mode: local

# GitHub hostname: 'github.com' or GitHub Enterprise host (e.g., 'github.mycompany.com')
github_base_url: github.com

# Target GitHub organization or user account
github_organization: CHANGE_ME

# Name of the environment variable containing the GitHub API token
github_token_env: GITHUB_TOKEN

# Case-insensitive substring filters applied to repository names
repository_name_filters:
  - service

# Contributor filters used when repository_discovery_mode is 'github_contributor'
repository_contributor_filters:
  - ankit
  - "@company.com"

# Scope for contributor discovery: 'lookback' (within days) or 'all_history'
repository_contributor_history_scope: lookback

# Number of days to look back for PR and commit activity
days: 3

# Author filter patterns (usernames, names, or email domains)
author_filters:
  - ankit
  - "@company.com"

# Matching rule for authors: 'commit_author', 'pr_creator', or 'both'
author_matching_mode: pr_creator

# User attribute to match against: 'github_login', 'github_name', or 'both'
author_filters_match_against: both

# Target base branches to audit PRs against
branches:
  - test
  - preprod

# PR lookup selection strategy: 'created_within_days', 'merged_within_days', 'latest_pr_for_author'
pr_lookup_mode: created_within_days

# PR state criteria: 'opened_by_author', 'merged_only', or 'open_and_merged'
pr_state_filter: opened_by_author

# Single property file to inspect
property_file: project.properties

# Optional list of property files scanned in priority order (first match wins)
# property_files:
#   - project.properties
#   - gradle.properties
#   - build.gradle.kts

# Match method for property filenames: 'exact_filename' or 'endswith_filename'
property_match_mode: exact_filename

# Property key containing the version string
version_key: version

# Version analysis mode: 'pr_raised', 'pr_merged', 'commit', 'file_author', 'user_activity'
version_check_mode: pr_raised

# Commit ref source for PR version reading: 'merged_head'
version_source_in_pr: merged_head

# Value assigned to version columns if property file is missing
missing_project_properties_behavior: NA

# Contributor counting mode: 'commit_authors_only' or 'commit_authors_and_pr_creator'
contributor_count_mode: commit_authors_and_pr_creator

# Sources scanned for Jira IDs: 'all' (PR Title, PR Description, Commit Messages)
jira_sources: all

# If true, runs `git fetch --all --prune` on local repos before scanning
fetch_before_scan: true

# Output file destinations
log_file: output/audit.log
csv_report: output/audit_report.csv
xlsx_report: output/audit_report.xlsx

# Save XLSX after each PR to prevent data loss on interruption
xlsx_realtime_save: true

# Apply visual conditional formatting (PASS: Green, REVIEW: Yellow, ERROR: Red)
xlsx_status_colors: true

# Real-time plain text progress tracking log
progress_file: output/progress.txt

# Path to the dotenv credentials file
dotenv_file: .env
```

---

## Repository Discovery Modes

1. **`local`**:
   - Recursively walks `root_folder` searching for Git repositories.
   - Respects `repository_name_filters`.
   - Resolves remote origin URLs to link directly to GitHub PRs.
   - Operates in offline/local simulation mode when remotes or tokens are unavailable.

2. **`github_org`**:
   - Queries GitHub REST API for all repositories under `github_organization`.
   - Filters repositories by `repository_name_filters`.

3. **`github_contributor`**:
   - Identifies repositories where specified authors contributed matching `repository_contributor_filters`.
   - Configurable scope via `repository_contributor_history_scope`:
     - `lookback`: Scans commit activity within the past `days`.
     - `all_history`: Scans contributors across complete repository history.

---

## Author Matching Modes

### `author_matching_mode`
- `pr_creator`: Checks only the user who opened the Pull Request.
- `commit_author`: Checks the authors of commits included in the PR.
- `both`: Matches if either the PR creator or any commit author matches the filter.

### `author_filters_match_against`
- `github_login`: Evaluates GitHub login/username.
- `github_name`: Evaluates GitHub display name and git commit author name/email.
- `both`: Matches if username, display name, or email contains any filter pattern.

---

## Version Modes

### `version_check_mode`
- `pr_raised` *(Default)*: Audits version progression for PRs raised by configured authors against target branches.
  - Analyzes version before PR (`ProjectPropertiesVersionBeforeMyPR`).
  - Analyzes version in PR (`ProjectPropertiesVersionInMyPR`).
  - Analyzes version in current branch HEAD (`ProjectPropertiesVersionCurrentBranch`).
  - Computes `VersionChangedInMyPR` and `VersionAdvancedAfterMyPR`.
- `pr_merged`: Specifically filters and audits merged PRs.
- `commit`: Audits version updates commit-by-commit on target branches.
- `file_author`: Identifies committers modifying property files.
- `user_activity`: Comprehensive user activity audit across versioned files.

---

## Output Files

All output files are updated in real-time after every analyzed Pull Request:

1. **`output/audit.log`**: Detailed execution log with token masking and debug information.
2. **`output/audit_report.csv`**: Standard CSV report with OS-level `fsync` on every line.
3. **`output/audit_report.xlsx`**: Excel workbook featuring:
   - Freeze pane on the top header row (`A2`).
   - AutoFilter across all columns.
   - Autosized column widths with cell padding.
   - Clickable hyperlinks for PR URLs.
   - Conditional color fills:
     - **PASS** → Soft Green (`#D9EAD3`)
     - **REVIEW** → Soft Yellow (`#FFF2CC`)
     - **ERROR** → Soft Red (`#F4CCCC`)
4. **`output/progress.txt`**: Real-time progress log tracking execution milestones.

---

## Output Columns

The audit report produces exactly 23 structured columns:

| # | Column Name | Description | Example |
|---|---|---|---|
| 1 | `Repository` | Repository full name or local path | `org/service-auth` |
| 2 | `Branch` | Target destination branch of the PR | `test` |
| 3 | `PRNumber` | Pull Request number | `101` |
| 4 | `PRTitle` | Pull Request title | `[PROJ-101] Version bump` |
| 5 | `PRUrl` | Clickable link to GitHub PR | `https://github.com/org/service-auth/pull/101` |
| 6 | `PRCreatedBy` | Username or author who raised PR | `ankit` |
| 7 | `PRCreatedDate` | Timestamp PR was created | `2026-10-15T10:00:00Z` |
| 8 | `MergedBy` | Username who merged PR (or `NA`) | `ankit` |
| 9 | `MergedDate` | Timestamp PR was merged (or `NA`) | `2026-10-15T11:30:00Z` |
| 10 | `CommitCount` | Number of commits included in PR | `2` |
| 11 | `DistinctContributors` | Count of unique contributors in PR | `2` |
| 12 | `ContributorNames` | Semicolon-separated contributor names | `alice;ankit` |
| 13 | `ContributorEmails` | Semicolon-separated contributor emails | `alice@company.com;ankit@company.com` |
| 14 | `JiraIds` | Semicolon-separated Jira issue keys | `PROJ-101;AUTH-202` |
| 15 | `ProjectPropertiesPresent` | Whether property file exists (`YES`/`NO`) | `YES` |
| 16 | `ProjectPropertiesModified` | Whether property file was touched in PR (`YES`/`NO`) | `YES` |
| 17 | `ProjectPropertiesVersionBeforeMyPR` | Version on base branch before PR | `1.0.0` |
| 18 | `ProjectPropertiesVersionInMyPR` | Version inside the PR | `1.1.0` |
| 19 | `ProjectPropertiesVersionCurrentBranch` | Version currently at target branch HEAD | `1.1.0` |
| 20 | `VersionChangedInMyPR` | Whether version was incremented (`YES`/`NO`) | `YES` |
| 21 | `VersionAdvancedAfterMyPR` | Whether branch advanced further (`YES`/`NO`) | `NO` |
| 22 | `Status` | `PASS`, `REVIEW`, or `ERROR` | `PASS` |
| 23 | `Action` | Recommended next steps or resolution | `None` |

---

## CLI Arguments

Command-line arguments take precedence over `config.yaml` and default values:

| Argument | Description |
|---|---|
| `--config PATH` | Path to configuration file (default: `config.yaml`) |
| `--root PATH` | Override `root_folder` for local repository scanning |
| `--days INT` | Override lookback days window |
| `--author STR` | Override author filter (comma-separated list) |
| `--branches STR` | Override target branches (comma-separated list) |
| `--repository-discovery-mode MODE` | Override discovery mode (`local`, `github_org`, `github_contributor`) |
| `--version-check-mode MODE` | Override version check mode (`pr_raised`, `pr_merged`, `commit`, etc.) |
| `--csv-report PATH` | Override output CSV file path |
| `--xlsx-report PATH` | Override output XLSX file path |
| `--log-file PATH` | Override log file path |
| `--progress-file PATH` | Override progress tracking file path |
| `--github-organization STR` | Override GitHub organization name |
| `--no-fetch` | Disable `git fetch --all --prune` execution |

---

## Usage Examples

### 1. Run with Default Configuration
```bash
python git_audit.py
```

### 2. Audit Local Repositories with Custom Lookback
```bash
python git_audit.py --root "/Users/dev/repos" --repository-discovery-mode local --days 14 --branches test,preprod
```

### 3. Audit Specific Author Across GitHub Organization
```bash
python git_audit.py --repository-discovery-mode github_org --github-organization myorg --author ankit --days 7
```

### 4. Custom Output Paths and No Git Fetch
```bash
python git_audit.py --csv-report reports/audit.csv --xlsx-report reports/audit.xlsx --no-fetch
```

---

## Local Test Harness

A complete automated local test harness is provided to validate functionality offline without requiring GitHub credentials.

### Windows
```cmd
tests\run_local_test.bat
```

### macOS / Linux
```bash
bash tests/run_local_test.sh
```

### What the Test Harness Does:
1. Runs `tests/create_test_repo.py` to construct a Git repository with `test` and `preprod` branches.
2. Commits simulated Pull Requests with multiple authors (`ankit`, `alice`).
3. Embeds Jira keys (`PROJ-101`, `AUTH-202`, `PROJ-105`) and increments `project.properties` versions.
4. Executes `git_audit.py` to audit the local repository.
5. Verifies that `audit.log`, `audit_report.csv`, `audit_report.xlsx`, and `progress.txt` exist and are populated.

---

## Troubleshooting

- **Missing GitHub Token**:
  If running in `github_org` or `github_contributor` mode, verify that `GITHUB_TOKEN` is exported in your environment or present in `.env`.
- **Rate Limit Exceeded (HTTP 403 / 429)**:
  `github_client.py` will automatically back off exponentially and retry. For higher rate limits, ensure an authenticated token is configured.
- **Git Binary Not Found**:
  Verify that `git --version` executes successfully in your terminal.
- **Permission Denied on Output Files**:
  Ensure Excel or another application does not have `output/audit_report.xlsx` or `output/audit_report.csv` locked for writing.
