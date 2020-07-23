import os
import subprocess
import logging

from typing import Optional

from build_clang.helpers import mkdir_p, ChangeDir
from build_clang.file_downloader import FileDownloader


CROSSTOOLS_NG_DIR_NAME = 'yb-toolchain-v20200425075614-999759775b'
CROSSTOOLS_NG_URL = (
    'https://github.com/mbautin/yb-toolchain/releases/download/v20200425075614-999759775b/'
    '%s.tar.gz' % CROSSTOOLS_NG_DIR_NAME
)

TOOLCHAIN_PARENT_DIR = '/opt/yb-build/toolchain'

g_crosstools_ng_dir: Optional[str] = None


def get_crosstools_ng_dir() -> str:
    global g_crosstools_ng_dir
    if g_crosstools_ng_dir is not None:
        return g_crosstools_ng_dir

    crosstools_ng_dir = os.path.join(TOOLCHAIN_PARENT_DIR, CROSSTOOLS_NG_DIR_NAME)
    if not os.path.isdir(crosstools_ng_dir):
        install_crosstools_ng()
        if not os.path.isdir(crosstools_ng_dir):
            raise IOError(
                "%s still does not exist after installing crosstools-ng toolchain" %
                crosstools_ng_dir)

    ensure_executable_links_created(crosstools_ng_dir)

    g_crosstools_ng_dir = crosstools_ng_dir
    return crosstools_ng_dir


def install_crosstools_ng():
    file_downloader = FileDownloader()
    downloaded_tar_gz_path = file_downloader.download_file(CROSSTOOLS_NG_URL)

    mkdir_p(TOOLCHAIN_PARENT_DIR)
    with ChangeDir(TOOLCHAIN_PARENT_DIR):
        subprocess.check_call(['tar', 'xzf', downloaded_tar_gz_path])


def ensure_executable_links_created(crosstools_ng_dir):
    prefix = 'x86_64-unknown-linux-gnu-'
    bin_dir = os.path.join(crosstools_ng_dir, 'bin')
    # TODO: we should not need this.
    os.chmod(bin_dir, 0o755)
    num_symlinks_created = 0
    for file_name in os.listdir(bin_dir):
        if file_name.startswith(prefix):
            full_path = os.path.join(bin_dir, file_name)
            link_name = file_name[len(prefix):]
            if link_name:
                full_link_path = os.path.join(bin_dir, link_name)
                if not os.path.islink(full_link_path):
                    os.symlink(file_name, full_link_path)
                    num_symlinks_created += 1
    if num_symlinks_created > 0:
        logging.info("Created %d symlinks in %s", num_symlinks_created, bin_dir)