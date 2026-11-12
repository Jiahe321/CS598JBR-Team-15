#!/usr/bin/env bash
set -euo pipefail
if [ $# -lt 3 ]; then
  echo "usage: $0 <project 1|2> <c-project-dir> <crust-rust-crate-dir> [max-iterations] [pipeline options...]" >&2
  exit 2
fi
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
cd "$(dirname "$0")/.."
project=$1
c_dir=$2
rust_template=$3
shift 3
extra=()
if [ $# -gt 0 ] && [[ "$1" =~ ^[0-9]+$ ]]; then
  extra+=(--max-iterations "$1")
  shift
fi
python3 src/pipeline.py --project "$project" --c-dir "$c_dir" --rust-template "$rust_template" "${extra[@]}" "$@"
