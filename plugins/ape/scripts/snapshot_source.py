#!/usr/bin/env python3
"""Pin one UTF-8 source snapshot of a clean clone at its resolved commit.

Writes every tracked, non-empty UTF-8 text file under --scope into one new JSON file:
{"format": "ape-source-snapshot/1", "revision": REV, "files": [{"path", "sha256",
"bytes", "text"}]}. JSON string framing means no file content can forge another file,
and each entry carries its own hash. Prints the source pin the stage contract and
report descriptor use. The clone is only read. The snapshot is created exclusively
(never overwritten) outside the clone and outside any job's artifacts.
Exit 0 pinned, 1 refused, 2 usage.
"""
import argparse, hashlib, json, os, re, stat, subprocess, sys, tempfile
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
FORMAT = 'ape-source-snapshot/1'
REVISION = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')
REPO_URL = re.compile(r'https://[^/\s]+/[^/\s]+/[^/\s]+')
SOURCE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')


class Refused(Exception):
    pass


def git(clone, *args):
    proc = subprocess.run(['git', '-C', str(clone), *args], capture_output=True, timeout=120,
                          env={**os.environ, 'GIT_NO_LAZY_FETCH': '1', 'GIT_OPTIONAL_LOCKS': '0'})
    if proc.returncode not in (0, 1):  # git grep exits 1 when nothing matched
        raise Refused(f'git {args[0]} failed: {proc.stderr.decode("utf-8", "replace").strip()[-300:]}')
    return proc


def inside(path, root):
    return path == root or root in path.parents


def snapshot(clone, scope, output, max_bytes):
    clone = Path(os.path.realpath(clone))
    top = git(clone, 'rev-parse', '--show-toplevel').stdout.decode().strip()
    if not top or Path(os.path.realpath(top)) != clone:
        raise Refused('--clone must be the top level of a Git work tree')
    revision = git(clone, 'rev-parse', 'HEAD').stdout.decode().strip()
    if not REVISION.fullmatch(revision):
        raise Refused('clone HEAD does not resolve to a commit')
    if Path(scope).is_absolute() or '..' in Path(scope).parts:
        raise Refused('--scope must be a relative path inside the clone')
    if git(clone, 'status', '--porcelain', '--untracked-files=no', '--', scope).stdout.strip():
        raise Refused('clone has local changes in scope; the snapshot would not match its commit')
    listed = git(clone, 'grep', '-I', '-z', '-l', '-e', '', '--', scope).stdout.split(b'\0')
    entries, skipped, size = [], [], 0
    for raw_name in sorted(item for item in listed if item):
        try:
            name = raw_name.decode('utf-8')
        except UnicodeDecodeError:
            skipped.append({'path': raw_name.decode('utf-8', 'replace'), 'reason': 'path is not UTF-8'})
            continue
        path = clone / name
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            skipped.append({'path': name, 'reason': 'not checked out'})
            continue
        if not stat.S_ISREG(info.st_mode) or not inside(Path(os.path.realpath(path)), clone):
            skipped.append({'path': name, 'reason': 'not a regular file in the clone'})
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            skipped.append({'path': name, 'reason': 'not UTF-8'})
            continue
        size += len(raw)
        if size > max_bytes:
            raise Refused(f'snapshot exceeds {max_bytes} bytes; narrow --scope')
        entries.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'text': text})
    if not entries:
        raise Refused('scope holds no tracked UTF-8 text files')
    data = json.dumps({'format': FORMAT, 'revision': revision, 'files': entries}, ensure_ascii=False,
                      sort_keys=True).encode('utf-8')
    if len(data) > max_bytes:
        raise Refused(f'snapshot exceeds {max_bytes} bytes; narrow --scope')
    out = Path(output)
    if not out.is_absolute():
        raise Refused('--output must be an absolute path')
    parent = Path(os.path.realpath(out.parent))
    if not parent.is_dir():
        raise Refused('--output directory does not exist')
    target = parent / out.name
    if inside(target, clone):
        raise Refused('--output must be outside the read-only clone')
    for ancestor in target.parents:
        if ancestor.name == 'artifacts' and (ancestor.parent / 'job.json').exists():
            raise Refused('--output must be outside every job artifacts directory (worker-writable)')
    fd, temp = tempfile.mkstemp(dir=parent, prefix='.' + out.name + '.')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o444)
        os.link(temp, target)  # exclusive: an existing snapshot is never replaced
    except FileExistsError:
        raise Refused('--output already exists; a pinned snapshot is immutable, choose a new name') from None
    finally:
        os.unlink(temp)
    return revision, data, len(entries), skipped, target


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--clone', required=True, help='clean Git clone at the resolved commit')
    parser.add_argument('--repo-url', required=True, help='https://github.com/OWNER/REPO')
    parser.add_argument('--id', required=True, help='source id, for example src-1')
    parser.add_argument('--output', required=True, help='new absolute snapshot path in the research workspace')
    parser.add_argument('--scope', default='.', help="relative path to snapshot (default '.')")
    parser.add_argument('--max-bytes', type=int, default=MAX_BYTES)
    args = parser.parse_args()
    if not REPO_URL.fullmatch(args.repo_url.rstrip('/')) or not SOURCE_ID.fullmatch(args.id) \
            or not 0 < args.max_bytes <= MAX_BYTES:
        parser.error('--repo-url must be https://HOST/OWNER/REPO, --id a short safe id, --max-bytes at most 16 MiB')
    try:
        revision, data, files, skipped, path = snapshot(args.clone, args.scope, args.output, args.max_bytes)
    except (Refused, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}), file=sys.stderr)
        return 1
    scope = Path(args.scope).as_posix().strip('/')
    url = f'{args.repo_url.rstrip("/")}/tree/{revision}' + ('' if scope in ('', '.') else f'/{scope}')
    pin = {'id': args.id, 'url': url, 'revision': revision, 'path': str(path),
           'sha256': hashlib.sha256(data).hexdigest()}
    print(json.dumps({'ok': True, 'pin': pin, 'bytes': len(data), 'files': files, 'skipped': skipped},
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
