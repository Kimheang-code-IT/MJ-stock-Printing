#!/usr/bin/env bash
# Clone the repository from GitHub and build it on this computer (no GHCR image pull).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Kimheang-code-IT/stock_pos.git}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "$1 is not installed. Install Git and Docker, then run this script again." >&2
    exit 1
  }
}

need git
need docker

# This script lives in infrastructure/scripts/ -> repo root is two levels up.
script_dir="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
repo_root_candidate="$(CDPATH= cd -- "$script_dir/../.." && pwd)"
if [[ -d "$repo_root_candidate/backend" ]]; then
  root="$repo_root_candidate"
elif [[ -n "${INSTALL_DIR:-}" ]]; then
  root="$INSTALL_DIR"
else
  root="${HOME}/stock_pos"
fi

if [[ ! -f "$root/infrastructure/docker-compose.yml" ]]; then
  echo "Cloning $REPO_URL -> $root"
  git clone "$REPO_URL" "$root"
elif [[ "$SKIP_GIT_PULL" != "1" ]]; then
  echo "Updating $root"
  git -C "$root" pull --ff-only
fi

infra="$root/infrastructure"
cd "$infra"

if [[ ! -f .env ]]; then
  echo "Missing infrastructure/.env."
  echo "Run: pwsh -File \"$infra/scripts/init-env.ps1\"  (or copy .env.local.example to .env and fill CHANGE_ME values)." >&2
  exit 1
fi

export IMAGE_TAG=local
export PULL_POLICY=build

echo "Building and starting from source (no app image pull)..."
docker compose -f docker-compose.yml up -d --build --pull missing

frontend_port="$(awk -F= '/^FRONTEND_PORT=/{print $2}' .env | tr -d '\r' || true)"
frontend_port="${frontend_port:-80}"

docker compose -f docker-compose.yml ps
echo
echo "Stock & POS is starting on this computer."
echo "  App:   http://localhost:${frontend_port}"
echo "  Login: see SEED_ADMIN_* in infrastructure/.env"
echo
echo "Logs: docker compose logs -f frontend api"
