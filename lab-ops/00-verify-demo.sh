#!/usr/bin/env bash
# Lab ops — verify demo health; restart/relaunch what is broken.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=env.sh
source "$DIR/env.sh"
exec python3 "$TRAINING_ROOT/scripts/verify-demo.py" "$@"
