"""Bounded local file, Git and lock operations shared by source commands."""
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
import time

try:
    import fcntl
except ImportError:
    fcntl = None


class SourceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SourceError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def no_links(path):
    path = Path(path).absolute()
    for part in (*reversed(path.parents), path):
        require(not part.is_symlink(), f'symlink path is unsupported: {part}')
    return path


def regular_files(root):
    """Relative paths of every regular file under root. A symlink anywhere (a linked
    directory is invisible to rglob/is_file scans) or a special file is refused."""
    root = Path(root)
    found = set()
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(folder) / name
            require(not path.is_symlink() and (path.is_dir() or path.is_file()),
                    f'linked or special file among executable inputs: {path}')
            if path.is_file():
                found.add(path.relative_to(root).as_posix())
    return found


def run_verified(command, env):
    """Run Python against verified sources only. Package receipts do not cover
    __pycache__, so the child gets an empty private bytecode cache (-X works under -I)."""
    with tempfile.TemporaryDirectory(prefix='agents-pycache-') as cache:
        argv = [command[0], '-X', 'pycache_prefix=' + cache, *command[1:]]
        return subprocess.run(argv, env=env, check=False).returncode


def relative(value):
    path = PurePosixPath(value)
    require(isinstance(value, str) and value and path.as_posix() == value and
            not path.is_absolute() and '..' not in path.parts and '\\' not in value,
            'unsafe source-relative path')
    return path


def read(path, maximum=16 * 1024 * 1024):
    path = no_links(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), f'expected regular file: {path}')
    require(info.st_size <= maximum, f'file exceeds capture limit: {path}')
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, f'file grew beyond capture limit: {path}')
    return data


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(read(path), object_pairs_hook=pairs)


def atomic(path, data, mode=0o600):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    no_links(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        if hasattr(os, 'O_DIRECTORY'):
            folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic(path, canonical(value))


def git(root, *argv, timeout=20, check=True, input=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    try:
        result = subprocess.run(['git', '-C', str(root), *argv], capture_output=True,
                                timeout=timeout, env=env, input=input)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f'bounded Git command unavailable: {argv[0]}') from exc
    if check:
        require(result.returncode == 0, 'Git ' + argv[0] + ' failed: ' + os.fsdecode(result.stderr).strip())
    return result


class Paths:
    def __init__(self, home=None):
        self.home = no_links(Path.home() if home is None else home)
        state = Path(os.environ.get('XDG_STATE_HOME') or self.home / '.local/state')
        data = Path(os.environ.get('XDG_DATA_HOME') or self.home / '.local/share')
        require(state.is_absolute() and data.is_absolute(), 'XDG data/state roots must be absolute')
        self.state = no_links(state / 'agents')
        self.data = no_links(data / 'agents')
        self.control = self.state / 'control'
        self.snapshots = self.state / 'snapshots'
        self.jobs = self.state / 'jobs'
        self.registry = self.jobs / 'registry'
        self.packages = self.jobs / 'packages'
        self.launcher = self.home / '.local/bin/agents'


@contextmanager
def source_lock(paths, timeout=10):
    """Same HOME-bound inode as dotfiles' guard, including across XDG overrides."""
    require(fcntl is not None, 'source receiving requires POSIX advisory locks; manual Windows operation is unavailable')
    folder = no_links(paths.home / '.local/state/agents/locks')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = no_links(folder / 'source.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    acquired = False
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid == os.getuid() and not info.st_mode & 0o022, 'unsafe source lock')
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                require(time.monotonic() < deadline, 'source update in progress; retry after the bounded lock')
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
