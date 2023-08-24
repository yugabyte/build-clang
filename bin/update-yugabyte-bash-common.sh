#!/usr/bin/env bash

set -euo pipefail

project_dir=$( cd "${BASH_SOURCE[0]%/*}"/.. && pwd )
set -euo pipefail

target_sha1=$(<"$project_dir/yugabyte-bash-common-sha1.txt")
if [[ ! $target_sha1 =~ ^[0-9a-f]{40}$ ]]; then
  echo >&2 "Invalid yugabyte-bash-common SHA1: $sha1"
  exit 1
fi
yugabyte_bash_common_dir=$project_dir/yugabyte-bash-common
if [[ ! -d $yugabyte_bash_common_dir ]]; then
  git clone https://github.com/yugabyte/yugabyte-bash-common.git "$yugabyte_bash_common_dir"
fi
cd "$yugabyte_bash_common_dir"
current_sha1=$( git rev-parse HEAD )
if [[ ! $current_sha1 =~ ^[0-9a-f]{40}$ ]]; then
  echo >&2 "Could not get current git SHA1 in $PWD"
  exit 1
fi
if [[ $current_sha1 != $target_sha1 ]]; then
  if ! ( set -x; git checkout "$target_sha1" ); then
    (
      set -x
      git fetch
      git checkout "$target_sha1"
    )
  fi
fi
