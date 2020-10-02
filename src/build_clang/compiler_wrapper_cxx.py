#!/usr/bin/env python3

from build_clang import compiler_wrapper


def main() -> None:
    compiler_wrapper.run_compiler_wrapper(is_cxx=True)


if __name__ == '__main__':
    main()
