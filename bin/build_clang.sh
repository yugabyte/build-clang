#!/usr/bin/env bash

set -euo pipefail
# shellcheck source=bin/common.sh
. "${BASH_SOURCE[0]%/*}/common.sh"

exit_handler() {
  local exit_code=$?
  if [[ -f ${log_path} ]]; then
    echo >&2 "Log saved to: $log_path"
  fi
  if [[ $exit_code -ne 0 ]]; then
    echo >&2 "Exit code: $exit_code"
  fi
  exit "$exit_code"
}

do_build() {
  yb_activate_virtualenv "$build_clang_project_root"

  set_pythonpath

  set -x
  python3 "$build_clang_project_root/src/build_clang/build_clang_main.py" "${args[@]}"
}

args=()
is_help=false
while [[ $# -gt 0 ]]; do
  args+=( "$1" )
  case $1 in
    -h|--help)
      is_help=true
    ;;
  esac
  shift
done

log_path=""
if [[ "$is_help" == "true" ]]; then
  do_build
else
  log_dir=~/logs
  mkdir -p "$log_dir"
  log_path=$log_dir/build_clang_$( date +%Y-%m-%dT%H_%M_%S ).log
  trap exit_handler EXIT
  echo >&2 "Logging to $log_path"
  do_build 2>&1 | tee "$log_path"
fi
