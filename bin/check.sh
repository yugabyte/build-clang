#!/usr/bin/env bash

set -euo pipefail
. "${BASH_SOURCE%/*}/common.sh"

yb_activate_virtualenv "$build_clang_project_root"

set_pythonpath

"$build_clang_project_root/src/build_clang/check_python_code.py"