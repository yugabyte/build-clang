import os
import subprocess
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
    if save_git_log_to:
        git_log_output = subprocess.check_output([
            'git', 'log', '-n', str(CLONE_DEPTH)
        ], cwd=dest_path).decode('utf-8')
        with open(save_git_log_to, 'w') as git_log_output_file:
            git_log_output_file.write(git_log_output)
