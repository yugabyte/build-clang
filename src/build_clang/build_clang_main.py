#!/usr/bin/env python3

import argparse
import subprocess
import logging
import os

from typing import Any, Optional, Dict, List

from build_clang import remote_build
from build_clang.git_helpers import git_clone_tag
from build_clang.helpers import mkdir_p, ChangeDir, run_cmd, multiline_str_to_list
from build_clang.file_downloader import FileDownloader
from build_clang.cmake_installer import get_cmake_path


LLVM_REPO_URL = 'https://github.com/llvm/llvm-project.git'
LLVM_VERSION = '10.0.0'
LLVM_TAG = 'llvmorg-%s' % LLVM_VERSION


DEVTOOLSET_ENV_VARS = set(multiline_str_to_list("""
    INFOPATH
    LD_LIBRARY_PATH
    MANPATH
    PATH
    PCP_DIR
    PERL5LIB
    PKG_CONFIG_PATH
    PYTHONPATH
"""))

LLVM_ENABLE_PROJECTS = multiline_str_to_list("""
    clang
    clang-tools-extra
    compiler-rt
    libcxx
    libcxxabi
    libunwind
    lld
""")


def cmake_vars_to_args(vars: Dict[str, str]) -> List[str]:
    return ['-D%s=%s' % (k, v) for (k, v) in vars.items()]


def activate_devtoolset() -> None:
    devtoolset_env_str = subprocess.check_output(
        ['bash', '-c', '. /opt/rh/devtoolset-8/enable && env']).decode('utf-8')

    for line in devtoolset_env_str.split("\n"):
        line = line.strip()
        if not line:
            continue
        k, v = line.split("=", 1)
        if k in DEVTOOLSET_ENV_VARS:
            logging.info("Setting %s to: %s", k, v)
            os.environ[k] = v


class ClangBuilder:
    args: Any
    llvm_parent_dir: str

    def __init__(self) -> None:
        self.llvm_parent_dir = os.path.join(
            '/opt/yb-build/llvm',
            'llvm-v%s' % LLVM_VERSION)

    def parse_args(self) -> None:
        parser = argparse.ArgumentParser(description='Build Clang')
        parser.add_argument(
            '--remote_server', help='Server to build on',
            default=os.getenv('BUILD_CLANG_REMOTE_SERVER'))
        parser.add_argument(
            '--remote_build_scripts_path',
            help='Remote directory for the build-clang project repo',
            default=os.getenv('BUILD_CLANG_REMOTE_BUILD_SCRIPTS_PATH'))
        parser.add_argument(
            '--llvm_checkout_path',
            help='Directory where to check out the llvm-project tree')
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Clean the build directory before the build')

        self.args = parser.parse_args()

    def get_install_prefix(self, stage: int) -> str:
        return os.path.join(self.get_stage_base_dir(stage), 'installed')

    def get_llvm_cmake_variables(
            self,
            stage: int) -> Dict[str, str]:
        install_prefix = self.get_install_prefix(stage)
        vars = dict(
            LLVM_ENABLE_PROJECTS=';'.join(LLVM_ENABLE_PROJECTS),
            CMAKE_INSTALL_PREFIX=install_prefix,
            CMAKE_BUILD_TYPE='Release',
            LLVM_TARGETS_TO_BUILD='X86',
            # '-DLLVM_BUILD_EXAMPLES=ON',
            LLVM_CCACHE_BUILD='ON',
            LLVM_CCACHE_MAXSIZE='100G',
            LLVM_CCACHE_DIR=os.path.expanduser('~/.ccache-llvm'),
            CLANG_DEFAULT_CXX_STDLIB='libc++',
            CLANG_DEFAULT_RTLIB='compiler-rt',
            LIBCXXABI_USE_LLVM_UNWINDER='ON'
        )
        if stage > 1:
            prev_stage_install_prefix = self.get_install_prefix(stage - 1)
            vars.update(
                CMAKE_C_COMPILER=os.path.join(prev_stage_install_prefix, 'bin', 'clang'),
                CMAKE_CXX_COMPILER=os.path.join(prev_stage_install_prefix, 'bin', 'clang++'),
            )
        return vars

    def get_stage_base_dir(self, stage: int) -> str:
        return os.path.join(self.llvm_parent_dir, 'stage-%d' % stage)

    def run(self) -> None:
        if os.getenv('BUILD_CLANG_REMOTELY') == '1':
            remote_build.build_remotely(
                remote_server=self.args.remote_server,
                remote_build_scripts_path=self.args.remote_build_scripts_path,
                # TODO: make this an argument?
                remote_mkdir=False
            )
            return

        cmake_path = get_cmake_path()

        llvm_checkout_path = self.args.llvm_checkout_path

        if not llvm_checkout_path:
            llvm_checkout_path = os.path.expanduser(
                os.path.join(self.llvm_parent_dir, 'src', 'llvm-project'))
            logging.info("Using LLVM checkout directory %s by default", llvm_checkout_path)

        activate_devtoolset()

        git_clone_tag(LLVM_REPO_URL, LLVM_TAG, llvm_checkout_path)
        llvm_src_path = os.path.join(llvm_checkout_path, 'llvm')

        for stage in [1, 2]:
            stage_base_dir: str = self.get_stage_base_dir(stage)
            cmake_build_dir: str = os.path.join(stage_base_dir, 'build')
            if self.args.clean and os.path.isdir(cmake_build_dir):
                run_cmd(['rm', '-rf', cmake_build_dir])

            mkdir_p(cmake_build_dir)
            with ChangeDir(cmake_build_dir):
                cmake_vars = self.get_llvm_cmake_variables(stage)
                run_cmd([
                    cmake_path,
                    '-G', 'Ninja',
                    '-S', os.path.join(llvm_checkout_path, 'llvm')
                ] + cmake_vars_to_args(cmake_vars))

                #     '-S', llvm_src_path,
                #     '-DLLVM_ENABLE_PROJECTS=%s' % ';'.join(LLVM_ENABLE_PROJECTS),
                #     '-DCMAKE_INSTALL_PREFIX=%s' % llvm_install_prefix,
                #     '-DCMAKE_BUILD_TYPE=Release',
                #     '-DLLVM_TARGETS_TO_BUILD=X86',
                #     # '-DLLVM_BUILD_TESTS=ON',
                #     # '-DLLVM_BUILD_EXAMPLES=ON',
                #     '-DLLVM_CCACHE_BUILD=ON',
                #     '-DLLVM_CCACHE_MAXSIZE=100G',
                #     '-DBOOTSTRAP_LLVM_ENABLE_LLD=ON',
                #     '-DLLVM_CCACHE_DIR=%s' % os.path.expanduser('~/.ccache-llvm')
                # ])

                run_cmd(['ninja'])
                run_cmd(['ninja', 'install'])


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(filename)s:%(lineno)d] %(asctime)s %(levelname)s: %(message)s")

    builder = ClangBuilder()
    builder.parse_args()
    builder.run()


if __name__ == '__main__':
    main()
