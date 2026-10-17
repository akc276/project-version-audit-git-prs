"""
Utility functions for logging, secret masking, date calculations, and string matching.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import logging
import os
from pathlib import Path
import re
from typing import Any, Iterable, Optional


# Pattern matching GitHub tokens and common authentication bearer values
TOKEN_REGEX = re.compile(
    r"(gh[pousr]_[A-Za-z0-9_]{10,}|github_pat_[A-Za-z0-9_]{20,}|bearer\s+[A-Za-z0-9_\-\.]{10,})",
    re.IGNORECASE,
)


def mask_token(token: Optional[str]) -> str:
    """
    Mask a token value safely for logging or console display.
    Example: ghp_123456789 becomes ghp_********.
    """
    if not token:
        return "[NOT SET]"
    token_str = str(token).strip()
    if len(token_str) <= 6:
        return "******"
    if token_str.startswith("ghp_") or token_str.startswith("gho_") or token_str.startswith("ghu_"):
        prefix = token_str[:4]
        return f"{prefix}********"
    if token_str.startswith("github_pat_"):
        return "github_pat_********"
    # General mask: keep first 3 and last 2 characters
    return f"{token_str[:3]}...{token_str[-2:]}"


class SecretMaskingFilter(logging.Filter):
    """Logging filter that scrubs tokens and auth credentials from all log records."""

    def __init__(self, raw_tokens: Optional[Iterable[str]] = None) -> None:
        super().__init__()
        self.exact_secrets = [t.strip() for t in (raw_tokens or []) if t and len(t.strip()) > 3]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # Replace exact known tokens
        for sec in self.exact_secrets:
            if sec in msg:
                masked = mask_token(sec)
                msg = msg.replace(sec, masked)

        # Scrub regex patterns
        def _replace_token_match(match: re.Match[str]) -> str:
            full_match = match.group(0)
            if full_match.lower().startswith("bearer "):
                raw_tok = full_match.split(None, 1)[1]
                return f"Bearer {mask_token(raw_tok)}"
            return mask_token(full_match)

        cleaned_msg = TOKEN_REGEX.sub(_replace_token_match, msg)
        record.msg = cleaned_msg
        record.args = ()
        return True


class SecretMaskingFormatter(logging.Formatter):
    """Formatter that scrubs secrets from both formatted messages and exception tracebacks."""

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        raw_tokens: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.exact_secrets = [t.strip() for t in (raw_tokens or []) if t and len(t.strip()) > 3]

    def _scrub(self, text: str) -> str:
        for sec in self.exact_secrets:
            if sec in text:
                text = text.replace(sec, mask_token(sec))

        def _replace_token_match(match: re.Match[str]) -> str:
            full_match = match.group(0)
            if full_match.lower().startswith("bearer "):
                raw_tok = full_match.split(None, 1)[1]
                return f"Bearer {mask_token(raw_tok)}"
            return mask_token(full_match)

        return TOKEN_REGEX.sub(_replace_token_match, text)

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return self._scrub(formatted)


def setup_logging(log_file_path: Path, token_to_mask: Optional[str] = None) -> logging.Logger:
    """
    Initializes root logger with both console and file handlers, applying secret masking.
    """
    log_file_path = Path(log_file_path)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("git_audit")
    logger.setLevel(logging.DEBUG)

    # Clear existing handlers to prevent duplicate logging
    if logger.hasHandlers():
        logger.handlers.clear()

    secrets = [token_to_mask] if token_to_mask else []
    mask_filter = SecretMaskingFilter(secrets)
    formatter = SecretMaskingFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        raw_tokens=secrets,
    )

    # Console handler (INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(mask_filter)
    logger.addHandler(console_handler)

    # File handler (DEBUG and above)
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(mask_filter)
    logger.addHandler(file_handler)

    return logger


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO8601 timestamp string into timezone-aware UTC datetime."""
    if not dt_str:
        return None
    try:
        # Standardize Z suffix to UTC offset
        clean_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_within_days(dt_str: Optional[str], days: int, reference_time: Optional[datetime] = None) -> bool:
    """
    Returns True if the given ISO date string occurred within the last `days` days.
    """
    dt = parse_iso_datetime(dt_str)
    if dt is None:
        return False
    ref = reference_time or datetime.now(timezone.utc)
    cutoff = ref - timedelta(days=days)
    return dt >= cutoff


def matches_any_filter(target_text: Optional[str], filters: Iterable[str]) -> bool:
    """
    Checks if target_text matches any filter pattern (case-insensitive substring match).
    """
    if not target_text:
        return False
    target_lower = target_text.strip().lower()
    for flt in filters:
        flt_clean = flt.strip().lower()
        if not flt_clean:
            continue
        if flt_clean in target_lower:
            return True
    return False
