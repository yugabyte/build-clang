import os
from build_clang.helpers import run_cmd, ChangeDir


def git_clone_tag(repo_url: str, tag: str, dest_path: str) -> None:
    dest_path = os.path.abspath(dest_path)
    if not os.path.exists(dest_path):
        run_cmd(['git', 'clone', repo_url, '--branch', tag, '--depth', 1, dest_path])
