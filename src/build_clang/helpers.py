import subprocess
import logging
import os
import pathlib
import hashlib
import time
from typing import List, Any, Dict, Optional
from datetime import datetime


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


def log_info_heading(*args: Any) -> None:
    logging.info("")
    logging.info("-" * 80)
    logging.info(*args)
    logging.info("-" * 80)
    logging.info("")


def dict_set_or_del(d: Any, k: Any, v: Any) -> None:
    """
    Set the value of the given key in a dictionary to the given value, or delete it if the value
    is None.
    """
    if v is None:
        if k in d:
            del d[k]
    else:
        d[k] = v


class EnvVarContext:
    """
    Sets the given environment variables and restores them on exit. A None value means the variable
    is undefined.
    """
    def __init__(self, **env_vars: Any) -> None:
        self.env_vars = env_vars

    def __enter__(self) -> None:
        self.saved_env_vars = {}
        for env_var_name, new_value in self.env_vars.items():
            self.saved_env_vars[env_var_name] = os.environ.get(env_var_name)
            dict_set_or_del(os.environ, env_var_name, new_value)

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        for env_var_name, saved_value in self.saved_env_vars.items():
            dict_set_or_del(os.environ, env_var_name, saved_value)


def which(file_name: str) -> Optional[str]:
    for path in os.environ["PATH"].split(os.pathsep):
        full_path = os.path.join(path, file_name)
        if os.path.exists(full_path) and os.access(full_path, os.X_OK):
            return full_path
    return None


def str_md5(s: str) -> str:
    return hashlib.md5(s.encode('utf-8')).hexdigest()


def get_current_timestamp_str() -> str:
    return datetime.now().strftime('%Y-%m-%dT%H-%M-%S.%f')


BASE36_ALPHABET = (
    ''.join([chr(ord('0') + i) for i in range(0, 10)]) +
    ''.join([chr(ord('a') + i) for i in range(0, 26)])
)

assert len(BASE36_ALPHABET) == 36


def base36encode(number: int) -> str:
    """
    Converts an integer to a base36 string.

    Based on:
    https://stackoverflow.com/questions/1181919/python-base-36-encoding/1181922#1181922
    """
    base36 = ''
    sign = ''

    if number < 0:
        sign = '-'
        number = -number

    if 0 <= number < len(BASE36_ALPHABET):
        return sign + BASE36_ALPHABET[number]

    while number != 0:
        number, i = divmod(number, len(BASE36_ALPHABET))
        base36 = BASE36_ALPHABET[i] + base36

    return base36


def base36timestamp(max_len: int = 7) -> str:
    int_time = int(time.time())
    s = base36encode(int_time)
    assert len(s) <= max_len
    return '0' * (max_len - len(s)) + s
