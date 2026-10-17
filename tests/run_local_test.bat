@echo off
setlocal enabledelayedexpansion

echo ==================================================
echo RUNNING LOCAL TEST HARNESS FOR GIT-AUDIT-TOOL
echo ==================================================

:: Set paths relative to repository root
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
cd /d "%PROJECT_ROOT%"

echo 1. Creating local test repository...
python tests\create_test_repo.py test_repos
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create test repository!
    exit /b 1
)

echo 2. Running git-audit-tool against local test repository...
python git_audit.py --root "%PROJECT_ROOT%\test_repos" --repository-discovery-mode local --days 30 --branches test,preprod --no-fetch
if %ERRORLEVEL% neq 0 (
    echo [ERROR] git-audit-tool execution failed with exit code %ERRORLEVEL%!
    exit /b 1
)

echo 3. Validating required audit output files...

set OUTPUT_DIR=output
set AUDIT_LOG=%OUTPUT_DIR%\audit.log
set AUDIT_CSV=%OUTPUT_DIR%\audit_report.csv
set AUDIT_XLSX=%OUTPUT_DIR%\audit_report.xlsx
set PROGRESS_TXT=%OUTPUT_DIR%\progress.txt

if not exist "%AUDIT_LOG%" (
    echo [ERROR] Missing expected log file: %AUDIT_LOG%
    exit /b 1
)
echo [OK] Found %AUDIT_LOG%

if not exist "%AUDIT_CSV%" (
    echo [ERROR] Missing expected CSV report: %AUDIT_CSV%
    exit /b 1
)
echo [OK] Found %AUDIT_CSV%

if not exist "%AUDIT_XLSX%" (
    echo [ERROR] Missing expected XLSX report: %AUDIT_XLSX%
    exit /b 1
)
echo [OK] Found %AUDIT_XLSX%

if not exist "%PROGRESS_TXT%" (
    echo [ERROR] Missing expected progress file: %PROGRESS_TXT%
    exit /b 1
)
echo [OK] Found %PROGRESS_TXT%

echo ==================================================
echo LOCAL TEST HARNESS COMPLETED SUCCESSFULLY!
echo All output reports and logs verified.
echo ==================================================
exit /b 0
