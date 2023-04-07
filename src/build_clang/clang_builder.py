import argparse
import os
import logging
import shlex
import subprocess
import git
import atexit
import sys
import time
import platform

from typing import Any, List, Optional

from sys_detection import is_linux, is_macos

from build_clang.constants import (
    NUM_NON_LTO_STAGES,
    DEFAULT_INSTALL_PARENT_DIR,
    DEFAULT_GITHUB_ORG,
    LLVM_VERSION_MAP,
    LLVM_PROJECT_CLONE_REL_PATH,
    GIT_SHA1_PLACEHOLDER_STR_WITH_SEPARATORS,
    YB_LLVM_ARCHIVE_NAME_PREFIX,
    BUILD_CLANG_SCRIPTS_ROOT_PATH,
)
from build_clang.helpers import (
    mkdir_p,
    run_cmd,
    get_major_version,
    remove_version_suffix,
)
from build_clang.clang_build_stage import ClangBuildStage
from build_clang.clang_build_conf import ClangBuildConf
from build_clang.git_helpers import git_clone_tag, get_current_git_sha1, save_git_log_to_file
from build_clang import remote_build
from build_clang.devtoolset import activate_devtoolset

# TODO: automatically pull latest images from https://github.com/yugabyte/build-infra
DOCKER_IMAGES = {
    'x86_64': {
        'almalinux8': 'yb_build_infra_almalinux8_x86_64:v2022-10-13T18_10_49',
        'centos7': 'yb_build_infra_centos7_x86_64:v2022-10-13T18_10_48',
        'ubuntu1804': 'yb_build_infra_ubuntu1804_x86_64:v2022-10-13T18_10_49',
        'ubuntu2004': 'yb_build_infra_ubuntu2004_x86_64:v2022-10-13T18_10_48',
        'ubuntu2204': 'yb_build_infra_ubuntu2204_x86_64:v2022-10-13T18_10_50',
    },
    'aarch64': {
        'centos7': 'yb_build_infra_centos7_aarch64:v2022-10-13T18_12_26',
        'almalinux8': 'yb_build_infra_almalinux8_aarch64:v2022-10-13T18_13_02',
        'ubuntu2004': 'yb_build_infra_ubuntu2004_aarch64:v2022-10-13T18_13_18',
        'ubuntu2204': 'yb_build_infra_ubuntu2204_aarch64:v2022-10-13T18_13_46',
    }
}


class ClangBuilder:
    args: Any
    llvm_parent_dir: str
    stages: List[ClangBuildStage]
    build_conf: ClangBuildConf

    def __init__(self) -> None:
        self.stages = []

    def get_max_allowed_stage(self) -> int:
        if self.args.lto:
            return NUM_NON_LTO_STAGES + 1
        return NUM_NON_LTO_STAGES

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
            default=None,
            help='Last stage to build')
        parser.add_argument(
            '--top_dir_suffix',
            help='Suffix to append to the top-level directory that we will use for the build. ')
        parser.add_argument(
            '--llvm_version',
            help='LLVM version to build, e.g. 12.0.1, 11.1.0, 10.0.1, 9.0.1, 8.0.1, or 7.1.0, or '
                 'Yugabyte-specific tags with extra patches, such as 12.0.1-yb-1 or 11.1.0-yb-1.',
            default='16')
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
            default=None,
            help='Use link-time optimization for the final stage of the build (default on Linux)')
        parser.add_argument(
            '--no-lto',
            dest='lto',
            action='store_false',
            help='The opposite of --lto (LTO is disabled by default on macOS)')
        parser.add_argument(
            '--upload_earlier_build',
            help='Upload earlier build specified by this path. This is useful for debugging '
                 'release upload to GitHub.')
        parser.add_argument(
            '--reuse_tarball',
            help='Reuse existing tarball (for use with --upload_earlier_build).',
            action='store_true')
        parser.add_argument(
            '--no_compiler_rt',
            help='Do not use compiler-rt runtime',
            action='store_true')
        parser.add_argument(
            '--existing_build_dir',
            help='Continue build in an existing directory, e.g. '
                 '/opt/yb-build/llvm/yb-llvm-v12.0.0-1618898532-d28af7c6-build. '
                 'This helps when developing these scripts to avoid rebuilding from scratch.')
        parser.add_argument(
            '--parallelism', '-j',
            type=int,
            help='Set the parallelism level for Ninja builds'
        )
        parser.add_argument(
            '--github_org',
            help='GitHub organization to use in the clone URL. Default: ' + DEFAULT_GITHUB_ORG,
            default=DEFAULT_GITHUB_ORG
        )
        parser.add_argument(
            '--skip_upload',
            help='Skip package upload',
            action='store_true')
        parser.add_argument(
            '--check_github_token',
            help='Check that we have a GitHub token before doing any builds')
        self.args = parser.parse_args()

        max_allowed_stage = self.get_max_allowed_stage()
        if self.args.max_stage is None:
            self.args.max_stage = max_allowed_stage
        if self.args.min_stage < 1:
            raise ValueError("--min-stage value too low: %d" % self.args.min_stage)
        if self.args.max_stage > max_allowed_stage:
            raise ValueError("--max-stage value too high: %d" % self.args.max_stage)
        if self.args.min_stage > self.args.max_stage:
            raise ValueError(
                "--min-stage value (%d) is greater than --max-stage value (%d)" % (
                    self.args.min_stage, self.args.max_stage))

        if self.args.existing_build_dir:
            logging.info("Assuming --skip_auto_suffix because --existing_build_dir is set")
            self.args.skip_auto_suffix = True

        adjusted_llvm_version = LLVM_VERSION_MAP.get(
            self.args.llvm_version, self.args.llvm_version)
        if self.args.llvm_version != adjusted_llvm_version:
            logging.info("Automatically substituting LLVM version %s for %s",
                         adjusted_llvm_version, self.args.llvm_version)
        self.args.llvm_version = adjusted_llvm_version

        llvm_major_version = get_major_version(self.args.llvm_version)

        if self.args.lto is None:
            if is_linux():
                if llvm_major_version >= 16:
                    logging.info("Disabling LTO by default on Linux for LLVM major version %d",
                                 llvm_major_version)
                    self.args.lto = False
                else:
                    logging.info("Enabling LTO by default on Linux for LLVM major version %d",
                                 llvm_major_version)
                    self.args.lto = True
            else:
                logging.info("Disabling LTO by default on a non-Linux system")
                self.args.lto = False
        logging.info("LTO enabled: %s" % self.args.lto)

        self.build_conf = ClangBuildConf(
            install_parent_dir=self.args.install_parent_dir,
            version=self.args.llvm_version,
            user_specified_suffix=self.args.top_dir_suffix,
            skip_auto_suffix=self.args.skip_auto_suffix,
            clean_build=self.args.clean,
            use_compiler_wrapper=self.args.use_compiler_wrapper,
            use_compiler_rt=not self.args.no_compiler_rt,
            existing_build_dir=self.args.existing_build_dir,
            parallelism=self.args.parallelism
        )

    def init_stages(self) -> None:
        effective_stage_number = 1
        for stage_number in range(1, NUM_NON_LTO_STAGES + 1):
            lto_values = [False]
            if stage_number == NUM_NON_LTO_STAGES and self.args.lto:
                lto_values.append(True)

            for lto in lto_values:
                self.stages.append(ClangBuildStage(
                    build_conf=self.build_conf,
                    stage_number=effective_stage_number,
                    prev_stage=self.stages[-1] if self.stages else None,
                    is_last_non_lto_stage=(stage_number == NUM_NON_LTO_STAGES) and not lto,
                    lto=lto
                ))
                effective_stage_number += 1

    def clone_llvm_source_code(self) -> None:
        llvm_project_src_path = self.build_conf.get_llvm_project_clone_dir()
        logging.info(f"Cloning LLVM code to {llvm_project_src_path}")

        find_cmd = [
            'find', '/opt/yb-build/llvm', '-mindepth', '3', '-maxdepth', '3',
            '-wholename', os.path.join('*', LLVM_PROJECT_CLONE_REL_PATH)
        ]
        logging.info("Searching for existing LLVM source directories using command: %s",
                     ' '.join([shlex.quote(item) for item in find_cmd]))
        existing_src_dirs = subprocess.check_output(find_cmd).decode('utf-8').split('\n')

        tag_we_want = 'llvmorg-%s' % self.build_conf.version

        existing_dir_to_use: Optional[str] = None
        llvm_repo_url = f'https://github.com/{self.args.github_org}/llvm-project.git'
        for existing_src_dir in existing_src_dirs:
            existing_src_dir = existing_src_dir.strip()
            if not existing_src_dir:
                continue
            if not os.path.exists(existing_src_dir):
                logging.warning("Directory %s does not exist", existing_src_dir)
                continue

            repo = git.Repo(existing_src_dir)
            # From https://stackoverflow.com/questions/34932306/get-tags-of-a-commit
            # Also relevant:
            # https://stackoverflow.com/questions/32523121/gitpython-get-current-tag-detached-head
            for tag in repo.tags:
                tag_commit = repo.commit(tag)
                if tag_commit.hexsha == repo.head.commit.hexsha:
                    logging.info(
                        f"Found tag {tag.name} in {existing_src_dir} "
                        f"matching the head SHA1 {repo.head.commit.hexsha}")
                    if tag.name == tag_we_want:
                        existing_dir_to_use = existing_src_dir
                        logging.info(
                            "This tag matches the name we want: %s, will clone from directory %s",
                            tag_we_want, existing_dir_to_use)
                        break
            if existing_dir_to_use:
                break
        if not existing_dir_to_use:
            logging.info("Did not find an existing checkout of tag %s, will clone %s",
                         tag_we_want, llvm_repo_url)

        if GIT_SHA1_PLACEHOLDER_STR_WITH_SEPARATORS in os.path.basename(
                os.path.dirname(os.path.dirname(llvm_project_src_path))):
            def remove_dir_with_placeholder_in_name() -> None:
                if os.path.exists(llvm_project_src_path):
                    logging.info("Removing directory %s", llvm_project_src_path)
                    subprocess.call(['rm', '-rf', llvm_project_src_path])
                else:
                    logging.warning("Directory %s does not exist, nothing to remove",
                                    llvm_project_src_path)
            atexit.register(remove_dir_with_placeholder_in_name)

        git_clone_tag(
            llvm_repo_url if existing_dir_to_use is None else existing_dir_to_use,
            tag_we_want,
            llvm_project_src_path)

    def create_clang_rt_builtins_symlinks(self, final_install_dir: str) -> None:
        """
        Boost 1.81 and potentially newer versions of Boost look for the following kinds of file
        names relative to the Clang installation directory (example given for x86_64 architecture):

        lib/clang/16/lib/linux/libclang_rt.builtins-x86_64.a

        However, this file is installed by default in the following location:

        lib/clang/16/lib/x86_64-unknown-linux-gnu/libclang_rt.builtins.a

        This pattern repeats for many different runtime libraries, e.g. UBSAN. Here, we create
        the corresponding symlinks to satisfy this requirement.
        """

        if not is_linux():
            return

        llvm_major_version = self.build_conf.llvm_major_version
        arch = platform.machine()

        llvm_version_variants = sorted(set([
            str(llvm_major_version),
            remove_version_suffix(self.build_conf.version)
        ]))

        existing_prefix_dirs = []
        prefix_dir_candidates = []
        for version_str in llvm_version_variants:
            common_dir_prefix_candidate = os.path.join(
                final_install_dir,
                'lib', 'clang', version_str, 'lib')
            if os.path.isdir(common_dir_prefix_candidate):
                existing_prefix_dirs.append(common_dir_prefix_candidate)
            prefix_dir_candidates.append(common_dir_prefix_candidate)
        if len(existing_prefix_dirs) == 0:
            raise ValueError("None of these directories exist: %s" % prefix_dir_candidates)
        if len(existing_prefix_dirs) > 1:
            raise ValueError("Multiple directories exist: %s" % existing_prefix_dirs)
        common_dir_prefix = existing_prefix_dirs[0]

        existing_per_arch_dir = os.path.join(
            common_dir_prefix,
            f'{arch}-unknown-linux-gnu')
        if not os.path.isdir(existing_per_arch_dir):
            raise IOError(
                f"Directory does not exist: {existing_per_arch_dir}, cannot create symlinks to "
                f"files in this directory.")
        link_parent_dir = os.path.join(common_dir_prefix, 'linux')
        mkdir_p(link_parent_dir)
        num_symlinks_created = 0
        for file_name in os.listdir(existing_per_arch_dir):
            if not file_name.endswith(('.so', '.a')):
                continue
            actual_file_path = os.path.join(existing_per_arch_dir, file_name)
            name_without_ext, ext = os.path.splitext(file_name)
            link_name = f"{name_without_ext}-{arch}{ext}"
            link_path = os.path.join(link_parent_dir, link_name)
            os.symlink(os.path.relpath(os.path.abspath(actual_file_path), link_parent_dir),
                       link_path)
            num_symlinks_created += 1

        logging.info(
            f"Created {num_symlinks_created} symlinks to files in {existing_per_arch_dir} in "
            f"{link_parent_dir} to facilitate Boost 1.81+ build")

    def run(self) -> None:
        if os.getenv('BUILD_CLANG_REMOTELY') == '1' and not self.args.local_build:
            remote_build.build_remotely(
                remote_server=self.args.remote_server,
                remote_build_scripts_path=self.args.remote_build_scripts_path,
                # TODO: make this an argument?
                remote_mkdir=True
            )
            return

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
                self.clone_llvm_source_code()
                mkdir_p(self.build_conf.get_llvm_build_info_dir())

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

            effective_max_stage = self.args.max_stage
            if self.args.lto:
                effective_max_stage = NUM_NON_LTO_STAGES + 1
            for stage in self.stages:
                if self.args.min_stage <= stage.stage_number <= effective_max_stage:
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
        self.create_clang_rt_builtins_symlinks(final_install_dir)

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

        if is_macos():
            sha_sum_cmd_line = ['shasum', '-a', '256']
        else:
            sha_sum_cmd_line = ['sha256sum']
        sha_sum_cmd_line.append(archive_path)
        sha256sum_output = subprocess.check_output(sha_sum_cmd_line).decode('utf-8')
        sha256sum_file_path = archive_path + '.sha256'
        with open(sha256sum_file_path, 'w') as sha256sum_file:
            sha256sum_file.write(sha256sum_output)

        assert final_install_dir_basename.startswith(YB_LLVM_ARCHIVE_NAME_PREFIX)
        tag = final_install_dir_basename[len(YB_LLVM_ARCHIVE_NAME_PREFIX):]

        if self.args.skip_upload:
            logging.info("Skipping upload")
            return

        github_token_path = os.path.expanduser('~/.github-token')
        if os.path.exists(github_token_path) and not os.getenv('GITHUB_TOKEN'):
            logging.info("Reading GitHub token from %s", github_token_path)
            with open(github_token_path) as github_token_file:
                os.environ['GITHUB_TOKEN'] = github_token_file.read().strip()

        run_cmd([
            'hub',
            'release',
            'create', tag,
            '-m', 'Release %s (LTO %s)' % (tag, 'enabled' if self.args.lto else 'disabled'),
            '-a', archive_path,
            '-a', sha256sum_file_path,
            # '-t', ...
        ], cwd=BUILD_CLANG_SCRIPTS_ROOT_PATH)
