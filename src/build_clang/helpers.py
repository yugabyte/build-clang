import subprocess
import logging
import os
import pathlib
import hashlib
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


def normalize_cmd_arg(arg: Any) -> Any:
    # Auto-convert ints to strings, but don't convert anything else.
    if isinstance(arg, int):
        return str(arg)
    return arg


def run_cmd(args: List[Any]) -> None:
    args = [normalize_cmd_arg(arg) for arg in args]
    logging.info("Running command: %s (current directory: %s)", args, os.getcwd())
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
        logging.info("Changing directory to: %s", self.new_path)
        os.chdir(self.new_path)

    def __exit__(self, etype: Any, value: Any, traceback: Any) -> None:
        logging.info("Changing directory back to: %s", self.saved_path)
        os.chdir(self.saved_path)


def mkdir_p(dir_path: str) -> None:
    pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)


def rm_rf(dir_path: str) -> None:
    if os.path.exists(dir_path):
        subprocess.check_call(['rm', '-rf', dir_path])


_validate_build_clang_scripts_root_path()


def compute_sha256_checksum(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def multiline_str_to_list(multiline_str: str) -> List[str]:
    lines = multiline_str.strip().split("\n")
    lines = [s.strip() for s in lines]
    return [s for s in lines if s]


def log_info_heading(*args):
    logging.info("")
    logging.info("-" * 80)
    logging.info(*args)
    logging.info("-" * 80)
    logging.info("")