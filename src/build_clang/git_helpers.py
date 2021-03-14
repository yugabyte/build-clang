import os
import subprocess
import pathlib
import logging

from build_clang.helpers import run_cmd, ChangeDir
from typing import Optional


CLONE_DEPTH = 10


def git_clone_tag(
        repo_url: str,
        tag: str,
        dest_path: str,
        save_git_log_to: Optional[str] = None) -> None:
    dest_path = os.path.abspath(dest_path)
    if not os.path.exists(dest_path):
        run_cmd(['git', 'clone', repo_url, '--branch', tag, '--depth', CLONE_DEPTH, dest_path])


def save_git_log_to_file(git_repo_dir: str, dest_file_path: str) -> None:
    dest_file_path = os.path.abspath(dest_file_path)

    logging.info("Saving the git log of %s into %s", git_repo_dir, dest_file_path)
    pathlib.Path(os.path.dirname(dest_file_path)).mkdir(parents=True, exist_ok=True)
    git_log_output = subprocess.check_output([
        'git', 'log', '-n', str(CLONE_DEPTH)
    ], cwd=git_repo_dir).decode('utf-8')
    with open(dest_file_path, 'w') as git_log_output_file:
        git_log_output_file.write(git_log_output)
