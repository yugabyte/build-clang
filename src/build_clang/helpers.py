import subprocess
import logging
from typing import List, Any


def run_cmd(args: List[Any]) -> None:
    logging.info("Running command: %s", args)
    subprocess.check_call(args)
