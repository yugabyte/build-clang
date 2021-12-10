#!/usr/bin/env python3

import sys
import argparse
import subprocess
import logging
import os
import shutil
import time
import stat
import platform
import sys_detection

from typing import Any, Optional, Dict, List, Tuple

from build_clang import remote_build
from build_clang.git_helpers import (
    git_clone_tag,
    save_git_log_to_file,
    get_current_git_sha1
)
from build_clang.helpers import (
    mkdir_p,
    rm_rf,
    ChangeDir,
    run_cmd,
    multiline_str_to_list,
    log_info_heading,
    EnvVarContext,
    which,
    get_current_timestamp_str,
    BUILD_CLANG_SCRIPTS_ROOT_PATH,
)

from build_clang.compiler_wrapper import get_cmake_args_for_compiler_wrapper


LLVM_REPO_URL = 'https://github.com/yugabyte/llvm-project.git'
NUM_STAGES = 3

# Length of Git SHA1 prefix to be used in directory name.
GIT_SHA1_PREFIX_LENGTH = 8

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

YB_LLVM_ARCHIVE_NAME_PREFIX = 'yb-llvm-'

BUILD_DIR_SUFFIX = 'build'
NAME_COMPONENT_SEPARATOR = '-'
BUILD_DIR_SUFFIX_WITH_SEPARATOR = NAME_COMPONENT_SEPARATOR + BUILD_DIR_SUFFIX

DEFAULT_INSTALL_PARENT_DIR = '/opt/yb-build/llvm'


def cmake_vars_to_args(vars: Dict[str, str]) -> List[str]:
    return ['-D%s=%s' % (k, v) for (k, v) in vars.items()]


def activate_devtoolset() -> None:
    if (not sys_detection.is_linux() or
            sys_detection.local_sys_conf().short_os_name_and_version() != 'centos7'):
        return

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
    install_parent_dir: str
    version: str
    llvm_major_version: int
    user_specified_suffix: Optional[str]
    skip_auto_suffix: bool
    git_sha1_prefix: Optional[str]

    cmake_executable_path: str

    # Whether to delete CMake build directory before the build.
    clean_build: bool

    # A timestamp string for when this confugration was created.
    build_start_timestamp_str: str

    # Whether to use our custom compiler wrapper script instead of the real compiler.
    use_compiler_wrapper: bool

    lto: bool

    unix_timestamp_for_suffix: Optional[str]

    tag_override: Optional[str]

    def __init__(
            self,
            install_parent_dir: str,
            version: str,
            user_specified_suffix: Optional[str],
            skip_auto_suffix: bool,
            clean_build: bool,
            use_compiler_wrapper: bool,
            lto: bool,
            use_compiler_rt: bool,
            existing_build_dir: Optional[str]) -> None:
        self.install_parent_dir = install_parent_dir
        self.version = version
        self.llvm_major_version = int(version.split('.')[0])
        assert self.llvm_major_version >= 7
        self.user_specified_suffix = user_specified_suffix
        self.skip_auto_suffix = skip_auto_suffix
        self.git_sha1_prefix = None

        self.cmake_executable_path = 'cmake'

        self.clean_build = clean_build
        self.build_start_timestamp_str = get_current_timestamp_str()
        self.use_compiler_wrapper = use_compiler_wrapper
        self.use_compiler_rt = use_compiler_rt

        # We store some information about how LLVM was built
        self.lto = lto

        self.unix_timestamp_for_suffix = None

        self.existing_build_dir = existing_build_dir
        self.tag_override = None
        if self.existing_build_dir:
            build_dir_basename = os.path.basename(self.existing_build_dir)
            invalid_msg_prefix = \
                f"Invalid existing build directory basename: '{build_dir_basename}', "
            if not build_dir_basename.endswith(BUILD_DIR_SUFFIX_WITH_SEPARATOR):
                raise ValueError(
                    invalid_msg_prefix +
                    f"does not end with '{BUILD_DIR_SUFFIX_WITH_SEPARATOR}'.")
            if not build_dir_basename.startswith(YB_LLVM_ARCHIVE_NAME_PREFIX):
                raise ValueError(
                    invalid_msg_prefix +
                    f"does not start with '{YB_LLVM_ARCHIVE_NAME_PREFIX}'.")
            self.tag_override = build_dir_basename[
                len(YB_LLVM_ARCHIVE_NAME_PREFIX):-len(BUILD_DIR_SUFFIX_WITH_SEPARATOR)]
        else:
            self.unix_timestamp_for_suffix = str(int(time.time()))

    def get_llvm_build_parent_dir(self) -> str:
        return os.path.join(
            self.install_parent_dir,
            self.get_install_dir_basename() + BUILD_DIR_SUFFIX_WITH_SEPARATOR)

    def get_tag(self) -> str:
        if self.tag_override:
            return self.tag_override

        top_dir_suffix = ''
        if not self.skip_auto_suffix:
            sys_conf = sys_detection.local_sys_conf()
            components = [
                component for component in [
                    self.unix_timestamp_for_suffix,
                    self.git_sha1_prefix or 'GIT_SHA1_PLACEHOLDER',
                    'with-compiler-rt' if self.use_compiler_rt else None,
                    self.user_specified_suffix,
                    sys_conf.short_os_name_and_version(),
                    sys_conf.processor
                ] if component
            ]
            top_dir_suffix = NAME_COMPONENT_SEPARATOR + NAME_COMPONENT_SEPARATOR.join(
                    components)

        return 'v%s%s' % (self.version, top_dir_suffix)

    def get_install_dir_basename(self) -> str:
        return YB_LLVM_ARCHIVE_NAME_PREFIX + self.get_tag()

    def get_final_install_dir(self) -> str:
        return os.path.join(
            self.install_parent_dir,
            self.get_install_dir_basename())

    def get_llvm_build_info_dir(self) -> str:
        return os.path.join(self.get_final_install_dir(), 'etc', 'yb-llvm-build-info')

    def get_llvm_project_clone_dir(self) -> str:
        return os.path.join(self.get_llvm_build_parent_dir(), 'src', 'llvm-project')

    def set_git_sha1(self, git_sha1: str) -> None:
        old_build_parent_dir = self.get_llvm_build_parent_dir()

        self.git_sha1_prefix = git_sha1[:GIT_SHA1_PREFIX_LENGTH]
        logging.info("Git SHA1: %s", git_sha1)
        logging.info("Using git SHA1 prefix: %s", self.git_sha1_prefix)
        logging.info("Renaming %s -> %s", old_build_parent_dir, self.get_llvm_build_parent_dir())
        os.rename(old_build_parent_dir, self.get_llvm_build_parent_dir())


def make_file_executable(file_path: str) -> None:
    """
    Makes the given file executable by owner.
    """
    current_stat = os.stat(file_path)
    os.chmod(file_path, current_stat.st_mode | stat.S_IXUSR)


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

    # We set this when we start building the stage.
    stage_start_timestamp_str: Optional[str]

    is_last_stage: bool

    def __init__(
            self,
            build_conf: ClangBuildConf,
            stage_number: int,
            prev_stage: Optional['ClangBuildStage'],
            is_last_stage: bool) -> None:
        # Fields based directly on the parameters.
        self.build_conf = build_conf
        self.stage_number = stage_number
        self.prev_stage = prev_stage
        if self.prev_stage is not None:
            assert self.prev_stage.stage_number != self.stage_number

        parent_dir_for_llvm_version = self.build_conf.get_llvm_build_parent_dir()

        # Computed fields.
        self.stage_base_dir = os.path.join(
            parent_dir_for_llvm_version, 'stage-%d' % self.stage_number)
        self.cmake_build_dir = os.path.join(self.stage_base_dir, 'build')

        self.compiler_invocations_top_dir = os.path.join(
            self.stage_base_dir, 'compiler_invocations')
        if is_last_stage:
            self.install_prefix = self.build_conf.get_final_install_dir()
        else:
            self.install_prefix = os.path.join(self.stage_base_dir, 'installed')
        self.stage_start_timestamp_str = None
        self.is_last_stage = is_last_stage

    def is_first_stage(self) -> bool:
        return self.prev_stage is None

    def get_llvm_enabled_projects(self) -> List[str]:
        enabled_projects = multiline_str_to_list("""
            clang
            libunwind
            lld
        """)
        if not self.is_first_stage():
           enabled_projects += multiline_str_to_list("""
                compiler-rt
                libcxx
                libcxxabi
            """)
        if self.is_last_stage:
            enabled_projects.append('clang-tools-extra')
            if self.build_conf.llvm_major_version >= 10:
                enabled_projects.append('lldb')
        return sorted(enabled_projects)

    def get_llvm_cmake_variables(self) -> Dict[str, str]:
        """
        See https://llvm.org/docs/CMake.html for the full list of possible options.

        https://raw.githubusercontent.com/llvm/llvm-project/master/llvm/CMakeLists.txt

        https://raw.githubusercontent.com/llvm/llvm-project/master/clang/CMakeLists.txt
        """
        first_stage = self.is_first_stage()
        if not first_stage:
            assert self.prev_stage is not None  # MyPy does not understand this always holds.
            assert self.prev_stage is not self
            assert self.stage_number > 1
            assert not self.prev_stage.is_last_stage

        use_compiler_rt = self.build_conf.use_compiler_rt and not self.is_first_stage()

        vars = dict(
            LLVM_ENABLE_PROJECTS=';'.join(self.get_llvm_enabled_projects()),
            CMAKE_INSTALL_PREFIX=self.install_prefix,
            CMAKE_BUILD_TYPE='Release',
            LLVM_TARGETS_TO_BUILD='X86;AArch64',

            BUILD_SHARED_LIBS=True,

            CMAKE_EXPORT_COMPILE_COMMANDS=True,

            LLVM_ENABLE_RTTI=True,
            LIBCXXABI_USE_COMPILER_RT=use_compiler_rt,
            LIBUNWIND_USE_COMPILER_RT=use_compiler_rt,
            LIBCXX_USE_COMPILER_RT=use_compiler_rt,
        )
        if not self.is_first_stage():
            vars.update(LIBCXXABI_USE_LLVM_UNWINDER=True)

        if self.stage_number >= 2:
            vars.update(CLANG_DEFAULT_CXX_STDLIB='libc++')
        else:
            vars.update(CLANG_DEFAULT_CXX_STDLIB='libstdc++')

        if self.stage_number >= 3:
            vars.update(SANITIZER_ALLOW_CXXABI=True)
        else:
            vars.update(SANITIZER_ALLOW_CXXABI=False)

        # LIBCXX_CXX_ABI=libcxxabi
        # LIBCXX_USE_COMPILER_RT=True
        # LIBCXXABI_USE_LLVM_UNWINDER=True
        # LIBCXXABI_USE_COMPILER_RT=True
        # LIBCXX_HAS_GCC_S_LIB=Off
        # LIBUNWIND_USE_COMPILER_RT=True

        if not first_stage:
            assert self.prev_stage is not None
            prev_stage_install_prefix = self.prev_stage.install_prefix
            prev_stage_cxx_include_dir = os.path.join(
                prev_stage_install_prefix, 'include', 'c++', 'v1')
            prev_stage_cxx_lib_dir = os.path.join(prev_stage_install_prefix, 'lib')

            # extra_cxx_flags = '-I%s' % prev_stage_cxx_include_dir,
            # extra_linker_flags = ' '.join([
            #     '-L%s' % prev_stage_cxx_lib_dir,
            #     '-Wl,-rpath=%s' % prev_stage_cxx_lib_dir
            # ])

            extra_linker_flags = []
            if sys.platform != 'darwin':
                # Disabled this because it inteferes with Yugabyte ASAN/TSAN builds
                # (ubsan/asan runtime end up pulling libc++/libc++abi from this lib directory and
                # not allowing us to use our custom-compiled versions of those libraries.)

                # extra_linker_flags = [
                #     '-Wl,-rpath=%s' % os.path.join(self.install_prefix, 'lib'),
                # ]

                if self.build_conf.use_compiler_rt:
                    extra_linker_flags.append(
                        # To avoid depending on libgcc.a when using Clang's runtime library
                        # compiler-rt. Otherwise building protobuf as part of yugabyte-db-thirdparty
                        # fails to find _Unwind_Resume.
                        # _Unwind_Resume is ultimately defined in /lib64/libgcc_s.so.1.
                        '-Wl,--exclude-libs,libgcc.a'
                    )
                vars.update(LLVM_ENABLE_LLD=True)

            extra_linker_flags_str = ' '.join(extra_linker_flags)
            vars.update(
                LLVM_BUILD_TESTS=True,

                CMAKE_SHARED_LINKER_FLAGS_INIT=extra_linker_flags_str,
                CMAKE_MODULE_LINKER_FLAGS_INIT=extra_linker_flags_str,
                CMAKE_EXE_LINKER_FLAGS_INIT=extra_linker_flags_str,
                # LIBCXX_CXX_ABI_INCLUDE_PATHS=os.path.join(
                #     prev_stage_install_prefix, 'include', 'c++', 'v1')
            )
            if self.stage_number >= 3:
                # Only use libc++ to build LLVM for stage 3 and later, because the previous stage's
                # compiler must have built libc++, and that does not happen for stage 1.
                vars.update(
                    SANITIZER_CXX_ABI='libc++',
                    LLVM_ENABLE_LIBCXX=True,
                )
            else:
                vars.update(LLVM_ENABLE_LIBCXX=False)

            if use_compiler_rt:
                vars.update(CLANG_DEFAULT_RTLIB='compiler-rt')

            if self.build_conf.lto and self.is_last_stage:
                vars.update(LLVM_ENABLE_LTO='Full')

        if self.build_conf.use_compiler_wrapper:
            vars.update(get_cmake_args_for_compiler_wrapper())
        else:
            c_compiler, cxx_compiler = self.get_compilers()
            vars.update(
                CMAKE_C_COMPILER=c_compiler,
                CMAKE_CXX_COMPILER=cxx_compiler
            )
        for k in vars:
            if vars[k] is True:
                vars[k] = 'ON'
            if vars[k] is False:
                vars[k] = 'OFF'
        return vars

    def get_compilers(self) -> Tuple[str, str]:
        if self.stage_number == 1:
            c_compiler = which('gcc')
            cxx_compiler = which('g++')
        else:
            assert self.prev_stage is not None
            prev_stage_install_prefix = self.prev_stage.install_prefix
            c_compiler = os.path.join(prev_stage_install_prefix, 'bin', 'clang')
            cxx_compiler = os.path.join(prev_stage_install_prefix, 'bin', 'clang++')
        assert c_compiler is not None
        assert cxx_compiler is not None
        return c_compiler, cxx_compiler

    def build(self) -> None:
        self.stage_start_timestamp_str = get_current_timestamp_str()
        if os.path.exists(self.cmake_build_dir) and self.build_conf.clean_build:
            logging.info("Deleting directory: %s", self.cmake_build_dir)
            rm_rf(self.cmake_build_dir)

        c_compiler, cxx_compiler = self.get_compilers()

        compiler_invocations_dir = os.path.join(
            self.compiler_invocations_top_dir,
            self.build_conf.build_start_timestamp_str)
        mkdir_p(compiler_invocations_dir)
        mkdir_p(self.cmake_build_dir)
        with ChangeDir(self.cmake_build_dir):
            env_vars = {}
            if self.build_conf.use_compiler_wrapper:
                env_vars = dict(
                    BUILD_CLANG_UNDERLYING_C_COMPILER=c_compiler,
                    BUILD_CLANG_UNDERLYING_CXX_COMPILER=cxx_compiler,
                    BUILD_CLANG_COMPILER_INVOCATIONS_DIR=compiler_invocations_dir
                )
            with EnvVarContext(**env_vars):

                cmake_vars = self.get_llvm_cmake_variables()
                run_cmd([
                    self.build_conf.cmake_executable_path,
                    '-G', 'Ninja',
                    '-S', os.path.join(self.build_conf.get_llvm_project_clone_dir(), 'llvm')
                ] + cmake_vars_to_args(cmake_vars))

                #     '-S', llvm_src_path,
                #     '-DLLVM_ENABLE_PROJECTS=%s' % ';'.join(LLVM_ENABLE_PROJECTS),
                #     '-DCMAKE_INSTALL_PREFIX=%s' % llvm_install_prefix,
                #     '-DCMAKE_BUILD_TYPE=Release',
                #     '-DLLVM_TARGETS_TO_BUILD=X86',
                #     # '-DLLVM_BUILD_TESTS=True',
                #     # '-DLLVM_BUILD_EXAMPLES=True',
                #     '-DLLVM_CCACHE_BUILD=True',
                #     '-DLLVM_CCACHE_MAXSIZE=100G',
                #     '-DBOOTSTRAP_LLVM_ENABLE_LLD=True',
                #     '-DLLVM_CCACHE_DIR=%s' % os.path.expanduser('~/.ccache-llvm')
                # ])

                targets = []
                if not self.is_first_stage():
                    targets = ['compiler-rt', 'cxxabi', 'cxx'] + targets
                targets.append('clang')
                for target in targets:
                    log_info_heading("Building target %s", target)
                    run_cmd(['ninja', target])
                log_info_heading("Building all other targets")
                run_cmd(['ninja'])
                if self.is_last_stage:
                    for target in ['clangd', 'clangd-indexer']:
                        log_info_heading("Building target %s", target)
                        run_cmd(['ninja', target])

                log_info_heading("Installing")
                run_cmd(['ninja', 'install'])
                if self.is_last_stage:
                    # This file is not installed by "ninja install" so copy it manually.
                    # TODO: clean up code repetition.
                    binary_rel_path = 'bin/clangd-indexer'
                    src_path = os.path.join(self.cmake_build_dir, binary_rel_path)
                    dst_path = os.path.join(self.install_prefix, binary_rel_path)
                    logging.info("Copying file %s to %s", src_path, dst_path)
                    shutil.copyfile(src_path, dst_path)
                    make_file_executable(dst_path)

                    for file_name in ['CMakeCache.txt', 'compile_commands.json']:
                        src_path = os.path.join(self.cmake_build_dir, file_name)
                        dst_path = os.path.join(
                            self.build_conf.get_llvm_build_info_dir(), file_name)
                        logging.info("Copying file %s to %s", src_path, dst_path)
                        shutil.copyfile(src_path, dst_path)

    def check_dynamic_libraries(self) -> None:
        for root, dirs, files in os.walk(self.install_prefix):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                logging.info("File path: %s", file_path)


class ClangBuilder:
    args: Any
    llvm_parent_dir: str
    stages: List[ClangBuildStage]
    build_conf: ClangBuildConf

    def __init__(self) -> None:
        self.stages = []

    def parse_args(self) -> None:
        parser = argparse.ArgumentParser(description='Build Clang')
        parser.add_argument(
            '--install_parent_dir',
            help='Parent directory of the final installation directory. Default: ' +
                 DEFAULT_INSTALL_PARENT_DIR,
            default=DEFAULT_INSTALL_PARENT_DIR)
        parser.add_argument(
            '--local_build',
            help='Run the build locally, even if BUILD_CLANG_REMOTE_... variables are set.',
            action='store_true')
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
        parser.add_argument(
            '--min_stage',
            type=int,
            default=1,
            help='First stage to build')
        parser.add_argument(
            '--max_stage',
            type=int,
            default=NUM_STAGES,
            help='Last stage to build')
        parser.add_argument(
            '--top_dir_suffix',
            help='Suffix to append to the top-level directory that we will use for the build. ')
        parser.add_argument(
            '--llvm_version',
            help='LLVM version to build, e.g. 12.0.1, 11.1.0, 10.0.1, 9.0.1, 8.0.1, or 7.1.0, or '
                 'Yugabyte-specific tags with extra patches, such as 12.0.1-yb-1 or 11.1.0-yb-1.',
            default='13.0.0')
        parser.add_argument(
            '--skip_auto_suffix',
            help='Do not add automatic suffixes based on Git commit SHA1 and current time to the '
                 'build directory and the archive name. This is useful for incremental builds when '
                 'debugging build-clang scripts.',
            action='store_true')
        parser.add_argument(
            '--use_compiler_wrapper',
            action='store_true',
            help='Use a compiler wrapper script. May slow down compilation.')
        parser.add_argument(
            '--lto',
            action='store_true',
            help='Use link-time optimization for the final stage of the build.')
        parser.add_argument(
            '--upload_earlier_build',
            help='Upload earlier build specified by this path. This is useful for debugging '
                 'release upload to GitHub.')
        parser.add_argument(
            '--reuse_tarball',
            help='Reuse existing tarball (for use with --upload_earlier_build).',
            action='store_true')
        parser.add_argument(
            '--use_compiler_rt',
            help='Use compiler-rt runtime',
            action='store_true')
        parser.add_argument(
            '--existing_build_dir',
            help='Continue build in an existing directory, e.g. '
                 '/opt/yb-build/llvm/yb-llvm-v12.0.0-1618898532-d28af7c6-build. '
                 'This helps when developing these scripts to avoid rebuilding from scratch.')

        self.args = parser.parse_args()

        if self.args.min_stage < 1:
            raise ValueError("--min-stage value too low: %d" % self.args.min_stage)
        if self.args.max_stage > NUM_STAGES:
            raise ValueError("--max-stage value too high: %d" % self.args.max_stage)
        if self.args.min_stage > self.args.max_stage:
            raise ValueError(
                "--min-stage value (%d) is greater than --max-stage value (%d)" % (
                    self.args.min_stage, self.args.max_stage))

        if self.args.existing_build_dir:
            logging.info("Assuming --skip_auto_suffix because --existing_build_dir is set")
            self.args.skip_auto_suffix = True

        self.build_conf = ClangBuildConf(
            install_parent_dir=self.args.install_parent_dir,
            version=self.args.llvm_version,
            user_specified_suffix=self.args.top_dir_suffix,
            skip_auto_suffix=self.args.skip_auto_suffix,
            clean_build=self.args.clean,
            use_compiler_wrapper=self.args.use_compiler_wrapper,
            lto=self.args.lto,
            use_compiler_rt=self.args.use_compiler_rt,
            existing_build_dir=self.args.existing_build_dir
        )

    def init_stages(self) -> None:
        prev_stage: Optional[ClangBuildStage] = None
        for stage_number in range(1, NUM_STAGES + 1):
            self.stages.append(ClangBuildStage(
                build_conf=self.build_conf,
                stage_number=stage_number,
                prev_stage=prev_stage,
                is_last_stage=(stage_number == NUM_STAGES)
            ))
            prev_stage = self.stages[-1]

    def run(self) -> None:
        if os.getenv('BUILD_CLANG_REMOTELY') == '1' and not self.args.local_build:
            remote_build.build_remotely(
                remote_server=self.args.remote_server,
                remote_build_scripts_path=self.args.remote_build_scripts_path,
                # TODO: make this an argument?
                remote_mkdir=True
            )
            return

        if sys.platform != 'darwin':
            activate_devtoolset()

        if (self.args.existing_build_dir is not None and
                self.build_conf.get_llvm_build_parent_dir() != self.args.existing_build_dir):
            logging.warning(
                f"User-specified build directory : {self.args.existing_build_dir}")
            logging.warning(
                f"Computed build directory       : {self.build_conf.get_llvm_build_parent_dir()}")
            raise ValueError("Build directory mismatch, see the details above.")

        if not self.args.upload_earlier_build:
            if self.args.existing_build_dir:
                logging.info("Not cloning the code, assuming it has already been done.")
            else:
                logging.info(
                    f"Cloning LLVM code to {self.build_conf.get_llvm_project_clone_dir()}")

                mkdir_p(self.build_conf.get_llvm_build_info_dir())
                git_clone_tag(
                    LLVM_REPO_URL,
                    'llvmorg-%s' % self.build_conf.version,
                    self.build_conf.get_llvm_project_clone_dir())

            if not self.args.skip_auto_suffix:
                git_sha1 = get_current_git_sha1(self.build_conf.get_llvm_project_clone_dir())
                self.build_conf.set_git_sha1(git_sha1)
                logging.info(
                    "Final LLVM code directory: %s",
                    self.build_conf.get_llvm_project_clone_dir())

            logging.info(
                "After all stages, LLVM will be built and installed to: %s",
                self.build_conf.get_final_install_dir())

            save_git_log_to_file(
                self.build_conf.get_llvm_project_clone_dir(),
                os.path.join(
                    self.build_conf.get_llvm_build_info_dir(), 'llvm_git_log.txt'))

            self.init_stages()

            for stage in self.stages:
                if self.args.min_stage <= stage.stage_number <= self.args.max_stage:
                    stage_start_time_sec = time.time()
                    logging.info("Building stage %d", stage.stage_number)
                    stage.build()
                    stage_elapsed_time_sec = time.time() - stage_start_time_sec
                    logging.info("Built stage %d in %.1f seconds",
                                 stage.stage_number, stage_elapsed_time_sec)
                else:
                    logging.info("Skipping stage %d", stage.stage_number)

        final_install_dir = (
            self.args.upload_earlier_build or self.build_conf.get_final_install_dir())
        final_install_dir_basename = os.path.basename(final_install_dir)
        final_install_parent_dir = os.path.dirname(final_install_dir)
        archive_name = final_install_dir_basename + '.tar.gz'
        archive_path = os.path.join(final_install_parent_dir, archive_name)

        if not self.args.reuse_tarball or not os.path.exists(archive_path):
            if os.path.exists(archive_path):
                logging.info("Removing existing archive %s", archive_path)
                try:
                    os.remove(archive_path)
                except OSError as ex:
                    logging.exception("Failed to remove %s, ignoring the error", archive_path)

            run_cmd(
                ['tar', 'czf', archive_name, final_install_dir_basename],
                cwd=final_install_parent_dir,
            )

        sha256sum_output = subprocess.check_output(
            ['sha256sum', archive_path]).decode('utf-8')
        sha256sum_file_path = archive_path + '.sha256'
        with open(sha256sum_file_path, 'w') as sha256sum_file:
            sha256sum_file.write(sha256sum_output)

        assert final_install_dir_basename.startswith(YB_LLVM_ARCHIVE_NAME_PREFIX)
        tag = final_install_dir_basename[len(YB_LLVM_ARCHIVE_NAME_PREFIX):]

        github_token_path = os.path.expanduser('~/.github-token')
        if os.path.exists(github_token_path) and not os.getenv('GITHUB_TOKEN'):
            logging.info("Reading GitHub token from %s", github_token_path)
            with open(github_token_path) as github_token_file:
                os.environ['GITHUB_TOKEN'] = github_token_file.read().strip()

        run_cmd([
            'hub',
            'release',
            'create', tag,
            '-m', 'Release %s' % tag,
            '-a', archive_path,
            '-a', sha256sum_file_path,
            # '-t', ...
        ], cwd=BUILD_CLANG_SCRIPTS_ROOT_PATH)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(filename)s:%(lineno)d] %(asctime)s %(levelname)s: %(message)s")
    builder = ClangBuilder()
    builder.parse_args()
    builder.run()


if __name__ == '__main__':
    main()
