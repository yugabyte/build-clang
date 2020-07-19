import subprocess
import os
import logging
from build_clang.helpers import run_cmd, ChangeDir, mkdir_p
from build_clang.file_downloader import FileDownloader

CMAKE_VERSION = '3.18.0'
CMAKE_URL = (
    'https://github.com/Kitware/CMake/releases/download/v{}/cmake-{}-Linux-x86_64.tar.gz'.format(
        CMAKE_VERSION, CMAKE_VERSION))
CMAKE_EXPECTED_SHA256 = '4d9a9d3351161073a67e49366d701b6fa4b0343781982dc5eef08a02a750d403'
CMAKE_INSTALL_PARENT_DIR = '/opt/yb-build/cmake'

g_cmake_executable_path = None


class CMakeInstaller:
    install_dir: str

    def __init__(self) -> None:
        self.install_dir = os.path.join(
            CMAKE_INSTALL_PARENT_DIR, 'cmake-%s-Linux-x86_64' % CMAKE_VERSION)
        self.cmake_executable_path = os.path.join(self.install_dir, 'bin', 'cmake')

    def install(self) -> None:
        if os.path.exists(self.cmake_executable_path):
            return

        file_downloader = FileDownloader()
        downloaded_archive = file_downloader.download_file(CMAKE_URL, CMAKE_EXPECTED_SHA256)
        mkdir_p(CMAKE_INSTALL_PARENT_DIR)
        with ChangeDir(CMAKE_INSTALL_PARENT_DIR):
            run_cmd(['tar', 'xzf', downloaded_archive])
        if not os.path.exists(self.cmake_executable_path):
            raise IOError(
                "Failed to create %s by extracting %s in %s" % (
                    self.cmake_executable_path,
                    downloaded_archive,
                    CMAKE_INSTALL_PARENT_DIR))

        cmake_version_str = subprocess.check_output(
            [self.cmake_executable_path, '--version']
        ).decode('utf-8').split("\n")[0].split()[-1]
        if cmake_version_str != CMAKE_VERSION:
            raise ValueError(
                "Invalid version from running %s --version: got %s, expected %s" % (
                    self.cmake_executable_path, cmake_version_str, CMAKE_VERSION))
        logging.info("Successfully installed CMake version %s at %s" % (
            CMAKE_VERSION, self.cmake_executable_path))


def get_cmake_path() -> str:
    global g_cmake_executable_path
    if not g_cmake_executable_path:
        cmake_installer = CMakeInstaller()
        cmake_installer.install()
        g_cmake_executable_path = cmake_installer.cmake_executable_path
    return g_cmake_executable_path
