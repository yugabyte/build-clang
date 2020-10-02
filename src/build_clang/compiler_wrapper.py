#!/usr/bin/env python3

import sys
import os
import subprocess
import logging
import json
from build_clang.helpers import str_md5, get_current_timestamp_str
from typing import List, Dict


class CompilerWrapper:
    is_cxx: bool
    args: List[str]

    def __init__(self, is_cxx: bool) -> None:
        self.is_cxx = is_cxx
        self.args = sys.argv

    def run(self) -> None:
        if self.is_cxx:
            underlying_compiler_path = os.environ['BUILD_CLANG_UNDERLYING_CXX_COMPILER']
            language = 'C++'
        else:
            underlying_compiler_path = os.environ['BUILD_CLANG_UNDERLYING_C_COMPILER']
            language = 'C'

        os.environ['CCACHE_COMPILER'] = underlying_compiler_path
        args = sys.argv[1:]
        compiler_path_and_args = [underlying_compiler_path] + args

        logging.info("Running %s compiler: %s", language, compiler_path_and_args)
        compiler_invocation_file_path = os.path.join(
            os.environ['BUILD_CLANG_COMPILER_INVOCATIONS_DIR'],
            'compiler_invocation_%s_%s.json' % (
                get_current_timestamp_str(),
                str_md5(' '.join(compiler_path_and_args))))

        invocation_dict = {
            'compiler': underlying_compiler_path,
            'args': args,
            'directory': os.getcwd()
        }
        with open(compiler_invocation_file_path, 'w') as invocation_file:
            json.dump(invocation_dict, invocation_file, indent=2)
        subprocess.check_call(['ccache', 'compiler'] + args)


def run_compiler_wrapper(is_cxx: bool) -> None:
    compiler_wrapper = CompilerWrapper(is_cxx=is_cxx)
    compiler_wrapper.run()


def get_cmake_args_for_compiler_wrapper() -> Dict[str, str]:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return dict(
        CMAKE_C_COMPILER=os.path.join(base_dir, 'compiler_wrapper_cc.py'),
        CMAKE_CXX_COMPILER=os.path.join(base_dir, 'compiler_wrapper_cxx.py')
    )


if __name__ == '__main__':
    pass
