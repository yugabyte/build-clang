#!/usr/bin/env bash

set -euo pipefail
. "${BASH_SOURCE%/*}/common.sh"

yb_activate_virtualenv "$build_clang_project_root"

mypy_config_path=$build_clang_project_root/mypy.ini
if [[ ! -f $mypy_config_path ]]; then
  fatal "mypy configuration file not found: $mypy_config_path"
fi

while IFS= read -r -d '' python_file_path; do
  log "Checking if '$python_file_path' compiles"
  python3 -m py_compile "$python_file_path"
  echo >&2

  base_name=${python_file_path##*/}
  base_name=${base_name%.py}
  log "Trying to import '$python_file_path'"
  ( set -x; python3 -c "from build_clang import $base_name" )
  echo >&2

  log "Type-checking '$python_file_path'"
  mypy --config-file "$mypy_config_path" "$python_file_path"
  echo >&2

  log "Checking coding style in '$python_file_path'"
  pycodestyle "$python_file_path"
  echo >&2
done< <(find "$build_clang_project_root/src/build_clang" -name "*.py" -type f -print0)
