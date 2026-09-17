#!/usr/bin/env bash
# Wait for a URL to return HTTP 200.
#
# Usage:
#   wait-for-health.sh <url> [timeout-seconds]
#
# Used by the E2E CI workflow to wait for the Next.js server on :3100
# (host-side) after `next start` is launched in the background.
set -euo pipefail

URL="${1:?Usage: wait-for-health.sh <url> [timeout-seconds]}"
TIMEOUT="${2:-60}"
DEADLINE=$((SECONDS + TIMEOUT))

until curl -sf "$URL" >/dev/null 2>&1; do
  if ((SECONDS >= DEADLINE)); then
    echo "TIMED OUT waiting for $URL after ${TIMEOUT}s" >&2
    exit 1
  fi
  sleep 1
done

echo "HEALTHY $URL"