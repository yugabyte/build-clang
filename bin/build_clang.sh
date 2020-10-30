#!/usr/bin/env bash

set -euo pipefail
. "${BASH_SOURCE%/*}/common.sh"

yb_activate_virtualenv "$build_clang_project_root"

set_pythonpath

python3 "$build_clang_project_root/src/build_clang/build_clang_main.py" "$@"