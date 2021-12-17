#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=bin/common.sh
. "${BASH_SOURCE[0]%/*}/common.sh"

log_dir=~/logs
mkdir -p "$log_dir"
log_path=$log_dir/build_clang_$( date +%Y-%m-%dT%H_%M_%S ).log
echo "Logging to $log_path"
(
  yb_activate_virtualenv "$build_clang_project_root"

  set_pythonpath

  set -x
  python3 "$build_clang_project_root/src/build_clang/build_clang_main.py" "$@"
) 2>&1 | tee "$log_path"
echo "Log saved to $log_path"
