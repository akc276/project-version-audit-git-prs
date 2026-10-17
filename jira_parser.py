"""
Jira issue ID extraction utility for git-audit-tool.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional


# Standard enterprise Jira issue key regex pattern: e.g. PROJ-1234, ABC2-987
JIRA_REGEX = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


class JiraParser:
    """Parser to extract and format Jira IDs from pull request metadata and commits."""

    @staticmethod
    def extract_ids_from_text(text: Optional[str]) -> List[str]:
        """Extract all Jira issue keys from a single text block."""
        if not text:
            return []
        matches = JIRA_REGEX.findall(text)
        return [m.strip() for m in matches if m.strip()]

    @classmethod
    def extract_and_format(
        cls,
        title: Optional[str] = None,
        description: Optional[str] = None,
        commit_messages: Optional[Iterable[str]] = None,
    ) -> str:
        """
        Extracts Jira IDs from title, description, and commit messages.
        Deduplicates values preserving first-seen order, returned as a semicolon-separated string.
        Returns 'NA' if no Jira IDs are detected.
        """
        seen = set()
        ordered_ids: List[str] = []

        # Check PR Title
        for jid in cls.extract_ids_from_text(title):
            if jid not in seen:
                seen.add(jid)
                ordered_ids.append(jid)

        # Check PR Description
        for jid in cls.extract_ids_from_text(description):
            if jid not in seen:
                seen.add(jid)
                ordered_ids.append(jid)

        # Check Commit Messages
        if commit_messages:
            for msg in commit_messages:
                for jid in cls.extract_ids_from_text(msg):
                    if jid not in seen:
                        seen.add(jid)
                        ordered_ids.append(jid)

        if not ordered_ids:
            return "NA"

        return ";".join(ordered_ids)
