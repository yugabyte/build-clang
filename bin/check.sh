#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=bin/common.sh
. "${BASH_SOURCE[0]%/*}/common.sh"

yb_activate_virtualenv "$build_clang_project_root"

codecheck
