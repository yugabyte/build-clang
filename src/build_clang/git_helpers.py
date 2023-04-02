import os
import subprocess
import pathlib
import logging
import sys

from build_clang.helpers import run_cmd, ChangeDir
from typing import Optional


CLONE_DEPTH = 10


def git_clone_tag(
        repo_url: str,
        tag: str,
        dest_path: str,
        save_git_log_to: Optional[str] = None) -> None:
    dest_path = os.path.abspath(dest_path)
    if os.path.exists(dest_path):
        return
    cmd_line = ['git', 'clone', repo_url, '--branch', tag, '--depth', str(CLONE_DEPTH), dest_path]
    p = subprocess.Popen(
        cmd_line,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    sys.stdout.write(stdout.decode('utf-8') + '\n')
    sys.stderr.write(stderr.decode('utf-8') + '\n')
    if p.returncode == 0:
        return
    if (b'attempt to fetch/clone from a shallow repository' in stderr and
            repo_url.startswith('/') and
            os.path.isdir(repo_url)):
        logging.info("git does not support cloning from a shallow repository, just copying")
        subprocess.check_call(['cp', '-R', repo_url, dest_path])
        return

    raise IOError("git command %s exited with code %d" % (cmd_line, p.returncode))


def get_current_git_sha1(repo_path: str) -> str:
    return subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo_path
    ).strip().decode('utf-8')


def save_git_log_to_file(git_repo_dir: str, dest_file_path: str) -> None:
    dest_file_path = os.path.abspath(dest_file_path)

    logging.info("Saving the git log of %s into %s", git_repo_dir, dest_file_path)
    pathlib.Path(os.path.dirname(dest_file_path)).mkdir(parents=True, exist_ok=True)
    git_log_output = subprocess.check_output([
        'git', 'log', '-n', str(CLONE_DEPTH)
    ], cwd=git_repo_dir).decode('utf-8')
    with open(dest_file_path, 'w') as git_log_output_file:
        git_log_output_file.write(git_log_output)
