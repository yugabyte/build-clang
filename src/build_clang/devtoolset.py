import subprocess
import logging
import os

import sys_detection
from sys_detection import is_linux

from build_clang.constants import DEVTOOLSET_ENV_VARS


def activate_devtoolset() -> None:
    if (not is_linux() or
            sys_detection.local_sys_conf().short_os_name_and_version() != 'centos7'):
        return

    found = False
    for devtoolset_number in [11, 10, 9]:
        enable_script_path = f'/opt/rh/devtoolset-{devtoolset_number}/enable'
        if os.path.exists(enable_script_path):
            found = True
            break
    if not found:
        raise ValueError("Could not find an acceptable devtoolset")
    devtoolset_env_str = subprocess.check_output(
        ['bash', '-c', f'. {enable_script_path} && env']).decode('utf-8')

    for line in devtoolset_env_str.split("\n"):
        line = line.strip()
        if not line:
            continue
        k, v = line.split("=", 1)
        if k in DEVTOOLSET_ENV_VARS:
            logging.info("Setting %s to: %s", k, v)
            os.environ[k] = v
