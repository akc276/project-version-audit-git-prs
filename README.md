# Required Updates Before First Run

Before running **git-audit-tool**, you must edit only the following values:

1. **`.env`**:
   - `GITHUB_TOKEN`: Your GitHub Personal Access Token (only needed for private repositories or remote GitHub API discovery).
2. **`config.yaml`**:
   - `github_organization`: Replace `CHANGE_ME` with your GitHub organization or username (e.g. `my-org`).
   - `root_folder`: If using local mode, set this to your repositories directory (e.g. `D:\Cariad\Repos` or `/Users/name/repos`).
   - `author_filters`: Set your name, username, or email to audit (e.g. `["ankit"]` or `["ankit.kr.chahal@company.com"]`). You only need your own identifier—no dummy domains needed.
   - `branches`: Set the target branches to audit PRs against (e.g. `["test", "preprod", "main"]`).

---

# git-audit-tool

Enterprise-grade audit utility for Git repositories and GitHub Pull Requests. It audits PRs raised or contributed by configured authors, extracts Jira issue keys, assesses contributor statistics, and audits `project.properties` (or `gradle.properties`) version changes across branches with real-time streaming to CSV, styled Excel (XLSX), logs, and progress trackers.

---

## 🚀 Quick Start (3 Steps)

### Step 1: Install Dependencies
```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# 2. Install required packages
pip install -r requirements.txt
```

### Step 2: Set Your GitHub Token (Optional for public repos)
Copy the example file and add your token:
```bash
cp .env.example .env
```
Edit `.env`:
```ini
GITHUB_TOKEN=ghp_yourPersonalAccessTokenHere
```

### Step 3: Run the Audit
```bash
# Run with settings from config.yaml:
python git_audit.py

# Or run with CLI overrides on the fly:
python git_audit.py --author ankit --branches test,preprod --days 7
```

---

## 📋 Copy-and-Paste `config.yaml` Recipes

Choose the recipe matching your workflow, paste it into `config.yaml`, and run!

### Recipe A: Audit Local Cloned Repositories on Your Machine
Ideal when you already have repositories cloned locally. Works completely offline.
```yaml
root_folder: /Users/ankit.kr.chahal/Documents/Codes/my-repos
repository_discovery_mode: local
repository_name_filters: []

author_filters:
  - ankit
  - "@company.com"
author_matching_mode: pr_creator
author_filters_match_against: both

branches:
  - test
  - preprod
  - main

property_file: project.properties
version_key: version
version_check_mode: pr_raised
days: 30
fetch_before_scan: false

csv_report: output/audit_report.csv
xlsx_report: output/audit_report.xlsx
log_file: output/audit.log
progress_file: output/progress.txt
```

---

### Recipe B: Audit a Remote GitHub Organization
Audits repositories directly via GitHub REST API without needing local clones.
```yaml
repository_discovery_mode: github_org
github_base_url: github.com
github_organization: my-company-org
github_token_env: GITHUB_TOKEN

repository_name_filters:
  - service          # Only audit repos with "service" in their name

author_filters:
  - ankit
  - "@company.com"
author_matching_mode: pr_creator
author_filters_match_against: both

branches:
  - test
  - preprod

property_file: project.properties
version_key: version
version_check_mode: pr_raised
days: 14

csv_report: output/audit_report.csv
xlsx_report: output/audit_report.xlsx
log_file: output/audit.log
progress_file: output/progress.txt
dotenv_file: .env
```

---

### Recipe C: Spring Boot & Gradle Projects (`gradle.properties`)
Audits Spring Boot or Kotlin projects where versions are tracked in `gradle.properties` or `build.gradle.kts`.
```yaml
repository_discovery_mode: github_org
github_organization: my-spring-org
repository_name_filters: []

author_filters:
  - developer_login

branches:
  - main

property_files:
  - gradle.properties
  - project.properties
  - build.gradle.kts

property_match_mode: exact_filename
version_key: springBootVersion      # Or: version, applicationVersion
version_check_mode: pr_raised
days: 30

csv_report: output/audit_report.csv
xlsx_report: output/audit_report.xlsx
log_file: output/audit.log
progress_file: output/progress.txt
```

---

### Recipe D: Discover Repositories by Developer Activity
Discovers and audits only the repositories where specific developers made commits within the lookback window.
```yaml
repository_discovery_mode: github_contributor
github_organization: my-org
repository_contributor_filters:
  - ankit
  - "@company.com"
repository_contributor_history_scope: lookback   # 'lookback' (within days) or 'all_history'
days: 7

author_filters:
  - ankit
  - "@company.com"
author_matching_mode: both
author_filters_match_against: both

branches:
  - test
  - preprod

property_file: project.properties
version_key: version
version_check_mode: pr_raised

csv_report: output/audit_report.csv
xlsx_report: output/audit_report.xlsx
log_file: output/audit.log
progress_file: output/progress.txt
```

---

## ⚙️ Complete `config.yaml` Reference Guide

| Configuration Key | What It Does | Options / Valid Values | Default |
|---|---|---|---|
| `root_folder` | Base directory to scan recursively in `local` mode | Any valid folder path | `D:\Cariad\Repos` |
| `repository_discovery_mode` | How repositories are identified | `local`, `github_org`, `github_contributor` | `local` |
| `github_base_url` | GitHub host domain | `github.com` or Enterprise (e.g. `github.mycompany.com`) | `github.com` |
| `github_organization` | Target GitHub organization or username | Any GitHub Org/User name | `CHANGE_ME` |
| `github_token_env` | Name of the environment variable containing the token | String | `GITHUB_TOKEN` |
| `repository_name_filters` | Filters repositories by name substring (case-insensitive) | List of strings (e.g. `["service", "api"]`) or `[]` | `["service"]` |
| `repository_contributor_filters` | Contributor match patterns for `github_contributor` mode | List of strings | `["ankit", "@company.com"]` |
| `repository_contributor_history_scope` | Scope for contributor discovery | `lookback` (within `days`) or `all_history` | `lookback` |
| `days` | Lookback period in days for PR and commit activity | Positive integer | `3` |
| `author_filters` | Target authors to audit | List of strings (usernames or emails) | `["ankit", "@company.com"]` |
| `author_matching_mode` | Which PR participant to match against `author_filters` | `pr_creator`, `commit_author`, `both` | `pr_creator` |
| `author_filters_match_against` | User attributes evaluated | `github_login`, `github_name`, `both` | `both` |
| `branches` | Target destination branches to audit PRs against | List of strings (e.g. `["test", "preprod"]`) | `["test", "preprod"]` |
| `pr_lookup_mode` | PR selection filtering strategy | `created_within_days`, `merged_within_days`, `latest_pr_for_author` | `created_within_days` |
| `pr_state_filter` | PR state filter | `opened_by_author`, `merged_only`, `open_and_merged` | `opened_by_author` |
| `property_file` | Single property file to inspect | Filename string | `project.properties` |
| `property_files` | List of property files inspected in order (first match wins) | List of filenames | `[]` |
| `property_match_mode` | How filename matches paths in repository | `exact_filename`, `endswith_filename` | `exact_filename` |
| `version_key` | Key name for the version in the property file | String (e.g. `version`, `springBootVersion`) | `version` |
| `version_check_mode` | Version audit strategy | `pr_raised`, `pr_merged`, `commit`, `file_author`, `user_activity` | `pr_raised` |
| `version_source_in_pr` | PR commit state to read version from | `merged_head` | `merged_head` |
| `missing_project_properties_behavior` | Value used if property file is not in repo | String | `NA` |
| `contributor_count_mode` | Contributor aggregation logic | `commit_authors_only`, `commit_authors_and_pr_creator` | `commit_authors_and_pr_creator` |
| `jira_sources` | Where to search for Jira keys | `all` (PR title, description, commit messages) | `all` |
| `fetch_before_scan` | Run `git fetch --all --prune` on local repos | `true`, `false` | `true` |
| `log_file` | Execution log file destination | File path | `output/audit.log` |
| `csv_report` | CSV output file destination | File path | `output/audit_report.csv` |
| `xlsx_report` | Excel XLSX output file destination | File path | `output/audit_report.xlsx` |
| `xlsx_realtime_save` | Save Excel workbook after every single PR | `true`, `false` | `true` |
| `xlsx_status_colors` | Apply conditional cell colors (Green/Yellow/Red) | `true`, `false` | `true` |
| `progress_file` | Real-time progress tracker destination | File path | `output/progress.txt` |
| `dotenv_file` | Path to `.env` file | File path | `.env` |

---

## 💻 CLI Command Cheat Sheet

Command-line options override `config.yaml` values without needing to edit the file:

```bash
# 1. Audit local directory with 14-day lookback for author 'ankit'
python git_audit.py --root "/path/to/repos" --repository-discovery-mode local --author ankit --days 14

# 2. Audit GitHub organization for branches 'test' and 'preprod'
python git_audit.py --github-organization myorg --repository-discovery-mode github_org --branches test,preprod

# 3. Audit Spring Boot Gradle project inspecting 'springBootVersion'
python git_audit.py --property-file gradle.properties --version-key springBootVersion

# 4. Filter repositories by name keyword
python git_audit.py --github-organization myorg --repo-filter payment,auth

# 5. Fast local audit without network git fetch
python git_audit.py --root "/path/to/repos" --repository-discovery-mode local --no-fetch

# 6. Specify custom report destinations
python git_audit.py --csv-report my_report.csv --xlsx-report my_report.xlsx --log-file my_audit.log
```

---

## 📊 Output Reports

All reports stream in real-time. If the process is stopped, all rows processed up to that moment remain intact on disk.

1. **`output/audit_report.csv`**: Standard CSV with immediate OS-level `fsync` after every row.
2. **`output/audit_report.xlsx`**: Formatted Excel workbook featuring:
   - Freeze pane on header row (`A2`).
   - AutoFilter enabled across all columns.
   - Autosized column widths with cell padding.
   - Clickable hyperlinks for PR URLs.
   - Conditional color fills:
     - **PASS** → Soft Green (`#D9EAD3`)
     - **REVIEW** → Soft Yellow (`#FFF2CC`)
     - **ERROR** → Soft Red (`#F4CCCC`)
3. **`output/audit.log`**: Detailed log with token masking (`ghp_********`).
4. **`output/progress.txt`**: Real-time progress log tracking execution milestones.

### Output Columns (Exact Order)

| # | Column Name | Description | Example |
|---|---|---|---|
| 1 | `Repository` | Repository name / full path | `org/service-auth` |
| 2 | `Branch` | Target destination branch | `test` |
| 3 | `PRNumber` | Pull Request number | `101` |
| 4 | `PRTitle` | Pull Request title | `[PROJ-101] Bump version` |
| 5 | `PRUrl` | Clickable link to GitHub PR | `https://github.com/org/repo/pull/101` |
| 6 | `PRCreatedBy` | PR creator username | `ankit` |
| 7 | `PRCreatedDate` | Timestamp PR was opened | `2026-10-15T10:00:00Z` |
| 8 | `MergedBy` | User who merged PR | `ankit` |
| 9 | `MergedDate` | Timestamp PR was merged | `2026-10-15T11:30:00Z` |
| 10 | `CommitCount` | Number of commits in PR | `2` |
| 11 | `DistinctContributors` | Unique contributor count | `2` |
| 12 | `ContributorNames` | Semicolon-separated names | `alice;ankit` |
| 13 | `ContributorEmails` | Semicolon-separated emails | `alice@company.com;ankit@company.com` |
| 14 | `JiraIds` | Deduplicated Jira keys | `PROJ-101;AUTH-202` |
| 15 | `ProjectPropertiesPresent` | Property file exists | `YES` / `NO` |
| 16 | `ProjectPropertiesModified` | File changed in PR | `YES` / `NO` |
| 17 | `ProjectPropertiesVersionBeforeMyPR` | Version on base branch before PR | `1.0.0` |
| 18 | `ProjectPropertiesVersionInMyPR` | Version inside the PR | `1.1.0` |
| 19 | `ProjectPropertiesVersionCurrentBranch` | Version currently at target branch HEAD | `1.1.0` |
| 20 | `VersionChangedInMyPR` | Did version increment? | `YES` / `NO` |
| 21 | `VersionAdvancedAfterMyPR` | Did branch move further? | `NO` |
| 22 | `Status` | Overall audit status | `PASS`, `REVIEW`, `ERROR` |
| 23 | `Action` | Recommended next steps | `None` |

---

## 🧪 Local Test Harness

Validate the entire application offline without needing GitHub credentials or an internet connection.

### On macOS / Linux
```bash
bash tests/run_local_test.sh
```

### On Windows
```cmd
tests\run_local_test.bat
```

What the test harness does:
1. Creates a local test Git repository with simulated multi-author commits and version increments.
2. Runs `git_audit.py` in `local` mode.
3. Automatically validates that `audit.log`, `audit_report.csv`, `audit_report.xlsx`, and `progress.txt` exist and contain accurate audit rows.

---

## 🔒 Security & Safe Execution Guarantee

- **Strictly Read-Only**: The tool never executes `git push`, `git commit`, `git merge`, or `git checkout`.
- **Read-Only API**: 100% of GitHub REST API calls are HTTP `GET` requests.
- **Zero Token Leakage**: Tokens are masked in console output, log files, and stack tracebacks (`ghp_********`).
