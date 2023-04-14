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

  set +u  # Because args could be empty.
  (
    set -x
    python3 "$build_clang_project_root/src/build_clang/build_clang_main.py" "${args[@]}"
  )
  set -u
}

if [[ -z ${YB_TARGET_ARCH:-} ]]; then
  if is_apple_silicon; then
    YB_TARGET_ARCH=arm64
  else
    YB_TARGET_ARCH=$( uname -m )
  fi
fi
export YB_TARGET_ARCH

if [[ $OSTYPE == darwin* ]]; then
  # On macOS, add the Homebrew bin directory corresponding to the target architecture to the PATH.
  if [[ $YB_TARGET_ARCH == "x86_64" ]]; then
    export PATH=/usr/local/bin:$PATH
  elif [[ $YB_TARGET_ARCH == "arm64" ]]; then
    export PATH=/usr/homebrew/bin:$PATH
  fi
fi

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
