#!/usr/bin/env bash
set -euo pipefail

echo "Installing Skyrict git hooks..."

# Check pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "pre-commit not found. Installing..."
    pip install pre-commit
fi

# Install commit-msg hook for conventional commits
pre-commit install
pre-commit install --hook-type commit-msg

echo ""
echo "Hooks installed."
echo "  pre-commit  - runs on every git commit (lint, format, checks)"
echo "  commit-msg  - validates conventional commit format"
echo ""
echo "To run manually:  pre-commit run --all-files"
echo "To skip hooks:    git commit --no-verify (use sparingly)"
