#!/usr/bin/env bash
# Local preview: regenerate publications whenever publications.bib
# changes, and run `hugo server` alongside it.
#
#   ./scripts/serve.sh
#
# Hugo watches data/publications.json, so a regeneration triggers a
# live reload the same way editing a content file does.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 scripts/bib2json.py

watch_bib() {
  local last
  last=$(stat -f %m publications.bib 2>/dev/null || echo 0)
  while true; do
    sleep 1
    local now
    now=$(stat -f %m publications.bib 2>/dev/null || echo 0)
    if [ "$now" != "$last" ]; then
      last=$now
      python3 scripts/bib2json.py
    fi
  done
}

watch_bib &
WATCHER=$!
trap 'kill $WATCHER 2>/dev/null || true' EXIT

hugo server "$@"
