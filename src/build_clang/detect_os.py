import sys
import platform


def get_os_name() -> str:
    if sys.platform.startswith('linux'):
        dist = platform.dist()
        return ''.join([
            dist[0],
            dist[1].split('.')[0]
        ])

    return sys.platform
