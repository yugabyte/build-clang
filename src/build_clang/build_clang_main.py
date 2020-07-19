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


class ClangBuildConf:
    version: str
    llvm_parent_dir_for_specific_version: str
    llvm_project_clone_dir: str
    cmake_executable_path: str

    def __init__(self, version: str) -> None:
        self.version = version
        self.llvm_parent_dir_for_specific_version = os.path.join(
            '/opt/yb-build/llvm',
            'llvm-v%s' % version)
        self.llvm_project_clone_dir = os.path.join(
            self.llvm_parent_dir_for_specific_version, 'src', 'llvm-project')
        self.cmake_executable_path = get_cmake_path()


class ClangBuildStage:
    # Build configuration. The same for all stages.
    build_conf: ClangBuildConf

    stage_number: int

    # Previous stage, e.g. stage 1 if this is stage 2, or None for stage 1.
    prev_stage: Optional['ClangBuildStage']

    # Base directory for this stage's directories.
    stage_base_dir: str

    # Directory that CMake will generate Ninja files in and where the build will run for this stage.
    cmake_build_dir: str

    # Installation prefix. The destination directory of "ninja install".
    install_prefix: str

    def __init__(
            self,
            build_conf: ClangBuildConf,
            stage_number: int,
            prev_stage: Optional['ClangBuildStage']) -> None:
        # Fields based directly on the parameters.
        self.build_conf = build_conf
        self.stage_number = stage_number
        self.prev_stage = prev_stage
        if self.prev_stage is not None:
            assert self.prev_stage.stage_number != self.stage_number

        # Computed fields.
        self.stage_base_dir = os.path.join(
            self.build_conf.llvm_parent_dir_for_specific_version,
            'stage-%d' % self.stage_number)
        self.cmake_build_dir = os.path.join(self.stage_base_dir, 'build')
        self.install_prefix = os.path.join(self.stage_base_dir, 'installed')

    def get_llvm_cmake_variables(self) -> Dict[str, str]:
        """
        See https://llvm.org/docs/CMake.html for the full list of possible options.
        """
        ON = 'ON'
        vars = dict(
            LLVM_ENABLE_PROJECTS=';'.join(LLVM_ENABLE_PROJECTS),
            CMAKE_INSTALL_PREFIX=self.install_prefix,
            CMAKE_BUILD_TYPE='Release',
            LLVM_TARGETS_TO_BUILD='X86',
            LLVM_CCACHE_BUILD=ON,
            LLVM_CCACHE_MAXSIZE='100G',
            LLVM_CCACHE_DIR=os.path.expanduser('~/.ccache-llvm'),
            CLANG_DEFAULT_CXX_STDLIB='libc++',
            CLANG_DEFAULT_RTLIB='compiler-rt',
            LIBCXXABI_USE_LLVM_UNWINDER=ON
        )
        if self.prev_stage is not None:
            assert self.prev_stage is not self
            prev_stage_install_prefix = self.prev_stage.install_prefix
            vars.update(
                CMAKE_C_COMPILER=os.path.join(prev_stage_install_prefix, 'bin', 'clang'),
                CMAKE_CXX_COMPILER=os.path.join(prev_stage_install_prefix, 'bin', 'clang++'),
                LLVM_ENABLE_LLD=ON,
                LLVM_ENABLE_LIBCXX=ON,
                LLVM_ENABLE_LTO='Full',
                LLVM_BUILD_TESTS=ON
            )

        return vars

    def build(self) -> None:
        mkdir_p(self.cmake_build_dir)
        with ChangeDir(self.cmake_build_dir):
            cmake_vars = self.get_llvm_cmake_variables()
            run_cmd([
                self.build_conf.cmake_executable_path,
                '-G', 'Ninja',
                '-S', os.path.join(self.build_conf.llvm_project_clone_dir, 'llvm')
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


class ClangBuilder:
    args: Any
    llvm_parent_dir: str
    stages: List[ClangBuildStage]
    build_conf: ClangBuildConf

    def __init__(self) -> None:
        self.build_conf = ClangBuildConf(version='10.0.0')
        self.stages = []

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
            '--clean',
            action='store_true',
            help='Clean the build directory before the build')

        self.args = parser.parse_args()

    def init_stages(self) -> None:
        prev_stage: Optional[ClangBuildStage] = None
        for stage_number in [1, 2]:
            self.stages.append(ClangBuildStage(
                build_conf=self.build_conf,
                stage_number=stage_number,
                prev_stage=prev_stage))
            prev_stage = self.stages[-1]

    def run(self) -> None:
        if os.getenv('BUILD_CLANG_REMOTELY') == '1':
            remote_build.build_remotely(
                remote_server=self.args.remote_server,
                remote_build_scripts_path=self.args.remote_build_scripts_path,
                # TODO: make this an argument?
                remote_mkdir=False
            )
            return

        logging.info("Using LLVM checkout directory %s", self.build_conf.llvm_project_clone_dir)

        activate_devtoolset()

        git_clone_tag(
            LLVM_REPO_URL,
            'llvmorg-%s' % self.build_conf.version,
            self.build_conf.llvm_project_clone_dir)

        self.init_stages()

        for stage in self.stages:
            if stage.stage_number == 1:
                continue
            stage.build()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(filename)s:%(lineno)d] %(asctime)s %(levelname)s: %(message)s")

    builder = ClangBuilder()
    builder.parse_args()
    builder.run()


if __name__ == '__main__':
    main()
