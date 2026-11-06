#!/usr/bin/env bash
set -euo pipefail
if [ $# -lt 3 ]; then
  echo "usage: $0 <project 1|2> <c-project-dir> <crust-rust-crate-dir> [max-iterations]" >&2
  exit 2
fi
: "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY first}"
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
cd "$(dirname "$0")/.."
extra=""
[ $# -ge 4 ] && extra="--max-iterations $4"
python3 src/pipeline.py --project "$1" --c-dir "$2" --rust-template "$3" $extra
