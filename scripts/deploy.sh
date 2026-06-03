#!/usr/bin/env bash
# HMS Ubuntu deploy: git pull → makemigrations → migrate → restart gunicorn
# Run on the server: bash scripts/deploy.sh   (or: chmod +x scripts/deploy.sh && ./scripts/deploy.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# --- config (override in scripts/deploy.env) ---
ENV_FILE="$SCRIPT_DIR/deploy.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

GUNICORN_SERVICE="${GUNICORN_SERVICE:-gunicorn}"
GIT_BRANCH="${GIT_BRANCH:-main}"
if [[ -z "${DEPLOY_SUDO_PASSWORD:-}" ]]; then
  echo "ERROR: Create scripts/deploy.env with DEPLOY_SUDO_PASSWORD (see deploy.env.example)"
  exit 1
fi

echo "==> Project: $PROJECT_DIR"
echo "==> Git pull ($GIT_BRANCH)..."
git fetch origin
git checkout "$GIT_BRANCH" 2>/dev/null || true
git pull origin "$GIT_BRANCH"

# Activate virtualenv if present
if [[ -f "$PROJECT_DIR/venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/venv/bin/activate"
elif [[ -f "$PROJECT_DIR/.venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/.venv/bin/activate"
else
  echo "WARN: No venv found; using system python"
fi

echo "==> makemigrations..."
python manage.py makemigrations --noinput

echo "==> migrate..."
python manage.py migrate --noinput

echo "==> Restart $GUNICORN_SERVICE..."
echo "$DEPLOY_SUDO_PASSWORD" | sudo -S systemctl restart "$GUNICORN_SERVICE"
echo "$DEPLOY_SUDO_PASSWORD" | sudo -S systemctl status "$GUNICORN_SERVICE" --no-pager -l || true

echo "==> Deploy finished successfully."
