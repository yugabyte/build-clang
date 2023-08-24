#!/usr/bin/env bash

set -euo pipefail

set_pythonpath() {
  export PYTHONPATH=$build_clang_project_root/src
}

is_apple_silicon() {
  if [[ $OSTYPE == darwin* && $( uname -v ) == *ARM64* ]]; then
    # true
    return 0
  fi

  # false
  return 1
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  echo "${BASH_SOURCE[0]} must be sourced, not executed" >&2
  exit 1
fi

build_clang_project_root=$( cd "${BASH_SOURCE[0]%/*}" && cd .. && pwd )

"${build_clang_project_root}/bin/update-yugabyte-bash-common.sh"

# shellcheck source=yugabyte-bash-common/src/yugabyte-bash-common.sh
. "$build_clang_project_root/yugabyte-bash-common/src/yugabyte-bash-common.sh"
