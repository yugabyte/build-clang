set -euo pipefail

set_pythonpath() {
  export PYTHONPATH=$build_clang_project_root/src
}

if [[ $BASH_SOURCE == $0 ]]; then
  echo "$BASH_SOURCE must be sourced, not executed" >&2
  exit 1
fi

build_clang_project_root=$( cd "${BASH_SOURCE%/*}" && cd .. && pwd )
if [[ ! -d $build_clang_project_root/yugabyte-bash-common ||
      -z "$( ls -A "$build_clang_project_root/yugabyte-bash-common" )" ]]; then
  ( cd "$build_clang_project_root"; git submodule update --init --recursive )
fi

. "$build_clang_project_root/yugabyte-bash-common/src/yugabyte-bash-common.sh"
