#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"

Write-Host "Installing Skyrict git hooks..." -ForegroundColor Cyan

# Check pre-commit is installed
if (-not (Get-Command pre-commit -ErrorAction SilentlyContinue)) {
    Write-Host "pre-commit not found. Installing..." -ForegroundColor Yellow
    pip install pre-commit
}

# Install hooks
pre-commit install
pre-commit install --hook-type commit-msg

Write-Host ""
Write-Host "Hooks installed." -ForegroundColor Green
Write-Host "  pre-commit  - runs on every git commit (lint, format, checks)"
Write-Host "  commit-msg  - validates conventional commit format"
Write-Host ""
Write-Host "To run manually:  pre-commit run --all-files"
Write-Host "To skip hooks:    git commit --no-verify (use sparingly)"
