#!/usr/bin/env bash
set -e

echo "=================================================="
echo "RUNNING LOCAL TEST HARNESS FOR GIT-AUDIT-TOOL"
echo "=================================================="

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "1. Creating local test repository..."
python3 tests/create_test_repo.py test_repos

echo "2. Running git-audit-tool against local test repository..."
python3 git_audit.py --root "$PROJECT_ROOT/test_repos" --repository-discovery-mode local --days 30 --branches test,preprod --no-fetch

echo "3. Validating required audit output files..."
OUTPUT_DIR="output"
AUDIT_LOG="$OUTPUT_DIR/audit.log"
AUDIT_CSV="$OUTPUT_DIR/audit_report.csv"
AUDIT_XLSX="$OUTPUT_DIR/audit_report.xlsx"
PROGRESS_TXT="$OUTPUT_DIR/progress.txt"

if [ ! -f "$AUDIT_LOG" ]; then
    echo "[ERROR] Missing expected log file: $AUDIT_LOG"
    exit 1
fi
echo "[OK] Found $AUDIT_LOG"

if [ ! -f "$AUDIT_CSV" ]; then
    echo "[ERROR] Missing expected CSV report: $AUDIT_CSV"
    exit 1
fi
echo "[OK] Found $AUDIT_CSV"

if [ ! -f "$AUDIT_XLSX" ]; then
    echo "[ERROR] Missing expected XLSX report: $AUDIT_XLSX"
    exit 1
fi
echo "[OK] Found $AUDIT_XLSX"

if [ ! -f "$PROGRESS_TXT" ]; then
    echo "[ERROR] Missing expected progress file: $PROGRESS_TXT"
    exit 1
fi
echo "[OK] Found $PROGRESS_TXT"

echo "=================================================="
echo "LOCAL TEST HARNESS COMPLETED SUCCESSFULLY!"
echo "All output reports and logs verified."
echo "=================================================="
