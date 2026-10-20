#!/usr/bin/env bash
# On the existing Selectel server, as root:
# bash update-selectel.sh /tmp/foshoo-selectel.tar.gz
set -Eeuo pipefail
umask 077

archive="${1:?Usage: bash update-selectel.sh /path/to/foshoo-selectel.tar.gz}"
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 1; }
test -f "$archive"
test -f /etc/foshoo.env
test -f /var/lib/foshoo/theater_bot.db
test -d /opt/foshoo/backend
command -v rsync >/dev/null
/opt/foshoo/.venv/bin/python -c 'import sys, pyexpat; assert sys.prefix != sys.base_prefix and sys.version_info >= (3, 10)'

stage=$(mktemp -d /opt/foshoo-update.XXXXXX)
trap 'rm -rf "$stage"' EXIT
tar -xzf "$archive" -C "$stage"
test -f "$stage/backend/main.py"
test -f "$stage/frontend/build/index.html"
test -f "$stage/REVISION"
revision=$(cat "$stage/REVISION")
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
if ! cmp -s "$stage/backend/requirements.txt" /opt/foshoo/backend/requirements.txt; then
    echo 'Dependencies changed. Prepare and verify the server virtualenv before applying this release.' >&2
    exit 1
fi
/opt/foshoo/.venv/bin/python -m pip check

backup="/var/backups/foshoo/$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:7}"
mkdir -p "$backup"
chmod 700 "$backup"
# Make the code/static backups before stopping the bot.
cp -a /opt/foshoo/backend "$backup/backend"
cp -a /opt/foshoo/frontend/build "$backup/build"
cp -a /var/www/foshoo "$backup/web"
cp -a /etc/foshoo.env "$backup/foshoo.env"
if [[ -f /opt/foshoo/REVISION ]]; then cp /opt/foshoo/REVISION "$backup/REVISION"; fi

rollback() {
    trap - ERR
    echo "Update failed; restoring code and frontend from $backup" >&2
    systemctl stop foshoo || true
    rsync -a --delete "$backup/backend/" /opt/foshoo/backend/
    rsync -a --delete "$backup/build/" /opt/foshoo/frontend/build/
    rsync -a --delete "$backup/web/" /var/www/foshoo/
    if [[ -f "$backup/REVISION" ]]; then
        cp "$backup/REVISION" /opt/foshoo/REVISION
    else
        rm -f /opt/foshoo/REVISION
    fi
    # These migrations are additive. Never rewind votes received after startup.
    # The consistent DB snapshot is available for a separately reviewed restore.
    systemctl start foshoo || true
    echo "DB snapshot retained at $backup/theater_bot.db; live DB was not rewound." >&2
    exit 1
}
trap rollback ERR
systemctl stop foshoo
/opt/foshoo/.venv/bin/python - "$backup/theater_bot.db" <<'PY'
import sqlite3
import sys
with sqlite3.connect("file:/var/lib/foshoo/theater_bot.db?mode=ro", uri=True) as source:
    with sqlite3.connect(sys.argv[1]) as destination:
        source.backup(destination)
        assert destination.execute("PRAGMA quick_check").fetchone()[0] == "ok"
PY

# Preserve any server-only secrets/data, including legacy local files.
rsync -a --delete --exclude='.env*' --exclude='credentials*.json' \
    --exclude='links.json' --exclude='*.db*' --exclude='*.sqlite*' \
    "$stage/backend/" /opt/foshoo/backend/
rsync -a --delete "$stage/frontend/build/" /opt/foshoo/frontend/build/
rsync -a "$stage/deploy/" /opt/foshoo/deploy/
chown -R foshoo:foshoo /opt/foshoo/backend /opt/foshoo/frontend/build /opt/foshoo/deploy

# Keep previous hashed assets for tabs still running the previous bundle.
# Publish index.html only once all new assets are in place.
rsync -a --exclude=index.html "$stage/frontend/build/" /var/www/foshoo/
chmod -R a+rX /var/www/foshoo
install -m 644 "$stage/frontend/build/index.html" /var/www/foshoo/index.html.next
mv /var/www/foshoo/index.html.next /var/www/foshoo/index.html
install -m 644 "$stage/REVISION" /opt/foshoo/REVISION
systemctl start foshoo
healthy=false
for attempt in {1..20}; do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/health > "$stage/health.json"; then
        healthy=true
        break
    fi
    sleep 1
done
[[ "$healthy" == true ]]
systemctl is-active --quiet foshoo
trap - ERR
printf 'Installed %s\nBackup: %s\n' "$revision" "$backup"
cat "$stage/health.json"
