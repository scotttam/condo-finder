#!/usr/bin/env bash
# Restart a per-user launchd agent: stop it, wait until launchd has fully removed it, then load it.
# `launchctl bootout` returns before the old process has exited; bootstrapping too early fails with
# "Bootstrap failed: 5: Input/output error". Usage: launchd-restart.sh <label> <plist>
set -euo pipefail

LABEL="$1"
PLIST="$2"
DOMAIN="gui/$(id -u)"
WAIT_SECONDS="${WAIT_SECONDS:-60}"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Stopping $LABEL..."
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  for _ in $(seq "$WAIT_SECONDS"); do
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 1
  done
  if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "$LABEL is still shutting down after ${WAIT_SECONDS}s; try again shortly." >&2
    exit 1
  fi
fi

for attempt in 1 2 3 4 5; do
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
    echo "Started $LABEL."
    exit 0
  fi
  sleep 2
done
launchctl bootstrap "$DOMAIN" "$PLIST"  # final attempt, showing launchctl's error
