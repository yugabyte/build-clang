from sys_detection import is_macos
from typing import List, Set, Tuple

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


def get_architectures_of_file(file_path: str) -> Tuple[Set[str], str]:
    """
    Returns a list of architectures that the specified executable is built for.

    Parses the output of the "file" command. In the simplest case we will get a single like this:

    <file_path>: Mach-O 64-bit dynamically linked shared library x86_64
    or
    <file_path>: Mach-O 64-bit executable x86_64

    However, in the more complicated cases, we may get:

    <file_path>: Mach-O universal binary with 3 architectures: [...]
    <file_path> (for architecture x86_64): Mach-O 64-bit dynamically linked shared library x86_64
    <file_path> (for architecture x86_64h): Mach-O 64-bit dynamically linked shared library x86_64h
    <file_path> (for architecture arm64):  Mach-O 64-bit dynamically linked shared library arm64

    For files that are not native executables, we may get e.g.:

    <file_path>: Python script text executable, ASCII text
    """
    file_cmd_output = subprocess.check_output(
        ['file', file_path]).strip().decode('utf-8')
    if 'Python script' in file_cmd_output or 'ASCII' in file_cmd_output:
        return set(), file_cmd_output
    arch_set: Set[str] = set()
    for line in file_cmd_output.split('\n'):
        items = line.strip().split()
        last_item = items[-1]
        for arch in MACOS_CPU_ARCHITECTURES:
            if last_item.startswith(arch):
                arch_set.add(arch)
    return arch_set, file_cmd_output


def validate_build_output_arch(target_arch: str, top_dir: str) -> None:
    if not is_macos():
        return
    other_macos_arch = get_other_macos_arch(target_arch)
    disallowed_suffix = ' ' + other_macos_arch
    logging.info(
        "Verifying achitecture of object files and libraries in %s (should be %s)",
        top_dir, target_arch)
    files_of_interest = subprocess.check_output([
            'find', top_dir, '-type', 'f', '-and', '(',
            '-name', '*.o', '-or',
            '-name', '*.dylib', '-or',
            '-perm', '+111',
            ')',
            '-and', '-not', '-name', '*.css',
            '-and', '-not', '-name', '*.py'
        ]).strip().decode('utf-8').split('\n')
    errors_found = False

    num_one_arch = 0
    num_multi_arch = 0
    num_errors = 0

    for file_of_interest in files_of_interest:
        arch_set, file_cmd_output = get_architectures_of_file(file_of_interest)
        if len(arch_set) == 0:
            logging.warning("File %s is not a native executable, skipping", file_of_interest)
            continue
        if target_arch not in arch_set:
            logging.error(
                "File %s is not built for the correct architecture %s "
                "(found arhictectures: %s). Output of the file command:\n%s",
                file_of_interest, target_arch, sorted(arch_set), file_cmd_output)
            num_errors += 1
        if len(arch_set) == 1:
            num_one_arch += 1
        else:
            num_multi_arch += 1

    logging.info(
        "Verified the architecture of %d files in %s. Found %d files with just one architecture "
        "(%s), %d files with more than one architecture, %d errors.",
        len(files_of_interest), top_dir, num_one_arch, target_arch, num_multi_arch, num_errors)
    if num_errors > 0:
        raise ValueError(
            "Found %d files with the wrong architecture in %s (target architecture: %s)" % (
                num_errors, top_dir, target_arch))
