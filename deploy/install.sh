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
echo "Condo Finder is running on 127.0.0.1:8000. People reach it through Tailscale Funnel."
PUBLIC_URL="$(grep -E '^PUBLIC_URL=' .env 2>/dev/null | cut -d= -f2- || true)"
if [ -n "$PUBLIC_URL" ]; then
  echo "  $PUBLIC_URL"
else
  echo "  PUBLIC_URL isn't set in .env. See README: Going public with Tailscale Funnel." >&2
fi
