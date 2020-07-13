import subprocess
import logging
import os
from typing import List, Any


BUILD_CLANG_SCRIPTS_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _validate_build_clang_scripts_root_path() -> None:
    for sub_dir in [
        'bin',
        'src',
        'venv',
        'yugabyte-bash-common'
    ]:
        dir_that_must_exist = os.path.join(BUILD_CLANG_SCRIPTS_ROOT_PATH, sub_dir)
        if not os.path.isdir(dir_that_must_exist):
            raise IOError("Directory does not exist: %s" % dir_that_must_exist)


def run_cmd(args: List[Any]) -> None:
    logging.info("Running command: %s", args)
    subprocess.check_call(args)


# from https://stackoverflow.com/questions/431684/how-do-i-change-the-working-directory-in-python
class ChangeDir:
    saved_path: str
    new_path: str

    """Context manager for changing the current working directory"""
    def __init__(self, new_path: str) -> None:
        self.new_path = new_path

    def __enter__(self) -> None:
        self.saved_path = os.getcwd()
        os.chdir(self.new_path)

    def __exit__(self, etype: Any, value: Any, traceback: Any) -> None:
        os.chdir(self.saved_path)


_validate_build_clang_scripts_root_path()
