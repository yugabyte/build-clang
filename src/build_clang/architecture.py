from sys_detection import is_macos
from typing import List

import logging
import os
import subprocess


MACOS_CPU_ARCHITECTURES = ['x86_64', 'arm64']


def get_arch_switch_cmd_prefix(target_arch: str) -> List[str]:
    """
    Returns a command line prefix that will switch to the target architecture.
    """
    if not is_macos():
        return []
    return ['arch', '-%s' % target_arch]


def get_other_macos_arch(arch: str) -> str:
    assert arch in MACOS_CPU_ARCHITECTURES, 'Not a valid CPU arhcitecture for macOS: %s' % arch
    candidates = []
    for other_arch in MACOS_CPU_ARCHITECTURES:
        if other_arch != arch:
            candidates.append(other_arch)
    if len(candidates) == 1:
        return candidates[0]
    raise ValueError(
        "Could not unambiguously determine the other macOS CPU architecture for %s. "
        "Candidates: %s" % (arch, candidates))


def validate_build_output_arch(target_arch: str, top_dir: str) -> None:
    if not is_macos():
        return
    other_macos_arch = get_other_macos_arch(target_arch)
    disallowed_suffix = ' ' + other_macos_arch
    logging.info(
        "Verifying achitecture of object files and libraries in %s (should be %s)",
        top_dir, target_arch)
    object_files = subprocess.check_output(
            ['find', top_dir, '-name', '*.o', '-or', '-name', '*.dylib']
        ).strip().decode('utf-8').split('\n')
    for object_file_path in object_files:
        file_type = subprocess.check_output(
            ['file', object_file_path]).strip().decode('utf-8')
        if file_type.endswith(disallowed_suffix):
            rel_path = os.path.relpath(object_file_path, top_dir)
            if not f'clang_rt.builtins_{other_macos_arch}' in rel_path:
                raise ValueError(
                    "Incorrect object file architecture generated for %s (%s expected): %s" % (
                        object_file_path, target_arch, file_type))
