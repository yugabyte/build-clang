import requests
import hashlib
import logging
import os
import time

from build_clang.helpers import compute_sha256_checksum, mkdir_p

from typing import Optional


DOWNLOAD_CACHCE_DIR = '/opt/yb-build/download_cache'


class FileDownloader:
    cache_dir: str

    def __init__(self, cache_dir: str = DOWNLOAD_CACHCE_DIR) -> None:
        self.cache_dir = cache_dir

    def download_file(self, url: str, expected_sha256: Optional[str] = None) -> str:
        """
        Downloads the given file to the cache directory, verifies SHA256 checksum, and returns the
        final downloaded file path.
        """
        local_filename = url.split('/')[-1]
        download_path = os.path.join(self.cache_dir, local_filename)
        if os.path.isfile(download_path):
            if expected_sha256:
                actual_sha256 = compute_sha256_checksum(download_path)
                if actual_sha256 == expected_sha256:
                    logging.info(
                        "File %s already exists and has expected SHA256 checksum %s",
                        download_path, expected_sha256)
                    return download_path
                logging.info(
                    "File %s exists but has SHA256 checksum %s instead of expected %s",
                    actual_sha256, expected_sha256)
            else:
                logging.info(
                    "File %s already exists and we don't have an expected SHA256 checksum for it. "
                    "Skipping the download.",
                    download_path)
                return download_path

        sha256_helper = hashlib.sha256()
        logging.info("Downloading %s to %s", url, download_path)
        mkdir_p(self.cache_dir)
        start_time_sec = time.time()
        with requests.get(url, stream=True) as request_stream:
            request_stream.raise_for_status()
            with open(download_path, 'wb') as output_file:
                for chunk in request_stream.iter_content(chunk_size=65536):
                    output_file.write(chunk)
                    sha256_helper.update(chunk)
        actual_sha256 = sha256_helper.hexdigest()
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ValueError(
                "Downloaded %s but got SHA256 %s instead of expected %s" % (
                    download_path, actual_sha256, expected_sha256))
        elapsed_time_sec = time.time() - start_time_sec
        logging.info("Downloaded %s to %s in %.1f seconds", url, download_path, elapsed_time_sec)
        return download_path
