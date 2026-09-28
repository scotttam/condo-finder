#!/usr/bin/env bash
# Install/refresh the Condo Finder launchd service for the current user.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"
LABEL="com.condofinder.web"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

cd "$PROJECT_DIR"
mkdir -p logs "$HOME/Library/LaunchAgents"
"$UV" sync --frozen --no-dev
"$UV" run --frozen --no-dev playwright install chromium   # RentEngine sources need a real browser
"$UV" run --frozen --no-dev python manage.py migrate --noinput
"$UV" run --frozen --no-dev python manage.py collectstatic --noinput

sed -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" -e "s#__UV__#$UV#g" "deploy/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST"

deploy/launchd-restart.sh "$LABEL" "$PLIST"

echo "Waiting for the app to answer on port 8000..."
for _ in $(seq 60); do
  if curl -fs -o /dev/null http://127.0.0.1:8000/; then
    break
  fi
  sleep 1
done
if ! curl -fs -o /dev/null http://127.0.0.1:8000/; then
  echo "The app didn't respond within 60s. Check: tail -50 $PROJECT_DIR/logs/web.log" >&2
  exit 1
fi
echo "Condo Finder is running."
echo "  Home network: http://$(scutil --get LocalHostName).local:8000"
TAILSCALE="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"
if [ -x "$TAILSCALE" ]; then
  TS_NAME="$("$TAILSCALE" status --json 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
  [ -n "$TS_NAME" ] && echo "  Anywhere (Tailscale): http://$TS_NAME:8000"
fi
