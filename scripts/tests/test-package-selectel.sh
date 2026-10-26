#!/usr/bin/env bash
# Offline integration checks for release provenance and dirty-checkout guards.
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/../.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/repo/scripts" "$fixture/repo/backend" "$fixture/repo/deploy" \
    "$fixture/repo/frontend/node_modules" "$fixture/bin"
cp "$project_dir/scripts/package-selectel.sh" "$fixture/repo/scripts/"
cd "$fixture/repo"
git init -q
git config user.name 'Release test'
git config user.email 'release-test@example.invalid'
printf 'dist/\nnode_modules/\nbackend/.env\n' > .gitignore
printf 'committed backend\n' > backend/main.py
printf 'template\n' > deploy/template.txt
printf '{}\n' > frontend/package.json
git add .
git commit -qm 'Fixture'
expected_revision=$(git rev-parse HEAD)
export RELEASE_TEST_REPO=$PWD
export RELEASE_TEST_MARKER="$fixture/build-called"
cat > "$fixture/bin/npm" <<'NPM'
#!/usr/bin/env bash
set -euo pipefail
test "$1" = --prefix
test "$2" != "$RELEASE_TEST_REPO/frontend"
test "$REACT_APP_API_URL" = https://app.example.ru
touch "$RELEASE_TEST_MARKER"
mkdir -p "$2/build"
printf '<html>release fixture</html>\n' > "$2/build/index.html"
if [[ "${RELEASE_TEST_MUTATE:-}" == yes ]]; then
    printf 'changed during build\n' >> "$RELEASE_TEST_REPO/backend/main.py"
fi
NPM
chmod +x "$fixture/bin/npm"
export PATH="$fixture/bin:$PATH"
assert_refused_before_build() {
    if bash scripts/package-selectel.sh app.example.ru > "$fixture/result" 2>&1; then
        echo 'Expected dirty checkout rejection' >&2; exit 1
    fi
    test ! -e "$RELEASE_TEST_MARKER"
    grep -q 'Release refused' "$fixture/result"
}
printf 'unstaged\n' >> backend/main.py
assert_refused_before_build
git add backend/main.py
assert_refused_before_build
git restore --source=HEAD --staged --worktree backend/main.py
printf 'untracked\n' > backend/new.py
assert_refused_before_build
rm backend/new.py
# Ignored local configuration must never enter the release.
printf 'local-only fixture\n' > backend/.env
bash scripts/package-selectel.sh app.example.ru > "$fixture/result" 2>&1
mkdir "$fixture/unpacked"
tar -xzf dist/foshoo-selectel.tar.gz -C "$fixture/unpacked"
test "$(cat "$fixture/unpacked/REVISION")" = "$expected_revision"
cmp backend/main.py "$fixture/unpacked/backend/main.py"
test -f "$fixture/unpacked/frontend/build/index.html"
test ! -e "$fixture/unpacked/backend/.env"
test ! -e "$fixture/unpacked/frontend/node_modules"
cp dist/foshoo-selectel.tar.gz "$fixture/original.tar.gz"
if RELEASE_TEST_MUTATE=yes bash scripts/package-selectel.sh app.example.ru > "$fixture/result" 2>&1; then
    echo 'Expected concurrent edit rejection' >&2; exit 1
fi
grep -q 'checkout changed during the build' "$fixture/result"
cmp dist/foshoo-selectel.tar.gz "$fixture/original.tar.gz"
echo 'PASS: unstaged, staged and untracked changes rejected; committed snapshot packaged; concurrent edit rejected.'
