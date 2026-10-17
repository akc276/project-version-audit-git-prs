"""
Test harness helper to create a reproducible local Git repository for validation.
Populates realistic branches, project.properties version changes, Jira IDs, and multi-author commits.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


def run_git(args: list[str], cwd: Path) -> str:
    """Execute git command within repo folder and return stdout."""
    res = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def create_test_repository(base_dir: Path) -> Path:
    """
    Initializes a local git repository simulating PRs and version updates.
    """
    repo_dir = base_dir / "service-payment-gateway"
    if repo_dir.exists():
        print(f"Cleaning existing test repository at {repo_dir}")
        shutil.rmtree(repo_dir, ignore_errors=True)

    repo_dir.mkdir(parents=True, exist_ok=True)
    print(f"Initializing test Git repository at {repo_dir}...")

    # Git init
    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Test Harness"], cwd=repo_dir)
    run_git(["config", "user.email", "ci@company.com"], cwd=repo_dir)
    run_git(["config", "commit.gpgsign", "false"], cwd=repo_dir)

    # 1. Initial Commit on main
    prop_file = repo_dir / "project.properties"
    prop_file.write_text(
        "# Payment Gateway Properties\n"
        "service.name=payment-gateway\n"
        "version=1.0.0\n",
        encoding="utf-8",
    )
    readme = repo_dir / "README.md"
    readme.write_text("# Payment Gateway Service\n", encoding="utf-8")

    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit: v1.0.0 [PROJ-100]"], cwd=repo_dir)

    # 2. Create 'test' and 'preprod' branches
    run_git(["branch", "test"], cwd=repo_dir)
    run_git(["branch", "preprod"], cwd=repo_dir)

    # 3. Simulate PR on 'test' branch
    # Checkout branch test
    run_git(["checkout", "test"], cwd=repo_dir)

    # Create feature branch for PR #101
    run_git(["checkout", "-b", "feature/PROJ-101-auth-enhancement"], cwd=repo_dir)

    # Author 1: ankit makes commit with version bump and Jira ID
    prop_file.write_text(
        "# Payment Gateway Properties\n"
        "service.name=payment-gateway\n"
        "version=1.1.0\n",
        encoding="utf-8",
    )
    run_git(["add", "project.properties"], cwd=repo_dir)
    run_git(
        [
            "-c", "user.name=ankit",
            "-c", "user.email=ankit@company.com",
            "commit", "-m", "[PROJ-101] Upgrade authentication flow and bump version to 1.1.0",
        ],
        cwd=repo_dir,
    )

    # Author 2: alice adds a second commit to the same PR
    auth_src = repo_dir / "AuthService.java"
    auth_src.write_text("// AuthService implementation\npublic class AuthService {}\n", encoding="utf-8")
    run_git(["add", "AuthService.java"], cwd=repo_dir)
    run_git(
        [
            "-c", "user.name=alice",
            "-c", "user.email=alice@company.com",
            "commit", "-m", "[PROJ-101] Refactor AuthService token parsing [AUTH-202]",
        ],
        cwd=repo_dir,
    )

    # Checkout 'test' and merge feature branch with PR merge commit message
    run_git(["checkout", "test"], cwd=repo_dir)
    run_git(
        [
            "-c", "user.name=ankit",
            "-c", "user.email=ankit@company.com",
            "merge", "--no-ff", "feature/PROJ-101-auth-enhancement",
            "-m", "Merge pull request #101 from feature/PROJ-101-auth-enhancement\n\nPROJ-101: Upgraded auth flow and version",
        ],
        cwd=repo_dir,
    )

    # 4. Simulate a second PR on 'preprod' branch without version bump (PASS/REVIEW check)
    run_git(["checkout", "preprod"], cwd=repo_dir)
    run_git(["checkout", "-b", "feature/PROJ-105-hotfix"], cwd=repo_dir)

    hotfix_file = repo_dir / "Hotfix.txt"
    hotfix_file.write_text("Hotfix patch applied\n", encoding="utf-8")
    run_git(["add", "Hotfix.txt"], cwd=repo_dir)
    run_git(
        [
            "-c", "user.name=ankit",
            "-c", "user.email=ankit@company.com",
            "commit", "-m", "[PROJ-105] Fix edge-case in checkout retry",
        ],
        cwd=repo_dir,
    )

    run_git(["checkout", "preprod"], cwd=repo_dir)
    run_git(
        [
            "-c", "user.name=ankit",
            "-c", "user.email=ankit@company.com",
            "merge", "--no-ff", "feature/PROJ-105-hotfix",
            "-m", "Merge pull request #102 from feature/PROJ-105-hotfix\n\nPROJ-105: Applied checkout patch",
        ],
        cwd=repo_dir,
    )

    # Switch back to main
    run_git(["checkout", "main"], cwd=repo_dir)

    print("Successfully created test repository structure:")
    print(f"  Repo path: {repo_dir}")
    print("  Branches: main, test, preprod")
    print("  Simulated PRs: #101 (version bumped), #102 (no version bump)")

    return repo_dir


if __name__ == "__main__":
    target_base = Path(__file__).resolve().parent.parent / "test_repos"
    if len(sys.argv) > 1:
        target_base = Path(sys.argv[1])
    create_test_repository(target_base)
