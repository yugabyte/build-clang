#!/usr/bin/env python3

import logging

from build_clang.clang_builder import ClangBuilder


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(filename)s:%(lineno)d] %(asctime)s %(levelname)s: %(message)s")
    builder = ClangBuilder()
    builder.parse_args()
    builder.run()


if __name__ == '__main__':
    main()
