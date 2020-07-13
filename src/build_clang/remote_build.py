from build_clang.helpers import run_cmd
import shlex


def build_remotely(remote_server: str, remote_build_scripts_path: str) -> None:
    assert remote_server is not None
    assert remote_build_scripts_path is not None
    assert remote_build_scripts_path.startswith('/')
    run_cmd(['ssh', remote_server, 'mkdir -p %s' % shlex.quote(remote_build_scripts_path)])
    run_cmd(['rsync', remote_server, 'mkdir -p %s' % shlex.quote(remote_build_scripts_path)])
