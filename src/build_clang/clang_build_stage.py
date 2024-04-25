import os
import platform
import logging
import shutil

from typing import Optional, List, Dict, Union, Tuple, Any

import sys_detection
from sys_detection import is_macos, is_linux

from build_clang.clang_build_conf import ClangBuildConf
from build_clang.helpers import (
    multiline_str_to_list,
    get_rpath_flag,
    which,
    to_cmake_option,
    run_cmd,
    log_info_heading,
    make_file_executable,
    get_current_timestamp_str,
    rm_rf,
    mkdir_p,
    ChangeDir,
    EnvVarContext,
    cmake_vars_to_args,
)
from build_clang.compiler_wrapper import get_cmake_args_for_compiler_wrapper
from build_clang.architecture import validate_build_output_arch, get_arch_switch_cmd_prefix
from build_clang.devtoolset import find_latest_gcc


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

    is_last_non_lto_stage: bool
    lto: bool

    def __init__(
            self,
            build_conf: ClangBuildConf,
            stage_number: int,
            prev_stage: Optional['ClangBuildStage'],
            is_last_non_lto_stage: bool,
            lto: bool) -> None:
        # Fields based directly on the parameters.
        self.build_conf = build_conf
        self.stage_number = stage_number
        self.prev_stage = prev_stage
        if self.prev_stage is not None:
            assert self.prev_stage.stage_number != self.stage_number, \
                f"Previous stage is the same as the current stage: {self.stage_number}"

        parent_dir_for_llvm_version = self.build_conf.get_llvm_build_parent_dir()

        # Computed fields.
        self.stage_base_dir = os.path.join(
            parent_dir_for_llvm_version, 'stage-%d' % self.stage_number)
        self.cmake_build_dir = os.path.join(self.stage_base_dir, 'build')

        self.compiler_invocations_top_dir = os.path.join(
            self.stage_base_dir, 'compiler_invocations')
        if is_last_non_lto_stage:
            self.install_prefix = self.build_conf.get_final_install_dir()
        else:
            self.install_prefix = os.path.join(self.stage_base_dir, 'installed')
        self.stage_start_timestamp_str = None
        self.is_last_non_lto_stage = is_last_non_lto_stage
        self.lto = lto

    def is_first_stage(self) -> bool:
        return self.prev_stage is None

    def get_enabled_runtimes(self) -> List[str]:
        runtimes = ['libunwind']
        if not self.is_first_stage():
            # For first stage, we don't build these runtimes because the bootstrap compiler
            # might not be able to compile them (e.g. GCC 8 is having trouble building libc++
            # from the LLVM 13 codebase).
            runtimes.extend(['libcxx', 'libcxxabi', 'compiler-rt'])
        if self.is_last_non_lto_stage and self.build_conf.openmp_enabled:
            runtimes.append('openmp')
        return runtimes

    def get_enabled_projects(self) -> List[str]:
        enabled_projects = multiline_str_to_list("""
            clang
            lld
        """)
        llvm_major_version = self.build_conf.llvm_major_version
        if llvm_major_version <= 15:
            enabled_projects += self.get_enabled_runtimes()

        if self.is_last_non_lto_stage and not self.lto:
            # We only need to build these tools at the last stage.
            enabled_projects.append('clang-tools-extra')
            if (llvm_major_version >= 10 and
                    not (llvm_major_version >= 13 and is_macos())):
                # There were some issues building lldb for LLVM 9 and older.
                # Also, LLVM 14.0.3's LLDB does not build cleanly on macOS in my experience.
                # https://gist.githubusercontent.com/mbautin/a17fa5087e651d4b7d16c27ea6fb80ed/raw
                enabled_projects.append('lldb')
        return sorted(enabled_projects)

    def get_llvm_cmake_variables(self) -> Dict[str, str]:
        """
        See https://llvm.org/docs/CMake.html for the full list of possible options.

        https://raw.githubusercontent.com/llvm/llvm-project/master/llvm/CMakeLists.txt

        https://raw.githubusercontent.com/llvm/llvm-project/master/clang/CMakeLists.txt
        """

        vars: Dict[str, Union[str, bool]] = {}

        use_compiler_rt = self.build_conf.use_compiler_rt

        # For the first stage, we don't specify the default C++ standard library, and just use the
        # default. For second stage and later, we build libc++ and tell Clang to use it by default.
        if not self.is_first_stage():
            vars['CLANG_DEFAULT_CXX_STDLIB'] = 'libc++'

        vars = dict(
            LLVM_ENABLE_PROJECTS=';'.join(self.get_enabled_projects()),
            CMAKE_INSTALL_PREFIX=self.install_prefix,
            CMAKE_BUILD_TYPE='Release',
            LLVM_TARGETS_TO_BUILD='X86;AArch64',

            BUILD_SHARED_LIBS=True,
            CMAKE_EXPORT_COMPILE_COMMANDS=True,

            LLVM_ENABLE_RTTI=True,
            LLVM_ENABLE_ZSTD=False,
        )

        if self.build_conf.llvm_major_version >= 16:
            vars['LLVM_ENABLE_RUNTIMES'] = ';'.join(self.get_enabled_runtimes())

        if is_macos():
            vars.update(
                COMPILER_RT_ENABLE_IOS=False,
                COMPILER_RT_ENABLE_WATCHOS=False,
                COMPILER_RT_ENABLE_TVOS=False,
            )

        if self.stage_number >= 3 and use_compiler_rt:
            # For the first stage, we don't even build compiler-rt.
            # For the second stage, we build it.
            # For the third stage, we can build it and use it for building various libraries.
            vars.update(
                LIBCXXABI_USE_COMPILER_RT=True,
                LIBUNWIND_USE_COMPILER_RT=True,
                LIBCXX_USE_COMPILER_RT=True,
            )

        if not self.is_first_stage():
            # At the second stage and later, we can use LLVM libunwind because it has already been
            # built.
            vars['LIBCXXABI_USE_LLVM_UNWINDER'] = True

            extra_linker_flags = []
            if is_linux():
                if self.build_conf.use_compiler_rt:
                    extra_linker_flags.append(
                        # To avoid depending on libgcc.a when using Clang's runtime library
                        # compiler-rt. Otherwise building protobuf as part of yugabyte-db-thirdparty
                        # fails to find _Unwind_Resume.
                        # _Unwind_Resume is ultimately defined in /lib64/libgcc_s.so.1.
                        '-Wl,--exclude-libs,libgcc.a'
                    )

                # Description for LLVM_ENABLE_LLD from https://llvm.org/docs/CMake.html:
                #
                # > This option is equivalent to -DLLVM_USE_LINKER=lld, except during a 2-stage
                # > build where a dependency is added from the first stage to the second ensuring
                # > that lld is built before stage2 begins.
                #
                # So, simply speaking, this enables the use of lld for building LLVM.
                vars['LLVM_ENABLE_LLD'] = True

            if (self.stage_number >= 3 and
                    is_linux() and
                    sys_detection.local_sys_conf().short_os_name_and_version() == 'amzn2' and
                    platform.machine() == 'aarch64'):
                # This turned out to be necessary for the stage 3 build on Amazon Linux 2 on
                # aarch64. Without this we get a linking error on the UBSAN runtime library.
                # https://gist.githubusercontent.com/mbautin/508849414af633b9839c27b338b04afe/raw
                extra_linker_flags.append('-lc++')

            extra_rpath_flags = []
            if (self.stage_number >= 3 and
                    is_linux() and
                    self.build_conf.llvm_major_version >= 15):
                # Clang 15 build system does not set up rpath properly, and even the tblgen step
                # fails to find libc++.
                os_specific_lib_dir = f'lib/{platform.machine()}-unknown-linux-gnu'
                # We need to escape the $ sign because otherwise $ORIGIN gets replaced by an
                # empty string, probably deep in LLVM's CMake scripts.
                extra_rpath_flags.append(get_rpath_flag(rf'\$ORIGIN/../{os_specific_lib_dir}'))
                if self.build_conf.llvm_major_version >= 16:
                    prev_stage_num = self.stage_number - 1
                    # For Clang 16 on Linux, we also need to set rpath to allow finding libc++ from
                    # the previous stage. llvm-tblgen might fail to find libc++ otherwise.
                    assert self.prev_stage   # must be set because we know stage_number >= 3
                    extra_rpath_flags.append(get_rpath_flag(
                        os.path.join(self.prev_stage.install_prefix, os_specific_lib_dir)
                    ))

            extra_linker_flags.extend(extra_rpath_flags)
            extra_linker_flags_str = ' '.join(extra_linker_flags)
            vars.update(
                CMAKE_SHARED_LINKER_FLAGS_INIT=extra_linker_flags_str,
                CMAKE_MODULE_LINKER_FLAGS_INIT=extra_linker_flags_str,
                CMAKE_EXE_LINKER_FLAGS_INIT=extra_linker_flags_str,
            )
            if (self.stage_number >= 3 and
                    is_linux() and
                    self.build_conf.llvm_major_version >= 16):
                vars.update(
                    SANITIZER_COMMON_LINK_FLAGS=';'.join(['-lc++abi', '-lunwind']),
                    SANITIZER_TEST_CXX_LIBRARIES='-lunwind'
                )

            if self.is_last_non_lto_stage:
                # We only need tests at the last stage because that's where we build clangd-indexer.
                vars['LLVM_BUILD_TESTS'] = True

            if self.lto:
                vars.update(LLVM_ENABLE_LTO='Full')
                vars.update(BUILD_SHARED_LIBS=False)

        # =========================================================================================
        # Stage 3 (non-LTO) and 4 (LTO)
        # =========================================================================================

        # The description of SANITIZER_ALLOW_CXXABI is "Allow use of C++ ABI details in ubsan".
        # We only enable it for stage 3 or later because we only build libc++ and libc++abi
        # starting at stage 2.
        if self.stage_number >= 3:
            vars.update(
                SANITIZER_ALLOW_CXXABI=True,
                SANITIZER_CXX_ABI='libc++',
                LLVM_ENABLE_LIBCXX=True,
                # We only switch to compiler-rt as the default runtime library for the third stage,
                # even though we build it for the second stage as well.
                CLANG_DEFAULT_RTLIB='compiler-rt',
            )

        if self.build_conf.use_compiler_wrapper:
            vars.update(get_cmake_args_for_compiler_wrapper())
        else:
            c_compiler, cxx_compiler = self.get_compilers()
            vars.update(
                CMAKE_C_COMPILER=c_compiler,
                CMAKE_CXX_COMPILER=cxx_compiler
            )

        final_vars: Dict[str, str] = {}
        for k in vars:
            final_vars[k] = to_cmake_option(vars[k])
        return final_vars

    def get_compilers(self) -> Tuple[str, str]:
        if self.stage_number == 1:
            c_compiler, cxx_compiler = find_latest_gcc()
        else:
            assert self.prev_stage is not None
            prev_stage_install_prefix = self.prev_stage.install_prefix
            c_compiler = os.path.join(prev_stage_install_prefix, 'bin', 'clang')
            cxx_compiler = os.path.join(prev_stage_install_prefix, 'bin', 'clang++')
        assert c_compiler is not None
        assert cxx_compiler is not None
        return c_compiler, cxx_compiler

    def _run_ninja(self, args: List[str] = []) -> None:
        ninja_args: List[str] = get_arch_switch_cmd_prefix(self.build_conf.target_arch) + ['ninja']
        if self.build_conf.parallelism:
            ninja_args.append('-j%d' % self.build_conf.parallelism)
        ninja_args.extend(args)
        run_cmd(ninja_args)

    def get_log_prefix(self) -> str:
        return '[Stage %d%s] ' % (
            self.stage_number,
            ' (LTO)' if self.lto else ''
        )

    def log_info_heading(self, heading: str, *args: Any) -> None:
        log_info_heading(self.get_log_prefix() + heading, *args)

    def log_info(self, msg: str, *args: Any) -> None:
        logging.info(self.get_log_prefix() + msg, *args)

    def install_binary_to_final_dir(self, binary_name: str) -> None:
        # This is needed because "clang" is a link to "clang-<version>".
        src_path = os.path.join(self.cmake_build_dir, 'bin', binary_name)
        if not os.path.exists(src_path):
            raise IOError("File does not exist: %s" % src_path)
        if os.path.islink(src_path):
            link_target = os.readlink(src_path)
            link_basename = os.path.basename(link_target)
            logging.info(
                "%s is a link to %s, using binary name %s instead",
                binary_name, link_target, link_basename)
            binary_name = link_basename

        binary_rel_path = os.path.join('bin', binary_name)
        src_path = os.path.join(self.cmake_build_dir, binary_rel_path)
        dst_path = os.path.join(self.build_conf.get_final_install_dir(), binary_rel_path)
        self.log_info("Copying file %s to %s", src_path, dst_path)
        shutil.copyfile(src_path, dst_path)
        make_file_executable(dst_path)

    def build(self) -> None:
        self.stage_start_timestamp_str = get_current_timestamp_str()
        if os.path.exists(self.cmake_build_dir) and self.build_conf.clean_build:
            self.log_info("Deleting directory: %s", self.cmake_build_dir)
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
                run_cmd(get_arch_switch_cmd_prefix(self.build_conf.target_arch) + [
                    self.build_conf.cmake_executable_path,
                    '-G', 'Ninja',
                    '-S', os.path.join(self.build_conf.get_llvm_project_clone_dir(), 'llvm')
                ] + cmake_vars_to_args(cmake_vars))

                targets: List = []
                if not self.is_first_stage():
                    if self.build_conf.llvm_major_version >= 16:
                        # For LLVM 16, compiler-rt depends on c++abi.
                        targets = ['cxxabi', 'compiler-rt', 'cxx'] + targets
                    else:
                        # Keep the order the way it used to be for LLVM 15 and older.
                        targets = ['compiler-rt', 'cxxabi', 'cxx'] + targets
                targets.append('clang')
                for target in targets:
                    self.log_info_heading("Building target %s", target)
                    self._run_ninja([target])
                self.log_info_heading("Building all other targets")
                if self.lto:
                    lto_binaries = ['clang', 'lld']
                    self.log_info("Building LTO binaries: %s", lto_binaries)
                    self._run_ninja(lto_binaries)
                    self.log_info("Installing LTO binaries: %s", lto_binaries)
                    for lto_binary_name in lto_binaries:
                        self.install_binary_to_final_dir(lto_binary_name)
                else:
                    self._run_ninja()
                    if self.is_last_non_lto_stage:
                        for target in ['clangd', 'clangd-indexer']:
                            self.log_info_heading("Building target %s", target)
                            self._run_ninja([target])

                    log_info_heading("Installing")
                    self._run_ninja(['install'])
                    if self.is_last_non_lto_stage:
                        # This file is not installed by "ninja install" so copy it manually.
                        self.install_binary_to_final_dir('clangd-indexer')

                        for file_name in ['CMakeCache.txt', 'compile_commands.json']:
                            src_path = os.path.join(self.cmake_build_dir, file_name)
                            dst_path = os.path.join(
                                self.build_conf.get_llvm_build_info_dir(), file_name)
                            self.log_info("Copying file %s to %s", src_path, dst_path)
                            shutil.copyfile(src_path, dst_path)

                validate_build_output_arch(self.build_conf.target_arch, self.install_prefix)

    def check_dynamic_libraries(self) -> None:
        for root, dirs, files in os.walk(self.install_prefix):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                logging.info("File path: %s", file_path)
