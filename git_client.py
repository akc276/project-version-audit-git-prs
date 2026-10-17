"""
Local git client interface executing Git commands safely via subprocess.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from models import CommitInfo, PRInfo


logger = logging.getLogger("git_audit.git_client")


class GitClientError(Exception):
    """Exception raised when a git CLI command fails."""
    pass


class GitClient:
    """Wrapper around local git CLI operations."""

    def __init__(self, repo_path: Path) -> None:
        self.repo_path = Path(repo_path).resolve()

    def run_cmd(self, args: List[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        """Execute a git command within the repository directory."""
        cmd = ["git"] + args
        logger.debug("Executing git in %s: %s", self.repo_path, " ".join(cmd))
        try:
            res = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=check,
            )
            return res
        except subprocess.CalledProcessError as ex:
            logger.debug("Git command failed [%s]: %s", " ".join(cmd), ex.stderr.strip())
            raise GitClientError(f"Git command failed: {' '.join(cmd)}\nError: {ex.stderr.strip()}") from ex
        except FileNotFoundError as ex:
            logger.error("Git binary not found on system PATH: %s", ex)
            raise GitClientError("Git executable not found in PATH") from ex

    def is_git_repo(self) -> bool:
        """Check if target path is a valid git repository."""
        if not self.repo_path.exists():
            return False
        try:
            res = self.run_cmd(["rev-parse", "--is-inside-work-tree"], check=False)
            if res.returncode == 0 and res.stdout.strip() == "true":
                return True
            # Check for bare repo
            res_bare = self.run_cmd(["rev-parse", "--is-bare-repository"], check=False)
            return res_bare.returncode == 0 and res_bare.stdout.strip() == "true"
        except Exception:
            return False

    def fetch_all(self) -> bool:
        """Run git fetch --all --prune to synchronize references."""
        logger.info("Fetching all remotes for %s", self.repo_path)
        try:
            res = self.run_cmd(["fetch", "--all", "--prune"], check=False)
            return res.returncode == 0
        except Exception as ex:
            logger.warning("Failed to fetch remotes in %s: %s", self.repo_path, ex)
            return False

    def get_remote_url(self, remote_name: str = "origin") -> Optional[str]:
        """Fetch remote URL for origin or first available remote."""
        try:
            res = self.run_cmd(["remote", "get-url", remote_name], check=False)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
            # Try listing all remotes
            res_list = self.run_cmd(["remote"], check=False)
            remotes = [r.strip() for r in res_list.stdout.splitlines() if r.strip()]
            if remotes:
                res_first = self.run_cmd(["remote", "get-url", remotes[0]], check=False)
                if res_first.returncode == 0:
                    return res_first.stdout.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def parse_github_owner_repo(remote_url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse owner and repository name from git remote URL.
        Supports:
          - https://github.com/owner/repo.git
          - git@github.com:owner/repo.git
          - ssh://git@host:port/owner/repo.git
        """
        if not remote_url:
            return None, None
        url = remote_url.strip()

        # SSH pattern: git@github.com:owner/repo.git
        ssh_match = re.search(r"[:/]([A-Za-z0-9_\-\.]+)/([A-Za-z0-9_\-\.]+?)(?:\.git)?$", url)
        if ssh_match:
            owner, repo = ssh_match.group(1), ssh_match.group(2)
            return owner, repo
        return None, None

    def get_current_branch(self) -> Optional[str]:
        """Returns the currently active branch name."""
        try:
            res = self.run_cmd(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
            if res.returncode == 0:
                branch = res.stdout.strip()
                return branch if branch != "HEAD" else None
        except Exception:
            pass
        return None

    def branch_exists(self, branch_name: str) -> bool:
        """Check if branch exists locally or on remote."""
        clean = branch_name.strip()
        candidates = [clean, f"origin/{clean}", f"refs/heads/{clean}", f"refs/remotes/origin/{clean}"]
        for c in candidates:
            res = self.run_cmd(["rev-parse", "--verify", c], check=False)
            if res.returncode == 0:
                return True
        return False

    def get_commit_sha(self, ref: str) -> Optional[str]:
        """Resolves a ref (branch, tag, SHA) to its 40-character commit SHA."""
        candidates = [ref, f"origin/{ref}"]
        for c in candidates:
            res = self.run_cmd(["rev-parse", c], check=False)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        return None

    def get_file_content_at_ref(self, ref: str, file_path: str) -> Optional[str]:
        """
        Reads content of a file at a specific git ref using git show.
        Returns None if the file does not exist at that ref.
        """
        # Normalize file path with forward slashes for git
        normalized_path = file_path.replace("\\", "/").lstrip("/")
        # Try both ref:path and origin/ref:path
        refs_to_try = [ref]
        if not ref.startswith("origin/") and len(ref) != 40:
            refs_to_try.append(f"origin/{ref}")

        for r in refs_to_try:
            spec = f"{r}:{normalized_path}"
            res = self.run_cmd(["show", spec], check=False)
            if res.returncode == 0:
                return res.stdout
        return None

    def list_files_in_ref(self, ref: str) -> List[str]:
        """List all tracked file paths in a given git ref."""
        candidates = [ref]
        if not ref.startswith("origin/") and len(ref) != 40:
            candidates.append(f"origin/{ref}")
        for r in candidates:
            res = self.run_cmd(["ls-tree", "-r", "--name-only", r], check=False)
            if res.returncode == 0:
                return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return []

    def get_changed_files_between_refs(self, base_ref: str, head_ref: str) -> List[str]:
        """List filenames modified between base_ref and head_ref."""
        res = self.run_cmd(["diff", "--name-only", f"{base_ref}...{head_ref}"], check=False)
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        # Fallback to direct two-dot diff
        res_direct = self.run_cmd(["diff", "--name-only", base_ref, head_ref], check=False)
        if res_direct.returncode == 0:
            return [line.strip() for line in res_direct.stdout.splitlines() if line.strip()]
        return []

    def get_commits_between_refs(self, base_ref: str, head_ref: str) -> List[CommitInfo]:
        """Retrieve CommitInfo list for commits in head_ref not in base_ref."""
        delimiter = "<|DELIM|>"
        format_str = f"%H{delimiter}%an{delimiter}%ae{delimiter}%ad{delimiter}%s"
        cmd = ["log", f"{base_ref}..{head_ref}", f"--pretty=format:{format_str}", "--date=iso-strict"]
        res = self.run_cmd(cmd, check=False)
        if res.returncode != 0:
            return []

        commits: List[CommitInfo] = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(delimiter)
            if len(parts) >= 5:
                sha, name, email, dt, msg = parts[0], parts[1], parts[2], parts[3], parts[4]
                commits.append(CommitInfo(
                    sha=sha,
                    author_name=name,
                    author_email=email,
                    author_login=name,
                    message=msg,
                    date=dt,
                ))
        return commits

    def discover_local_simulated_prs(self, target_branches: List[str], days_lookback: int) -> List[PRInfo]:
        """
        In local mode without active GitHub API, discover pull requests by analyzing git merge commits
        (e.g., 'Merge pull request #101', 'Merge branch feature/... into test') across target branches.
        """
        logger.info("Scanning local git history for merge commits and branch PRs in %s", self.repo_path)
        prs: List[PRInfo] = []
        seen_prs = set()

        for branch in target_branches:
            if not self.branch_exists(branch):
                continue
            head_sha = self.get_commit_sha(branch)
            if not head_sha:
                continue

            # Query merge commits on branch
            delim = "<|GITDELIM|>"
            fmt = f"%H{delim}%P{delim}%an{delim}%ae{delim}%ad{delim}%B"
            res = self.run_cmd(["log", "--merges", f"-n", "50", f"--pretty=format:{fmt}", "--date=iso-strict", branch], check=False)
            if res.returncode != 0:
                continue

            # Split raw log entries
            entries = res.stdout.split("\n\n")
            for entry in entries:
                lines = entry.strip().splitlines()
                if not lines:
                    continue
                header = lines[0]
                body = "\n".join(lines[1:]) if len(lines) > 1 else ""
                parts = header.split(delim)
                if len(parts) < 6:
                    continue

                commit_sha = parts[0]
                parents = parts[1].split()
                author_name = parts[2]
                author_email = parts[3]
                date_str = parts[4]
                full_msg = f"{parts[5]}\n{body}".strip()

                if len(parents) < 2:
                    continue
                base_parent = parents[0]
                head_parent = parents[1]

                # Match "Merge pull request #123 from org/branch" or similar
                pr_num_match = re.search(r"Merge pull request #(\d+)", full_msg, re.IGNORECASE)
                if pr_num_match:
                    pr_num = int(pr_num_match.group(1))
                    title = full_msg.splitlines()[0]
                else:
                    # Synthetic PR number from commit SHA hash if merge commit doesn't specify PR number
                    pr_num = int(commit_sha[:6], 16) % 100000 + 1
                    title = full_msg.splitlines()[0]

                pr_key = (branch, pr_num)
                if pr_key in seen_prs:
                    continue
                seen_prs.add(pr_key)

                # Fetch commits between base parent and head parent
                pr_commits = self.get_commits_between_refs(base_parent, head_parent)
                changed_files = self.get_changed_files_between_refs(base_parent, head_parent)

                # Simulated GitHub PR URL
                remote_url = self.get_remote_url()
                owner, repo = self.parse_github_owner_repo(remote_url)
                if owner and repo:
                    pr_url = f"https://github.com/{owner}/{repo}/pull/{pr_num}"
                else:
                    repo_name = self.repo_path.name
                    pr_url = f"https://github.com/local/{repo_name}/pull/{pr_num}"

                prs.append(PRInfo(
                    number=pr_num,
                    title=title,
                    url=pr_url,
                    creator_login=author_name,
                    creator_name=author_name,
                    created_at=date_str,
                    merged_by_login=author_name,
                    merged_at=date_str,
                    state="closed",
                    base_branch=branch,
                    base_sha=base_parent,
                    head_branch="merged",
                    head_sha=head_parent,
                    is_merged=True,
                    body=body,
                    commits=pr_commits,
                    changed_files=changed_files,
                ))

        return prs
