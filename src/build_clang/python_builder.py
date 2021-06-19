import os
import tempfile
import subprocess
import logging

from downloadutil.downloader import Downloader
from downloadutil.download_config import DownloadConfig

"""
#!/usr/bin/env bash

# shellcheck disable=SC1091
source scl_source enable devtoolset-8

set -euo pipefail

# shellcheck source=docker_setup_scripts/docker_setup_scripts_common.sh
. "${BASH_SOURCE%/*}/docker_setup_scripts_common.sh"

python_tmp_dir=/tmp/python_install_from_source
mkdir -p "$python_tmp_dir"
python_version=3.8.2
python_src_dir_name="Python-$python_version"
cd "$python_tmp_dir"
python_src_tarball_name="$python_src_dir_name.tgz"
python_src_tarball_url="https://www.python.org/ftp/python/$python_version/$python_src_tarball_name"
wget "$python_src_tarball_url"
actual_md5sum=$( md5sum "$python_src_tarball_name" | awk '{print $1}')
expected_md5sum="f9f3768f757e34b342dbc06b41cbc844"
if [[ $actual_md5sum != "$expected_md5sum" ]]; then
  echo >&2 "Checksum mismatch: actual=$actual_md5sum, expected=$expected_md5sum"
fi
python_build_dir="$python_tmp_dir/$python_src_dir_name"
sudo rm -rf "$python_build_dir"
tar xzf "$python_src_tarball_name"
cd "$python_build_dir"
python_prefix="/usr/share/python-$python_version"
export CFLAGS="-mno-avx -mno-bmi -mno-bmi2 -mno-fma -march=core-avx-i"
export CXXFLAGS=$CFLAGS
export LDFLAGS="-Wl,-rpath=$python_prefix/lib"
echo "CFLAG=$CFLAGS"
echo "LDFLAGS=$LDFLAGS"
./configure "--prefix=$python_prefix" "--with-optimizations"
make
sudo make install
# Upgrade pip
sudo "$python_prefix/bin/pip3" install -U pip

for binary_name in python3 pip3 python3-config; do
  sudo update-alternatives --install "/usr/local/bin/$binary_name" "$binary_name" \
                           "$python_prefix/bin/$binary_name" 1000
done

"""


PYTHON_VERSION = '3.8.2'
PYTHON_EXPECTED_MD5_SUM = 'f9f3768f757e34b342dbc06b41cbc844'


class PythonBuilder:
    def __init__(self, install_parent_dir: str) -> None:
        self.install_parent_dir = install_parent_dir
        self.version = PYTHON_VERSION
        self.install_prefix = os.path.join(self.install_parent_dir, f'python-{self.version}')
        self.python_src_dir_name = f'Python-{self.version}'
        self.python_src_tarball_name = f'{self.python_src_dir_name}.tgz'
        self.python_src_tarball_url = \
            f'https://www.python.org/ftp/python/{self.version}/{self.python_src_tarball_name}'

    def build(self) -> None:
        download_config = DownloadConfig(
            verbose=True,
            cache_dir_path=os.path.expanduser('~/.cache/downloads'))
        downloader = Downloader(config=download_config)
        downloaded_path = downloader.download_url(
            self.python_src_tarball_url,
            download_parent_dir_path=None,
            verify_checksum=False)

        with tempfile.TemporaryDirectory() as tmp_dir_path:
            logging.info(
                f"Extracting Python source archive {downloaded_path} in {tmp_dir_path}")
            subprocess.check_call(
                ['tar', 'xzf', downloaded_path],
                cwd=tmp_dir_path)
            python_src_dir_path = os.path.join(tmp_dir_path, self.python_src_dir_name)
            if not os.path.exists(python_src_dir_path):
                raise IOError(f"Directory {python_src_dir_path} did not get created")
            subprocess.check_call(
                [
                    './configure',
                    f'--prefix={self.install_prefix}',
                    '--with-optimizations'
                ],
                cwd=python_src_dir_path)
            subprocess.check_call(
                [
                    'make'
                ],
                cwd=python_src_dir_path)
            subprocess.check_call(
                ['make', 'install'],
                cwd=python_src_dir_path)