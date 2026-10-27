#!/usr/bin/env bash
# Stands in for git: a snapshot of the tree taken when a change starts, so /finish can
# scope cleanup and review to what the change touched.
#   start   take the snapshot, keeping an existing one (a change can span sessions)
#   files   list files added (A), modified (M) or deleted (D) since the snapshot
#   diff    unified diff since the snapshot
#   accept  replace the snapshot with the current tree once /finish passes
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
base="$root/.claude/baseline"
excludes=(
  --exclude '/.claude/baseline/' --exclude '/.claude/settings.local.json'
  --exclude '/.venv/' --exclude '/data/' --exclude '/.env'
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.ruff_cache/'
  --exclude 'node_modules/' --exclude '.DS_Store' --exclude '/web/dist/'
)

snapshot() {
  mkdir -p "$base"
  rsync -a --delete --delete-excluded "${excludes[@]}" "$root/" "$base/"
}

changed() {
  [ -d "$base" ] || { echo "no baseline; run: .claude/scripts/changes.sh start" >&2; exit 1; }
  (
    cd "$root"
    find . -type f \
      -not -path './.claude/baseline/*' -not -path './.claude/settings.local.json' \
      -not -path './.venv/*' -not -path './data/*' -not -name '.env' \
      -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -not -path '*/.ruff_cache/*' \
      -not -path '*/node_modules/*' -not -name '.DS_Store' -not -path './web/dist/*' | sed 's|^\./||' | while read -r f; do
      if [ ! -f "$base/$f" ]; then echo "A $f"
      elif ! cmp -s "$f" "$base/$f"; then echo "M $f"
      fi
    done
    cd "$base"
    find . -type f | sed 's|^\./||' | while read -r f; do
      [ -f "$root/$f" ] || echo "D $f"
    done
  ) | sort -k2
}

case "${1:-}" in
  start)
    if [ -d "$base" ]; then echo "baseline kept from $(stat -f %Sm "$base")"
    else snapshot && echo "baseline taken"
    fi ;;
  files) changed ;;
  diff)
    changed | while read -r _ f; do
      diff -uN --label "a/$f" --label "b/$f" "$base/$f" "$root/$f" || true
    done ;;
  accept) rm -rf "$base" && snapshot && echo "baseline moved to the current tree" ;;
  *) echo "usage: $0 start|files|diff|accept" >&2; exit 2 ;;
esac
