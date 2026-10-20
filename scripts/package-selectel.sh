#!/usr/bin/env bash
# Run on the developer machine. Secrets and the old DB are sent separately.
set -euo pipefail
cd "$(dirname "$0")/.."
domain="${1:-}"
if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ || "$domain" != *.* ]]; then
    echo 'Usage: bash scripts/package-selectel.sh app.your-domain.ru' >&2
    exit 1
fi
CI=true REACT_APP_API_URL="https://$domain" npm --prefix frontend run build
mkdir -p dist
file_list=$(mktemp)
trap 'rm -f "$file_list"' EXIT
git ls-files --cached --others --exclude-standard -z -- backend deploy > "$file_list"
git rev-parse HEAD > dist/REVISION
COPYFILE_DISABLE=1 tar -czf dist/foshoo-selectel.tar.gz \
    --exclude='*.db*' --exclude='*.sqlite*' --exclude='.env*' \
    --exclude='credentials*.json' --exclude='links.json' \
    --null -T "$file_list" frontend/build -C dist REVISION
echo 'Ready: dist/foshoo-selectel.tar.gz (code, static frontend, deployment templates; no production data).'
