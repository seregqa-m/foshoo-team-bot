#!/usr/bin/env bash
# Run on the developer machine. Secrets and the old DB are sent separately.
set -euo pipefail
cd "$(dirname "$0")/.."
domain="${1:-}"
if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ || "$domain" != *.* ]]; then
    echo 'Usage: bash scripts/package-selectel.sh app.your-domain.ru' >&2
    exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    echo 'Release refused: commit changes and resolve untracked files first (git status --short).' >&2
    exit 1
fi
revision=$(git rev-parse HEAD)
project_dir=$PWD
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
# Build from the recorded commit, never from mutable working-tree files.
git archive "$revision" backend deploy frontend | tar -xf - -C "$stage"
test -d "$project_dir/frontend/node_modules"
ln -s "$project_dir/frontend/node_modules" "$stage/frontend/node_modules"
CI=true REACT_APP_API_URL="https://$domain" npm --prefix "$stage/frontend" run build
printf '%s\n' "$revision" > "$stage/REVISION"
COPYFILE_DISABLE=1 tar -czf "$stage/release.tar.gz" -C "$stage" \
    --exclude='*.db*' --exclude='*.sqlite*' --exclude='.env*' \
    --exclude='credentials*.json' --exclude='links.json' \
    backend deploy frontend/build REVISION
# Do not publish an artifact if the checkout changed while the build ran.
if [[ "$(git rev-parse HEAD)" != "$revision" || -n "$(git status --porcelain --untracked-files=all)" ]]; then
    echo 'Release refused: checkout changed during the build.' >&2
    exit 1
fi
mkdir -p dist
mv "$stage/release.tar.gz" dist/foshoo-selectel.tar.gz
cp "$stage/REVISION" dist/REVISION
echo 'Ready: dist/foshoo-selectel.tar.gz (code, static frontend, deployment templates; no production data).'
