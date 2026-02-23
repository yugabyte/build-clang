from build_clang.helpers import multiline_str_to_list
import os


NUM_NON_LTO_STAGES = 3

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

# Relative path to the directory where we clone the LLVM source code.
LLVM_PROJECT_CLONE_REL_PATH = os.path.join('src', 'llvm-project')

GIT_SHA1_PLACEHOLDER_STR = 'GIT_SHA1_PLACEHOLDER'
GIT_SHA1_PLACEHOLDER_STR_WITH_SEPARATORS = (
    NAME_COMPONENT_SEPARATOR + GIT_SHA1_PLACEHOLDER_STR + NAME_COMPONENT_SEPARATOR)

LLVM_VERSION_MAP = {
    '11': '11.1.0-yb-1',
    '12': '12.0.1-yb-2',
    '13': '13.0.1-yb-2',
    '14': '14.0.6-yb-2',
    '15': '15.0.7-yb-1',
    '16': '16.0.6-yb-3',
    '17': '17.0.6-yb-1',
    '18': '18.1.8-yb-1',
    '19': '19.1.0-yb-1',
    '20': '20.1.8-yb-1',
    '21': '21.1.1-yb-2',
}

DEFAULT_GITHUB_ORG = 'yugabyte'

BUILD_CLANG_SCRIPTS_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
