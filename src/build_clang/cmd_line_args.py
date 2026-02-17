import argparse
import os
import logging
import platform

from typing import Tuple, Union

from sys_detection import is_linux

from build_clang.constants import (
    DEFAULT_INSTALL_PARENT_DIR,
    DEFAULT_GITHUB_ORG,
    LLVM_VERSION_MAP,
    NUM_NON_LTO_STAGES,
)
from build_clang.helpers import get_major_version
from build_clang.clang_build_conf import ClangBuildConf


def convert_bool_arg(value: Union[str, bool]) -> bool:
    if isinstance(value, bool):
        return value
    normalized_value = value.lower()
    if normalized_value in ('yes', 'true', 't', 'y', '1'):
        return True
    if normalized_value in ('no', 'false', 'f', 'n', '0'):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected. Got {value}.")


def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Build Clang/LLVM')
    parser.add_argument(
        '--install_parent_dir',
        help='Parent directory of the final installation directory. Default: %s' %
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
        default='18')
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
        help='Use link-time optimization for the final stages of the build (default)')
    parser.add_argument(
        '--no_lto',
        dest='lto',
        action='store_false',
        help='The opposite of --lto')
    parser.add_argument(
        '--pgo',
        action='store_true',
        default=None,
        help='Use profile-guided optimization for the final stage of the build. Requires LTO')
    parser.add_argument(
        '--no_pgo',
        dest='pgo',
        action='store_false',
        help='The opposite of --pgo')
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
        '--skip_build',
        help='Skip building any of the stages. Useful for debugging, or when combined with '
             '--existing_build_dir, when you want to upload an existing build.',
        action='store_true')
    parser.add_argument(
        '--skip_upload',
        help='Skip package upload',
        action='store_true')

    parser.add_argument(
        '--target_arch',
        help='Target architecture to build for.',
        choices=['x86_64', 'aarch64', 'arm64'])

    parser.add_argument(
        '--with_openmp',
        type=convert_bool_arg,
        nargs='?',
        const=True,
        default=True,
        help="Build LLVM with OpenMP support (true by default, specify =no to disable).")

    return parser


def parse_args() -> Tuple[argparse.Namespace, ClangBuildConf]:
    parser = create_arg_parser()
    args = parser.parse_args()

    if args.lto is None:
        logging.info("Enabling LTO by default")
        args.lto = True

    if args.pgo is None:
        if args.lto:
            logging.info("Enabling PGO by default on LTO-enabled builds")
            args.pgo = True
        else:
            logging.info("Disabling PGO by default on LTO-disabled builds")
            args.pgo = False

    max_allowed_stage = NUM_NON_LTO_STAGES + (3 if args.pgo else 1 if args.lto else 0)

    if args.pgo and not args.lto:
        raise ValueError("PGO build requires LTO enabled")

    if not args.skip_build:
        if args.max_stage is None:
            args.max_stage = max_allowed_stage
        if args.min_stage < 1:
            raise ValueError("--min_stage value too low: %d" % args.min_stage)
        if args.max_stage > max_allowed_stage:
            raise ValueError(
                f"--max_stage value too high: {args.max_stage}, must be {max_allowed_stage} or "
                f"lower. LTO is " + ("enabled" if args.lto else "disabled") + ". "
                f"PGO is " + ("enabled" if args.pgo else "disabled"))

        if args.min_stage > args.max_stage:
            raise ValueError(
                "--min-stage value (%d) is greater than --max-stage value (%d)" % (
                    args.min_stage, args.max_stage))

    if args.existing_build_dir:
        logging.info("Assuming --skip_auto_suffix because --existing_build_dir is set")
        args.skip_auto_suffix = True

    adjusted_llvm_version = LLVM_VERSION_MAP.get(
        args.llvm_version, args.llvm_version)
    if args.llvm_version != adjusted_llvm_version:
        logging.info("Automatically substituting LLVM version %s for %s",
                     adjusted_llvm_version, args.llvm_version)
    args.llvm_version = adjusted_llvm_version

    llvm_major_version = get_major_version(args.llvm_version)

    logging.info("LLVM major version: %d", llvm_major_version)
    logging.info("LTO enabled: %s" % args.lto)
    logging.info("PGO enabled: %s" % args.pgo)

    target_arch_arg = args.target_arch
    target_arch_from_env = os.environ.get('YB_TARGET_ARCH')
    current_arch = platform.machine()

    arch_agreement = [
        arch for arch in [target_arch_arg, target_arch_from_env, current_arch]
        if arch is not None
    ]
    if len(set(arch_agreement)) != 1:
        raise ValueError(
            "Target architecture is ambiguous: %s. "
            "--target_arch arg is %s, YB_TARGET_ARCH env var is %s, "
            "platform.machine() is %s" % (
                arch_agreement,
                target_arch_arg,
                target_arch_from_env,
                current_arch))

    build_conf = ClangBuildConf(
        install_parent_dir=args.install_parent_dir,
        version=args.llvm_version,
        user_specified_suffix=args.top_dir_suffix,
        skip_auto_suffix=args.skip_auto_suffix,
        clean_build=args.clean,
        use_compiler_wrapper=args.use_compiler_wrapper,
        use_compiler_rt=not args.no_compiler_rt,
        existing_build_dir=args.existing_build_dir,
        parallelism=args.parallelism,
        target_arch=current_arch,
        openmp_enabled=args.with_openmp
    )

    return args, build_conf
