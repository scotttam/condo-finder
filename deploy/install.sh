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
"$UV" run --frozen --no-dev python manage.py migrate --noinput
"$UV" run --frozen --no-dev python manage.py collectstatic --noinput

sed -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" -e "s#__UV__#$UV#g" "deploy/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Condo Finder is running at http://$(scutil --get LocalHostName).local:8000"
