import subprocess
import logging
import os

import sys_detection

from typing import Tuple, Optional

from sys_detection import is_linux

from build_clang.constants import DEVTOOLSET_ENV_VARS
from build_clang.helpers import which


GCC_VERSIONS = [14, 13, 12, 11, 10, 9]


def activate_devtoolset() -> None:
    if (not is_linux() or
            sys_detection.local_sys_conf().short_os_name_and_version() != 'centos7'):
        return

    found = False
    for devtoolset_number in GCC_VERSIONS:
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


def find_default_gcc() -> Tuple[Optional[str], Optional[str]]:
    return which('gcc'), which('g++')


def find_latest_gcc() -> Tuple[Optional[str], Optional[str]]:
    """
    Finds the latest GCC version installed in /usr/bin. For use with Amazon Linux 2.
    """

    if (not is_linux() or
            sys_detection.local_sys_conf().short_os_name_and_version() != 'amzn2'):
        return find_default_gcc()

    bin_dir = '/usr/bin'
    for gcc_version in GCC_VERSIONS:
        cc_path = os.path.join(bin_dir, f'gcc{gcc_version}-gcc')
        cxx_path = os.path.join(bin_dir, f'gcc{gcc_version}-g++')
        if os.path.exists(cc_path) and os.path.exists(cxx_path):
            return cc_path, cxx_path

    return find_default_gcc()
