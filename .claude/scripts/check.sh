#!/usr/bin/env bash
# Every check, run to the end so one pass shows every failure. Stands in for CI.
set -uo pipefail
cd "$(dirname "$0")/../.."

[ -f pyproject.toml ] || { echo "no pyproject.toml yet; M0 scaffolds it" >&2; exit 1; }

failed=()
run() {
  echo "== $*"
  "$@" || failed+=("$*")
}

run uv run ruff check .
run uv run ruff format --check .
run uv run pyright
run uv run pytest -m "not live" -q

if command -v bun >/dev/null; then
  run bun install --cwd web --frozen-lockfile
  run bun run --cwd web api:check
  run bun run --cwd web typecheck
  run bun run --cwd web lint
  run bun run --cwd web test
  # Last: `sift run` serves web/dist, so a passing check leaves the app serving this code.
  run bun run --cwd web build
else
  echo "== bun not found: the web app's checks did not run. Install it: brew install oven-sh/bun/bun" >&2
  failed+=("bun (not installed)")
fi

if [ ${#failed[@]} -gt 0 ]; then
  printf 'FAILED: %s\n' "${failed[@]}"
  exit 1
fi
echo "all checks passed"
