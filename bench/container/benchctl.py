#!/usr/bin/env python3
"""Create and manage this stage's private, isolated Docker bench resources."""
import argparse
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bench' / 'v2' / 'tools'))
import model_policy
sys.path.insert(0, str(Path(__file__).resolve().parent))
import driver as driver_module
import host_observations

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = ROOT / 'bench' / 'container'
RESULTS = Path('/tmp/t3-issue28-container-results')
STAGE_MAP_PATH = ROOT / 'migration' / 'rebuild' / 'compat-map.d' / 'stage-1b.json'
STAGE_MAP = json.loads(STAGE_MAP_PATH.read_text(encoding='utf-8'))
SECRET_ENV = Path.home() / 't3-plugins-bench' / 'secrets' / 'bench.env'
T3_VERSION = STAGE_MAP['t3']
CLAUDE_VERSION = STAGE_MAP['provider_programs']['claude_code']
CODEX_VERSION = STAGE_MAP['provider_programs']['codex_cli']
RUNTIME = Path.home() / '.t3' / 'runtime' / 'versions' / T3_VERSION
SOURCE_FILES = ('audit_models.py', 'driver.py', 'gateway.py', 'github_sidecar.py', 'smoke.py',
                'smoke_helper.py', 'start-container.sh', 'host_observations.py', 'identity_metadata.py', 'native_exec.py', 'Dockerfile')
NODE_EXECUTABLE = Path(shutil.which('node') or '').resolve()


def private_dir(path):
    if path.is_symlink():
        raise RuntimeError('private results root may not be a symlink')
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('private results root ownership or permissions rejected')


DOCKER_CLEANUP_TIMEOUT = 120


CLEANUP_COMMANDS = (('docker', 'stop'), ('docker', 'rm'), ('docker', 'network', 'rm'),
                    ('docker', 'image', 'rm'))


def run(args, log, check=True, timeout=None):
    if timeout is None and any(tuple(args[:len(prefix)]) == prefix for prefix in CLEANUP_COMMANDS):
        timeout = DOCKER_CLEANUP_TIMEOUT  # A hung daemon must not block cleanup forever.
    with log.open('ab') as stream:
        try:
            result = subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=False,
                                    timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            # A hung daemon is a failed command, never a successful cleanup.
            stream.write(f'timed out after {timeout}s: {args[0]}\n'.encode())
            code = 124
    if check and code:
        raise RuntimeError(f'command failed ({code}): {args[0]}')
    return code


def docker_inspect_json(kind, object_id):
    result = subprocess.run(['docker', kind, 'inspect', object_id], capture_output=True,
                            text=True, check=True, timeout=20)
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError('Docker returned ambiguous resource identity')
    return rows[0]


def _commit_manifest(path, manifest):
    """Write and replace the manifest; return the directory-fsync error, or None.

    Any error before os.replace propagates and leaves the last good copy intact.
    """
    data = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode('utf-8')
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise
    # Committed: from here on readers see the new manifest.
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        return exc
    return None


def write_manifest(path, manifest):
    """Atomically replace the manifest and report whether the commit is durable.

    A failure before os.replace raises and leaves the last good copy intact, so
    nothing new is recorded. After os.replace the new manifest is committed. If
    only the directory fsync then fails, the state is recorded but its durability
    is uncertain: this notes that in the manifest, rewrites it once (best effort)
    and returns False instead of raising. Returns True when durable.
    """
    error = _commit_manifest(path, manifest)
    if error is None:
        return True
    manifest.setdefault('manifest_durability_uncertain', []).append({
        'stage': 'directory-fsync-after-replace', 'committed': True,
        'error': errno.errorcode.get(error.errno, type(error).__name__)})
    try:
        _commit_manifest(path, manifest)
    except OSError:
        pass  # The earlier commit stands; the note is kept for the next write.
    return False


def record_created(manifest, path, kind, role, name, log):
    """Record one created resource; raise only if its identity was not committed."""
    row = docker_inspect_json(kind, name)
    identity = row.get('Id') or row.get('ID')
    if not isinstance(identity, str) or not identity:
        raise RuntimeError('Docker resource has no immutable ID')
    record = {'kind': kind, 'name': name, 'id': identity, 'run_id': manifest['run_id'],
              'labels': run_labels(manifest['run_id'])}
    if not validate_owned_resource(kind, row, record, manifest['run_id']):
        raise RuntimeError('created Docker resource lacks exact name or task ownership labels')
    manifest.setdefault('created_resources', {})[role] = record
    # The committed identity replaces the write-ahead intent in the same atomic write.
    pending = manifest.get('pending_resources', {})
    intent = pending.pop(role, None)
    try:
        write_manifest(path, manifest)
    except BaseException:
        if intent is not None:
            pending[role] = intent  # Not committed: the intent keeps `down`'s authority.
        raise
    # The identity is committed; a log failure must not turn it into a failed recording.
    try:
        with log.open('a', encoding='utf-8') as stream:
            stream.write(f'Created {kind} identity recorded for {role}.\n')
    except OSError:
        pass


RECORD_ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError,
                 subprocess.CalledProcessError, subprocess.TimeoutExpired)
RUN_LABEL_FILTERS = ('--filter', 'label=io.t3.issue28.stage=s1b')
RESOURCE_KINDS = ('container', 'network', 'image')


def run_labels(run_id):
    return {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}


def owned_lookup_command(kind, run_id, name=None):
    """List only objects carrying this run's labels and, when given, exactly this name."""
    labels = [*RUN_LABEL_FILTERS, '--filter', f'label=io.t3.issue28.run={run_id}']
    if kind == 'container':
        return ['docker', 'ps', '--all', '--no-trunc', '--quiet', *labels,
                *(() if name is None else ('--filter', f'name=^/{re.escape(name)}$'))]
    if kind == 'network':
        return ['docker', 'network', 'ls', '--no-trunc', '--quiet', *labels,
                *(() if name is None else ('--filter', f'name=^{re.escape(name)}$'))]
    if kind == 'image':
        return ['docker', 'image', 'ls', '--no-trunc', '--quiet', *labels,
                *(() if name is None else ('--filter', f'reference={name}'))]
    raise ValueError('unsupported Docker resource kind')


REMOVE_OWNED = {'container': ['docker', 'rm', '--force'], 'network': ['docker', 'network', 'rm'],
                'image': ['docker', 'image', 'rm']}


def lookup_owned(kind, run_id, name, logs):
    """Return (lookup succeeded, matching immutable IDs) for this run's labels and name."""
    # Log-file failures must not stop the lookup itself.
    try:
        errors = logs.open('ab')
    except OSError:
        errors = subprocess.DEVNULL
    try:
        listed = subprocess.run(owned_lookup_command(kind, run_id, name),
                                stdout=subprocess.PIPE, stderr=errors, text=True,
                                timeout=20, check=False)
        if listed.returncode != 0 or not isinstance(listed.stdout, str):
            return False, []
        return True, list(dict.fromkeys(listed.stdout.split()))
    except (OSError, subprocess.TimeoutExpired):
        return False, []
    finally:
        if errors is not subprocess.DEVNULL:
            errors.close()


def remove_by_run_labels(kind, run_id, name, logs):
    """Remove whatever matches the run labels and exact name; return a receipt.

    The receipt keeps the exact labels, name, kind and every matched immutable
    ID, so `down` can reconcile this resource later by the same scope.
    """
    lookup_succeeded, found = lookup_owned(kind, run_id, name, logs)
    removed = []
    for identity in found:
        argv = [*REMOVE_OWNED[kind], identity]
        try:
            ok = run(argv, logs, check=False) == 0
        except OSError:
            try:
                ok = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=60, check=False).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
        if ok:
            removed.append(identity)
    return {'cleanup_by': 'run labels and exact name', 'kind': kind, 'name': name,
            'run_id': run_id, 'labels': run_labels(run_id),
            'lookup_succeeded': lookup_succeeded, 'matched': len(found), 'matched_ids': found,
            'removed': len(removed), 'removed_ids': removed}


def reconcile_by_run_labels(kind, run_id, name, logs):
    """Look up, remove, then confirm absence of this run's labelled object with this exact name."""
    receipt = remove_by_run_labels(kind, run_id, name, logs)
    confirmed, remaining = (lookup_owned(kind, run_id, name, logs) if receipt['lookup_succeeded']
                            else (False, []))
    receipt.update(confirmation_lookup_succeeded=confirmed, remaining_ids=remaining,
                   absence_confirmed=confirmed and not remaining)
    return receipt


def labelled_leftovers(run_id, logs):
    """Confirm that no object of any kind still carries this run's labels.

    This only looks; nothing is removed without a recorded identity or an
    exact-name receipt. It catches what no record names, such as a probe
    container whose `docker run --rm` client was interrupted.
    """
    remaining, failed = {}, []
    for kind in RESOURCE_KINDS:
        ok, found = lookup_owned(kind, run_id, None, logs)
        if not ok:
            failed.append(kind)
        elif found:
            remaining[kind] = found
    return {'lookup_failed': failed, 'remaining_ids': remaining,
            'absence_confirmed': not failed and not remaining}


def declare_pending(manifest, role, kind, name):
    """Write-ahead intent: the exact scope `down` may reconcile if recording never happens."""
    manifest.setdefault('pending_resources', {})[role] = {
        'kind': kind, 'name': name, 'run_id': manifest['run_id'],
        'labels': run_labels(manifest['run_id'])}


def abandon_unrecorded(manifest, locate, kind, role, name, logs, failure, receipt_key=None):
    """Remove an unrecorded resource by run labels and exact name, save a receipt, and fail."""
    receipt = remove_by_run_labels(kind, manifest['run_id'], name, logs)
    if receipt_key:
        manifest[receipt_key] = receipt
    else:
        manifest.setdefault('unrecorded_resources', {})[role] = receipt
    try:
        write_manifest(locate(), manifest)
        suffix = ''
    except (OSError, RuntimeError, ValueError):
        suffix = '; cleanup receipt was not saved'
    complete = receipt['lookup_succeeded'] and receipt['removed'] == receipt['matched']
    raise RuntimeError(failure + (f'; labelled {kind} removed' if complete else
                                  '; cleanup incomplete, inspect run labels') + suffix)


def record_or_remove(manifest, locate, kind, role, name, logs, attempts=3,
                     description=None, receipt_key=None):
    """Commit a just-created resource's identity, or remove that resource and fail.

    An identity missing from the committed manifest gives `down` no cleanup
    authority, so nothing created may keep running without one.
    """
    resources = manifest.setdefault('created_resources', {})
    previous = resources.get(role)
    for attempt in range(attempts):
        try:
            record_created(manifest, locate(), kind, role, name, logs)
            return
        except RECORD_ERRORS:
            # OSError covers manifest persistence (ENOSPC, EIO) before commit.
            if attempt + 1 < attempts:
                time.sleep(1)
    # record_created may have set the identity in memory before its write failed.
    if previous is None:
        resources.pop(role, None)
    else:
        resources[role] = previous
    abandon_unrecorded(manifest, locate, kind, role, name, logs,
                       f'{description or role} identity could not be recorded', receipt_key)


def create_owned(manifest, locate, kind, role, name, argv, logs, description=None, receipt_key=None):
    """Commit the intent, run one create command, then record the identity or remove it.

    The intent (kind, exact name and run labels) is committed before anything is
    created, so even a crash or a lost cleanup receipt leaves `down` a scope it
    can reconcile. If the intent cannot be committed nothing is created.
    """
    declare_pending(manifest, role, kind, name)
    write_manifest(locate(), manifest)
    try:
        run(argv, logs)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        # A failed `docker run -d` can still leave a created container behind.
        abandon_unrecorded(manifest, locate, kind, role, name, logs,
                           f'{description or role} creation failed', receipt_key)
    record_or_remove(manifest, locate, kind, role, name, logs,
                     description=description, receipt_key=receipt_key)


def validate_owned_resource(kind, row, expected, run_id):
    labels = (row.get('Config', {}).get('Labels') if kind == 'container'
              else row.get('Labels') if kind == 'network'
              else row.get('Config', {}).get('Labels')) or {}
    object_id = row.get('Id') or row.get('ID')
    name = row.get('Name', '').lstrip('/')
    if kind == 'image':
        name_matches = expected['name'] in (row.get('RepoTags') or [])
    else:
        name_matches = expected['name'] == name
    exact_labels = {'io.t3.issue28.stage': 's1b', 'io.t3.issue28.run': run_id}
    legacy_run_label = run_id[-6:]
    recovered_legacy = (expected.get('recovered_creation_output') is True
                        and re.fullmatch(r'[0-9a-f]{64}',
                                         expected.get('creation_evidence_sha256', ''))
                        and kind == 'container'
                        and expected['name'] == f't3-issue28-gateway-{run_id}'
                        and expected['labels'] == {'io.t3.issue28.stage': 's1b',
                                                   'io.t3.issue28.run': legacy_run_label})
    return (object_id == expected['id'] and expected['kind'] == kind
            and expected['run_id'] == run_id and name_matches
            and (expected['labels'] == exact_labels or recovered_legacy)
            and labels.get('io.t3.issue28.stage') == 's1b'
            and labels.get('io.t3.issue28.run') == expected['labels'].get('io.t3.issue28.run'))


def version_cmd(path, args, log):
    return run([path, *args], log)


def make_context(run_dir, log):
    context = run_dir / 'build-context'
    context.mkdir(mode=0o700)
    for name in SOURCE_FILES:
        shutil.copy2(CONTAINER / name, context / name)
    node_version = subprocess.run([str(NODE_EXECUTABLE), '--version'], capture_output=True,
                                  text=True, check=True, timeout=10).stdout.strip().removeprefix('v')
    if node_version != STAGE_MAP['node_version'] or not NODE_EXECUTABLE.is_file():
        raise RuntimeError('pinned Node.js program version is unavailable')
    shutil.copy2(NODE_EXECUTABLE, context / 'node')
    shutil.copy2(ROOT / 'bench' / 'v2' / 'tools' / 'model_policy.py', context / 'model_policy.py')
    if not RUNTIME.is_dir() or (RUNTIME / 't3').is_symlink():
        raise RuntimeError('pinned T3 runtime package unavailable or unexpectedly linked')
    shutil.copytree(RUNTIME, context / 't3-runtime', symlinks=True)
    return context


def write_policy(run_dir):
    config_dir = run_dir / 'config'
    config_dir.mkdir(mode=0o755)
    config_dir.chmod(0o755)
    target = run_dir / 'config' / 'bootstrap.json'
    target.write_text(json.dumps({'schema_version': 1, 'deny_all': True, 'targets': {}},
                                 sort_keys=True) + '\n', encoding='utf-8')
    target.chmod(0o444)
    return target


def make_input(run_dir):
    root = run_dir / 'input'
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    brief = root / 'brief.txt'
    brief.write_text('S1b deterministic container smoke input.\n', encoding='utf-8')
    digest = hashlib.sha256(brief.read_bytes()).hexdigest()
    (root / 'brief.sha256').write_text(digest + '\n', encoding='ascii')
    seed = b'S1b deterministic summary boundary fixture\n'
    for size in (32767, 32768, 32769):
        payload = (seed * ((size + len(seed) - 1) // len(seed)))[:size]
        (root / f'summary-{size}.txt').write_bytes(payload)
        (root / f'summary-{size}.sha256').write_text(hashlib.sha256(payload).hexdigest() + '\n',
                                                    encoding='ascii')
    for path in root.iterdir():
        path.chmod(0o444)
    return root


CANARY_ROLE_MARKER_PREFIX = 'ISSUE28_CANARY_ROLE='


def canary_task_templates(provider):
    """The exact, frozen task/prompt literals each finite role must be dispatched with.

    These strings are the only authority a captured ``delegate_task`` input or a
    provider-native prompt is matched against; the model parent must dispatch them
    byte for byte, with no added, removed, quoted or reformatted text.
    """
    return {
        'primary': CANARY_ROLE_MARKER_PREFIX + 'primary\n' + helper_command(provider) + '\n',
        'summary-32767': CANARY_ROLE_MARKER_PREFIX + 'summary-32767\n/bench/input/summary-32767.txt\n',
        'summary-32768': CANARY_ROLE_MARKER_PREFIX + 'summary-32768\n/bench/input/summary-32768.txt\n',
        'summary-32769': CANARY_ROLE_MARKER_PREFIX + 'summary-32769\n/bench/input/summary-32769.txt\n',
        'native-probe': CANARY_ROLE_MARKER_PREFIX + 'native-probe\nISSUE28_NATIVE_PROBE\n/bench/input/brief.txt\n'}


def canary_role_protocol(provider, target):
    """The finite canary role authority, built deterministically before launch.

    Each finite role carries its exact frozen marker line, the exact scope token an
    app child's task (or the provider-native probe's prompt) must contain, its dispatch
    kind and the complete frozen assignment literal (``task`` for an app child,
    ``prompt`` for the native probe) the host must capture verbatim. The frozen target
    binds provider/model/options selection.
    """
    templates = canary_task_templates(provider)
    roles = [{'role': 'primary', 'dispatch': 'app', 'report_key': 'primary',
              'marker': CANARY_ROLE_MARKER_PREFIX + 'primary',
              'required': [helper_command(provider)], 'task': templates['primary']}]
    roles += [{'role': f'summary-{size}', 'dispatch': 'app', 'report_key': str(size),
               'marker': CANARY_ROLE_MARKER_PREFIX + f'summary-{size}',
               'required': [f'/bench/input/summary-{size}.txt'], 'task': templates[f'summary-{size}']}
              for size in (32767, 32768, 32769)]
    roles.append({'role': 'native-probe', 'dispatch': 'native', 'report_key': None,
                  'marker': CANARY_ROLE_MARKER_PREFIX + 'native-probe',
                  'required': ['ISSUE28_NATIVE_PROBE'], 'prompt': templates['native-probe']})
    return {'schema_version': 1, 'provider': provider,
            'target': {'providerInstanceId': target['providerInstanceId'],
                       'model': target['model'], 'options': dict(target['options'])},
            'roles': roles}


def write_canary_role_protocol(run_dir, provider, target):
    """Freeze the role authority under the host-only protocol directory before dispatch."""
    root = run_dir / 'protocol'
    if root.is_symlink():
        raise RuntimeError('canary role protocol root may not be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    root.chmod(0o700)
    path = root / f'canary-roles-{provider}.json'
    if path.exists():
        raise RuntimeError('canary role protocol for this provider is already frozen')
    path.write_text(json.dumps(canary_role_protocol(provider, target), sort_keys=True, indent=2) + '\n',
                    encoding='utf-8')
    path.chmod(0o600)
    return path


def load_canary_role_protocol(run_dir, record):
    """Read the protocol the host froze before launch; any drift is a failure."""
    if not isinstance(record, dict) or not isinstance(record.get('file'), str) or not record['file']:
        raise RuntimeError('canary role protocol was not frozen before launch')
    path = run_dir / 'protocol' / record['file']
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('frozen canary role protocol is unavailable')
    if hashlib.sha256(path.read_bytes()).hexdigest() != record.get('sha256'):
        raise RuntimeError('frozen canary role protocol changed after launch')
    return json.loads(path.read_text(encoding='utf-8'))


def write_canary_prompt(input_root, provider, target):
    templates = canary_task_templates(provider)
    boundary_tasks = '\n'.join(templates[f'summary-{size}'].rstrip('\n') for size in (32767, 32768, 32769))
    prompt = (
        'This is one finite isolated benchmark canary. Use only the assigned provider target '
        f'providerInstanceId={provider}, model={target["model"]}, '
        f'options={json.dumps(target["options"], sort_keys=True)}. Do not change model/options, '
        'retry or start grandchildren. Dispatch each task argument byte for byte as the exact '
        'frozen literal shown below: no added, removed, reordered, quoted, indented or otherwise '
        'reformatted text, and no leading or trailing characters. A dispatch whose task text '
        'differs from the frozen literal in any byte is rejected and fails the run.\n'
        'Delegate exactly four app-owned children. The writer (primary) task must be exactly:\n'
        + templates['primary'] +
        'The three read-only summary boundary reader tasks must each be exactly:\n'
        + boundary_tasks + '\n'
        'In addition to those four app children, create exactly one provider-native child using '
        'the native tool with the same inherited model/options. Its prompt must be exactly:\n'
        + templates['native-probe'] +
        'The native child may only read /bench/input/brief.txt and return only its 64-character '
        'SHA-256 as the complete final result. Do not supply another model alias or effort. If '
        'native inheritance is unavailable, report blocked and do not substitute. Wait until this '
        'native child is completed, then close its owned runtime if that native tool requires it. '
        'No other native children are authorized.\n'
        f'The primary writes only under /bench/ws/canary/{provider}/task-1, runs the frozen helper '
        'exactly as shown in its task, and GETs http://github.bench.test:8080/api/v3/user. Preserve '
        'a compact terminal summary. The primary child must use that exact output path, not '
        'canary/task-1 or any other directory. The parent must not write helper output or repair a '
        'child write.\n'
        'Each boundary reader returns its fixture file bytes verbatim as the final result; do not '
        'generate padding. Record each returned task ID under summary_boundary_task_ids with keys '
        '32767, 32768 and 32769. The harness will read task_status.summary directly and compare '
        'exact UTF-8 bytes against each fixture.\n'
        'Before finishing, use your authenticated task_status tool for all four accepted task IDs. '
        'Each must be terminal with workState=result_available and hasPendingChildRuns=false. A '
        'completed parent with running children fails. Keep the entire task_status result for each '
        'call in the host tool transport. Await the existing tasks through completion '
        'notifications; do not recreate them. If any child is blocked on approval, fails, or cannot '
        'finish within this finite run, cancel only that owned child with task_cancel and observe '
        'terminal state with task_status. Do not claim success for cancelled or unfinished boundary '
        'results.\n'
        'After all task_status calls report terminal, attempt one same-scope tracked follow-up only '
        'if the active T3 tools and host policy support it. Use the same target/options, report the '
        'new task ID, and confirm the original summary is unchanged. Otherwise report continuation '
        'not allowed. Even when refused, hash the complete original task_status.summary with '
        'SHA-256, read that same task_status again, and confirm it is unchanged; no new task may be '
        'created for the refused route. Do not contact production GitHub. Return exactly one JSON '
        'object with input_sha256, github_login, primary_task_id, summary_boundary_task_ids, and '
        'tracked_followup fields. tracked_followup must contain status (supported or not_allowed), '
        'original_task_id, new_task_id, original_summary_sha256_before_followup (a SHA-256 string), '
        'and original_unchanged (boolean).'
    )
    prompt_path = input_root / f'canary-{provider}.txt'
    prompt_path.write_text(prompt + '\n', encoding='utf-8')
    prompt_path.chmod(0o444)
    return prompt_path


def certificate(run_dir, log):
    """Create a per-run CA and a non-CA gateway leaf it signs.

    Rustls clients (Codex) reject a CA certificate presented as the server
    certificate, so agents trust only the CA and the gateway serves the leaf.
    """
    secret_dir = run_dir / 'tls'
    secret_dir.mkdir(mode=0o700)
    ca_cert, ca_key = secret_dir / 'ca.crt', secret_dir / 'ca.key'
    cert, key, request = secret_dir / 'gateway.crt', secret_dir / 'gateway.key', secret_dir / 'gateway.csr'
    extensions = secret_dir / 'gateway.ext'
    extensions.write_text('basicConstraints=critical,CA:FALSE\n'
                          'keyUsage=critical,digitalSignature,keyEncipherment\n'
                          'extendedKeyUsage=serverAuth\n'
                          'subjectAltName=DNS:gateway.bench.test\n', encoding='ascii')
    run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(ca_key),
         '-out', str(ca_cert), '-days', '2', '-subj', '/CN=t3 issue28 bench gateway CA',
         '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
         '-addext', 'keyUsage=critical,keyCertSign,cRLSign'], log)
    run(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
         '-out', str(request), '-subj', '/CN=gateway.bench.test'], log)
    run(['openssl', 'x509', '-req', '-in', str(request), '-CA', str(ca_cert), '-CAkey', str(ca_key),
         '-CAcreateserial', '-out', str(cert), '-days', '2', '-extfile', str(extensions)], log)
    # The CA key signs only this leaf; remove it so nothing else can be issued.
    ca_key.unlink()
    request.unlink()
    for path in (ca_cert, cert, key):
        path.chmod(0o444)
    return ca_cert, cert, key


def docker_ok(log):
    info = subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}|{{.Driver}}|{{.SecurityOptions}}'],
                          capture_output=True, text=True, check=True, timeout=30)
    with log.open('a', encoding='utf-8') as stream:
        stream.write('Docker daemon information captured.\n')
    parts = info.stdout.strip().split('|', 2)
    if len(parts) != 3 or 'rootless' not in parts[2]:
        raise RuntimeError('expected rootless Docker daemon')
    return {'version': parts[0], 'storage_driver': parts[1], 'rootless': True}


def image_provenance(image, log):
    inspected = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                               capture_output=True, text=True, check=True, timeout=30)
    result = {'image_id': inspected.stdout.strip()}
    for name, executable in (('node', 'node'), ('npm', 'npm'), ('python', 'python3'),
                             ('claude', 'claude'), ('codex', 'codex'), ('t3', 't3')):
        # Labelled, so even a leftover probe container is attributable to this run.
        version = subprocess.run(['docker', 'run', '--rm', '--network', 'none',
                                  '--label', 'io.t3.issue28.stage=s1b',
                                  '--label', 'io.t3.issue28.run=' + image.split(':', 1)[1],
                                  '--entrypoint', executable, image, '--version'],
                                 capture_output=True, text=True, check=True, timeout=60)
        result[name] = version.stdout.strip().splitlines()[-1]
    with log.open('a', encoding='utf-8') as stream:
        stream.write('Image and program provenance captured.\n')
    return result


def isolation_inventory(name, log):
    result = subprocess.run(['docker', 'inspect', '--format', '{{json .Mounts}}|{{json .NetworkSettings.Networks}}', name],
                            capture_output=True, text=True, check=True, timeout=20)
    with log.open('a', encoding='utf-8') as stream:
        stream.write('Container mount and network inventory captured.\n')
    mounts_text, networks_text = result.stdout.strip().split('|', 1)
    mounts = json.loads(mounts_text)
    networks = json.loads(networks_text)
    return mounts, networks


def verify_isolation(names, private_net, egress_net, config, ca_cert, cert, key, task_input, workspace, raw, state, logs):
    expected_agent = {
        '/bench/input': (task_input, False),
        '/bench/ws': (workspace, True),
        '/bench/results': (raw, True),
        '/bench/t3': (state, True),
        '/opt/bench-home/.claude/projects': (raw / 'claude-projects', True),
        '/opt/bench-home/.codex/sessions': (raw / 'codex-sessions', True),
                '/bench/config': (config.parent, False),
        '/run/secrets/bench-gateway-ca.pem': (ca_cert, False),
    }
    agent_mounts, agent_networks = isolation_inventory(names['agent'], logs)
    agent = {item['Destination']: (Path(item['Source']), item['RW']) for item in agent_mounts}
    if agent != expected_agent or set(agent_networks) != {private_net}:
        raise RuntimeError('agent container mounts or network attachments differ from policy')
    _gateway_mounts, gateway_networks = isolation_inventory(names['gateway'], logs)
    _github_mounts, github_networks = isolation_inventory(names['github'], logs)
    if set(gateway_networks) != {private_net, egress_net} or set(github_networks) != {private_net}:
        raise RuntimeError('sidecar or gateway network attachments differ from policy')
    expected_gateway = {config.parent, cert, key}
    if {Path(item['Source']) for item in _gateway_mounts} != expected_gateway:
        raise RuntimeError('gateway mount set differs from policy')
    if _github_mounts:
        raise RuntimeError('synthetic GitHub sidecar must have no host mounts')
    return {'agent_mounts': sorted(agent), 'agent_networks': [private_net],
            'gateway_mounts': sorted(item['Destination'] for item in _gateway_mounts),
            'gateway_networks': sorted(gateway_networks), 'github_networks': [private_net],
            'mounts_verified': True}


def setup(args):
    private_dir(RESULTS)
    if not SECRET_ENV.is_file() or SECRET_ENV.is_symlink():
        raise RuntimeError('runtime API-key env file is unavailable')
    info = SECRET_ENV.stat()
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        raise RuntimeError('runtime API-key env file permissions rejected')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(3)
    run_dir = RESULTS / run_id
    run_dir.mkdir(mode=0o700)
    logs = run_dir / 'private.log'
    logs.touch(mode=0o600)
    docker_runtime = docker_ok(logs)
    context = make_context(run_dir, logs)
    config = write_policy(run_dir)
    task_input = make_input(run_dir)
    ca_cert, cert, key = certificate(run_dir, logs)
    workspace = run_dir / 'workspace'
    raw = run_dir / 'raw'
    state = run_dir / 't3-state'
    workspace.mkdir(mode=0o700)
    raw.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    (raw / 'claude-projects').mkdir(mode=0o777)
    (raw / 'codex-sessions').mkdir(mode=0o777)
    # Rootless Docker maps the host owner to container UID 0. These mounts are
    # reachable only inside the mode-0700 per-run results directory.
    workspace.chmod(0o777)
    raw.chmod(0o777)
    state.chmod(0o700)

    image = 't3-issue28-s1b:' + run_id
    private_net = 't3-issue28-private-' + run_id
    egress_net = 't3-issue28-egress-' + run_id
    names = {'agent': 't3-issue28-agent-' + run_id,
             'gateway': 't3-issue28-gateway-' + run_id,
             'github': 't3-issue28-github-' + run_id}
    manifest = {'run_id': run_id, 'image': image, 'networks': [private_net, egress_net],
                'containers': names, 'status': 'preparing', 't3_version': T3_VERSION,
                'base_image': STAGE_MAP['base_image'],
                'claude_version': CLAUDE_VERSION, 'codex_version': CODEX_VERSION,
                'node_version': STAGE_MAP['node_version'],
                'node_binary_sha256': hashlib.sha256(NODE_EXECUTABLE.read_bytes()).hexdigest(),
                'model_policy_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
                't3_binary_sha256': hashlib.sha256((RUNTIME / 't3').read_bytes()).hexdigest(),
                'docker': docker_runtime, 'canary_attempts': [],
                # Every recovery map `down` reads exists from the first write, so a
                # crash after any later write-ahead intent leaves a manifest it accepts.
                'created_resources': {}, 'pending_resources': {}, 'unrecorded_resources': {}}
    manifest['build_source_sha256'] = {
        name: hashlib.sha256((context / name).read_bytes()).hexdigest()
        for name in (*SOURCE_FILES, 'model_policy.py')}
    manifest_path = run_dir / 'resource-manifest.json'
    write_manifest(manifest_path, manifest)
    print(json.dumps({'status': 'preparing', 'run_id': run_id}), flush=True)

    def locate():
        return manifest_path

    try:
        labels = ['--label', 'io.t3.issue28.stage=s1b', '--label', f'io.t3.issue28.run={run_id}']
        # Each create is followed by bounded identity recording; an identity that
        # cannot be committed has its resource removed by run labels and exact name.
        create_owned(manifest, locate, 'image', 'image', image,
                     ['docker', 'build', *labels, '--tag', image,
                      '--build-arg', f'T3_VERSION={T3_VERSION}',
                      '--build-arg', f'CLAUDE_VERSION={CLAUDE_VERSION}',
                      '--build-arg', f'CODEX_VERSION={CODEX_VERSION}',
                      str(context)], logs)
        manifest['provenance'] = image_provenance(image, logs)
        create_owned(manifest, locate, 'network', 'network_private', private_net,
                     ['docker', 'network', 'create', *labels, '--internal', private_net], logs)
        create_owned(manifest, locate, 'network', 'network_egress', egress_net,
                     ['docker', 'network', 'create', *labels, egress_net], logs)
        create_owned(manifest, locate, 'container', 'container_gateway', names['gateway'],
                     gateway_bootstrap_command(names['gateway'], egress_net, config.parent,
                                               cert, key, image), logs)
        run(['docker', 'network', 'connect', '--alias', 'gateway.bench.test',
             private_net, names['gateway']], logs)
        create_owned(manifest, locate, 'container', 'container_github', names['github'],
                     ['docker', 'run', '-d', '--name', names['github'], '--network', private_net,
                      *labels, '--network-alias', 'github.bench.test', '--entrypoint', 'python3',
                      image, '/opt/bench/github_sidecar.py'], logs)
        create_owned(manifest, locate, 'container', 'container_agent', names['agent'],
                     agent_command(names['agent'], private_net, task_input, workspace, raw,
                                   state, config.parent, ca_cert, image), logs)
        manifest['isolation'] = verify_isolation(
            names, private_net, egress_net, config, ca_cert, cert, key, task_input,
            workspace, raw, state, logs)
        manifest['status'] = 'running'
        write_manifest(manifest_path, manifest)
        print(json.dumps({'status': 'running', 'run_id': run_id, 'resources_recorded': True}))
    except Exception:
        manifest['status'] = 'partial-failure'
        try:
            write_manifest(manifest_path, manifest)
        except OSError:
            pass  # Committed identities already give `down` its cleanup authority.
        raise


def find_manifest(run_id):
    private_dir(RESULTS)
    if not re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{6}', run_id):
        raise RuntimeError('task-owned run ID rejected')
    matches = list(RESULTS.glob(run_id + '/resource-manifest.json'))
    if len(matches) != 1 or matches[0].is_symlink():
        raise RuntimeError('task-owned resource manifest not found')
    return matches[0]


def manage(args):
    path = find_manifest(args.run_id)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    logs = path.parent / 'private.log'
    if args.command == 'preflight':
        owned = manifest['created_resources']['container_agent']
        if not validate_owned_resource('container', docker_inspect_json('container', owned['id']), owned, args.run_id):
            raise RuntimeError('observation preflight agent identity changed')
        code = ('import os,json,pathlib; p=pathlib.Path("/bench/t3/userdata/statev2.sqlite"); '
                's=p.stat(); print(json.dumps({"process_uid":os.getuid(),"state_owner_uid":s.st_uid,'
                '"base_process_can_write_state":os.access(p,os.W_OK)}))')
        result = subprocess.run(['docker', 'exec', owned['id'], 'python3', '-c', code],
                                capture_output=True, text=True, timeout=10, check=True)
        observed = json.loads(result.stdout)
        positive_code = """import socket, json, ipaddress
rows = []
for host in ('api.anthropic.com', 'api.openai.com'):
    ips = sorted({x[4][0] for x in socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
                  if ipaddress.ip_address(x[4][0]).is_global})[:2]
    for ip in ips:
        try:
            with socket.create_connection((ip, 443), timeout=3):
                reached = True
        except OSError:
            reached = False
        rows.append({'host': host, 'ip': ip, 'reachable': reached})
print(json.dumps(rows))
"""
        positive = subprocess.run(['docker', 'exec', manifest['containers']['gateway'], 'python3', '-c', positive_code],
                                  capture_output=True, text=True, timeout=20, check=True)
        targets = json.loads(positive.stdout)
        negative_code = """import socket, json, sys
rows = json.loads(sys.argv[1])
for row in rows:
    try:
        with socket.create_connection((row['ip'], 443), timeout=1.5):
            row['worker_reachable'] = True
    except OSError:
        row['worker_reachable'] = False
print(json.dumps(rows))
"""
        negative = subprocess.run(['docker', 'exec', owned['id'], 'python3', '-c', negative_code, json.dumps(targets)],
                                  capture_output=True, text=True, timeout=15, check=True)
        probes = json.loads(negative.stdout)
        observed['literal_provider_network_probes'] = probes
        observed['literal_provider_network_verified'] = ({row['host'] for row in probes} == {'api.anthropic.com', 'api.openai.com'} and
            all(row['reachable'] is True and row['worker_reachable'] is False for row in probes))
        profile_code = """import json, os, pathlib
path = pathlib.Path('/bench/t3/userdata/statev2.sqlite')
checks = {}
for operation, flags in (('state_read_denied', os.O_RDONLY), ('state_write_denied', os.O_WRONLY)):
    try:
        descriptor = os.open(path, flags); os.close(descriptor); checks[operation] = False
    except PermissionError:
        checks[operation] = True
status = pathlib.Path('/proc/self/status').read_text()
checks['uid_is_worker'] = os.geteuid() == 1001
checks['no_new_privileges'] = 'NoNewPrivs:\t1' in status
checks['capabilities_dropped'] = 'CapEff:\t0000000000000000' in status and 'CapBnd:\t0000000000000000' in status
checks['owner_state_directory_denied'] = not os.access('/bench/t3', os.R_OK | os.W_OK | os.X_OK)
probe = pathlib.Path('/bench/ws/.permission-probe')
probe.write_text('permitted worker write'); checks['workspace_write_allowed'] = probe.read_text() == 'permitted worker write'; probe.unlink()
checks['input_read_allowed'] = pathlib.Path('/bench/input/brief.txt').is_file()
print(json.dumps(checks))
"""
        from native_exec import DROP
        profile = subprocess.run(['docker', 'exec', owned['id'], *DROP, 'python3', '-c', profile_code],
                                 capture_output=True, text=True, timeout=20, check=True)
        observed['native_process_profile_checks'] = json.loads(profile.stdout)
        observed['native_cli_checks'] = {}
        for program, version in (('claude', CLAUDE_VERSION), ('codex', CODEX_VERSION)):
            cli = subprocess.run(['docker', 'exec', owned['id'], program, '--version'],
                                 capture_output=True, text=True, timeout=20)
            observed['native_cli_checks'][program] = cli.returncode == 0 and version in cli.stdout
        # T3 must resolve every provider command it would spawn to the shim;
        # a direct native binary would keep coordinator credentials.
        resolution = subprocess.run(['docker', 'exec', owned['id'], 'python3', '-c',
                                     'import json,sys; sys.path.insert(0,"/opt/bench"); import native_exec; '
                                     'print(json.dumps(native_exec.t3_binary_resolution()))'],
                                    capture_output=True, text=True, timeout=20, check=False)
        try:
            report = json.loads(resolution.stdout.splitlines()[-1])
            if not isinstance(report, dict):
                raise ValueError('resolution probe returned a non-object')
        except (IndexError, ValueError):
            report = {'verified': False, 'reason': 'resolution probe unavailable'}
        observed['native_binary_resolution'] = report
        verified = preflight_profile_verified(observed)
        observed.update(status='passed' if verified else 'failed',
                        native_protected_store_denial='verified Linux UID/capability boundary' if verified else 'failed',
                        reason='T3 owns launches; its provider commands resolve to the shim and both pinned native executables use the measured Linux credential-drop profile; canary acceptance separately requires worker-UID shim launches in the coordinator-only log; no authentication-creation probe was performed',
                        build_source_sha256=manifest['build_source_sha256'])
        manifest['observer_boundary_preflight'] = observed
        write_manifest(path, manifest)
        print(json.dumps(observed, sort_keys=True))
        return 0 if verified and observed['literal_provider_network_verified'] else 2
    if args.command == 'smoke':
        with socket.socket() as fixture:
            fixture.bind(('127.0.0.1', 0))
            fixture.listen(4)
            fixture.settimeout(0.2)
            port = fixture.getsockname()[1]
            positive = host_loopback_positive(fixture, port)
            with logs.open('ab') as errors:
                smoke_run = subprocess.run(['docker', 'exec', '-e', f'BENCH_HOST_LOOPBACK_PORT={port}',
                                            manifest['containers']['agent'], 'python3', '/opt/bench/smoke.py'],
                                           stdout=subprocess.PIPE, stderr=errors, text=True,
                                           timeout=120, check=False)
            code = smoke_run.returncode
            unexpected = loopback_connections_after(fixture)
        with logs.open('a', encoding='utf-8') as stream:
            stream.write(smoke_run.stdout)
        probes = smoke_probe_results(smoke_run.stdout)
        manifest['host_loopback_control'] = {'host_positive_connect': positive,
                                             'container_connections_accepted': unexpected}
        # Negatives count only alongside their container-side positives from this same run.
        manifest['smoke_network_controls'] = probes
        manifest['smoke_passed'] = (code == 0 and positive and unexpected == 0
                                    and probes['paired_controls_passed'])
        forwarded = gateway_forward_count(manifest['containers']['gateway'], logs)
        manifest['smoke_model_requests'] = forwarded
        if forwarded != 0:  # None means the gateway log was unavailable.
            manifest['smoke_passed'] = False
        write_manifest(path, manifest)
        print(json.dumps({'smoke': 'passed' if manifest['smoke_passed'] else 'failed',
                          'exit_code': code, 'model_requests': forwarded}))
        return 0 if manifest['smoke_passed'] else (code or 2)
    if args.command == 'catalog':
        result = driver(manifest, ['--catalog-only'], logs)
        targets = result.get('targets')
        catalog = result.get('catalog')
        if not isinstance(targets, dict) or not isinstance(catalog, dict):
            raise RuntimeError('isolated catalog discovery returned incomplete evidence')
        validated = model_policy.validate_frozen_map(catalog, targets, role='canary')
        try:
            metadata = subprocess.run(['docker', 'exec', manifest['containers']['gateway'], 'python3',
                                       '/opt/bench/identity_metadata.py', json.dumps(validated)],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=50)
            identity_records = json.loads(metadata.stdout)
        except (ValueError, subprocess.TimeoutExpired):
            identity_records = {'verified': False, 'reason': 'metadata command unavailable or incomplete'}
        manifest['response_identity_metadata'] = identity_records
        runtime_path = path.parent / 'config' / 'runtime-targets.json'
        runtime_path.write_text(json.dumps({'schema_version': 1, 'targets': validated,
                                           'response_identity_metadata': identity_records},
                                           sort_keys=True, indent=2) + '\n', encoding='utf-8')
        runtime_path.chmod(0o444)
        (path.parent / 'config').chmod(0o555)
        configure_gateway(manifest, runtime_path, logs)
        manifest['runtime_targets'] = validated
        manifest['target_manifest_sha256'] = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
        manifest['status'] = 'catalog-locked'
        write_manifest(path, manifest)
        print(json.dumps({'catalog': 'discovered-and-locked', 'targets': validated,
                          'target_manifest_sha256': manifest['target_manifest_sha256'],
                          'paid_requests': 0}, sort_keys=True))
        return 0
    if args.command == 'canary':
        if not manifest.get('smoke_passed'):
            raise RuntimeError('live canaries are blocked until the no-model smoke passes')
        if manifest.get('observer_boundary_preflight', {}).get('status') != 'passed':
            raise RuntimeError('live canaries are blocked: native worker denial of observation-store writes is unverified; network smoke is insufficient')
        if manifest['observer_boundary_preflight'].get('literal_provider_network_verified') is not True:
            raise RuntimeError('direct-provider literal-IP isolation lacks gateway positive and worker negative controls')
        if manifest['observer_boundary_preflight'].get('native_binary_resolution', {}).get('verified') is not True:
            raise RuntimeError('live canaries are blocked: T3 provider commands are not shown to resolve to the worker shim')
        if manifest.get('status') == 'model-mismatch-or-unverified':
            raise RuntimeError('live canaries stopped after an unverified or mismatched model transcript')
        if any(row.get('provider') == args.provider for row in manifest.get('canary_attempts', [])):
            raise RuntimeError('this provider canary slot was already attempted; no retry is allowed')
        policy = {'targets': manifest.get('runtime_targets', {})}
        if set(policy['targets']) != {'codex', 'claudeAgent'}:
            raise RuntimeError('container live catalog has not been frozen and locked')
        from identity_metadata import valid_identity
        identities = manifest.get('response_identity_metadata', {}).get('identities', {})
        if not all(valid_identity(identities.get(p), p, t['model']) for p, t in policy['targets'].items()):
            raise RuntimeError('primary provider response identities must be verified and frozen before dispatch')
        hashes = manifest.get('build_source_sha256', {})
        for filename in (*SOURCE_FILES, 'model_policy.py'):
            source = (ROOT / 'bench/v2/tools/model_policy.py' if filename == 'model_policy.py'
                      else CONTAINER / filename)
            if hashes.get(filename) != hashlib.sha256(source.read_bytes()).hexdigest():
                raise RuntimeError('current source differs from the built canary image')
        # Read before the slot is consumed; an unreadable coordinator log blocks dispatch.
        native_before = read_native_launches(manifest['created_resources']['container_agent']['id'], logs,
                                             allow_missing=True)
        # Baselines also come before the slot is used: without them the deltas are unprovable.
        github_before = github_event_count(manifest['containers']['github'], logs)
        gateway_before = gateway_rejection_count(manifest['containers']['gateway'], logs)
        if github_before is None or gateway_before is None:
            raise RuntimeError('live canaries are blocked: synthetic GitHub or gateway log baseline is unavailable')
        prompt_name = f"canary-{args.provider}.txt"
        prompt_path = path.parent / 'input' / prompt_name
        role_protocol_path = write_canary_role_protocol(path.parent, args.provider,
                                                        policy['targets'][args.provider])
        role_protocol_sha256 = hashlib.sha256(role_protocol_path.read_bytes()).hexdigest()
        write_canary_prompt(path.parent / 'input', args.provider,
                            policy['targets'][args.provider])
        canary = {'provider': args.provider, 'slot': 'owner-approved-repair8',
                  'phase': 'dispatching', 'gateway_rejections_before': gateway_before,
                  'role_protocol': {'file': role_protocol_path.name, 'sha256': role_protocol_sha256},
                  'launch': {'status': 'not-accepted', 'thread_id': None}}
        manifest['canary_attempts'].append(canary)
        write_manifest(path, manifest)
        workspace_before = workspace_inventory(path.parent / 'workspace')
        # A unique title, persisted before dispatch, lets a lost launch response be
        # resolved by listing threads instead of launching again.
        launch_title = f'Issue 28 S1b {args.provider} canary {secrets.token_hex(8)}'
        canary['launch_title'] = launch_title
        write_manifest(path, manifest)
        try:
            result = driver(manifest, ['--launch-provider', args.provider, '--prompt-file',
                                       '/bench/input/' + prompt_name, '--title', launch_title], logs)
        except RuntimeError as exc:
            gateway_after_launch_error = gateway_rejection_count(
                manifest['containers']['gateway'], logs)
            canary.update({'phase': 'launch-error',
                           'launch': {'status': 'error', 'thread_id': None,
                                      'error_route': str(exc),
                                      'gateway_rejections_after': gateway_after_launch_error,
                                      'gateway_rejection_delta': count_delta(gateway_after_launch_error,
                                                                             gateway_before),
                                      'recovery': resolve_uncertain_launch(manifest, launch_title, logs)}})
            write_manifest(path, manifest)
            raise
        expected = policy['targets'][args.provider]['model']
        thread_id = result.get('threadId')
        if not driver_module.opaque_thread_id(thread_id):
            canary.update({'phase': 'launch-result-invalid',
                           'launch': {'status': 'invalid-response', 'thread_id': None,
                                      'gateway_rejections_after': gateway_rejection_count(
                                          manifest['containers']['gateway'], logs)}})
            write_manifest(path, manifest)
            raise RuntimeError('accepted launch returned an invalid opaque thread ID')
        # Persist the authoritative accepted identity before any wait/read call.
        canary.update({'phase': 'launched', 'launch': {
            'status': 'accepted', 'thread_id': thread_id,
            'launch_status': result.get('status'),
            'gateway_rejections_after': gateway_rejection_count(manifest['containers']['gateway'], logs)}})
        write_manifest(path, manifest)
        try:
            wait = driver(manifest, ['--wait-thread', thread_id,
                                 '--expected-message', '/bench/input/' + prompt_name], logs)
        except RuntimeError as exc:
            canary.update({'phase': 'wait-error', 'wait_error_route': str(exc),
                           'recovery': 'accepted thread identity retained; rerun wait with recorded ID'})
            write_manifest(path, manifest)
            raise
        audit = subprocess.run(['docker', 'exec', manifest['containers']['agent'], 'python3',
                                '/opt/bench/audit_models.py', '--provider', args.provider],
                               stdout=subprocess.PIPE, stderr=logs.open('ab'), text=True,
                               timeout=30, check=False)
        try:
            audit_result = json.loads(audit.stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            audit_result = {'verified': False, 'error': 'model-audit result unavailable'}
        audit_result['readback_model_matches'] = (wait.get('readback_model') == expected
                                                  and wait.get('readback_provider') == args.provider)
        audit_result['original_message_exact'] = wait.get('original_message_exact') is True
        audit_result['final_message_retrieval_exact'] = wait.get('final_message_retrieval_exact') is True
        canary_result = wait.get('canary_result')
        owned = {}
        try:
            captured = capture_parent_observations(manifest, thread_id, path.parent, logs)
            ids = ([canary_result['primary_task_id']]
                   + list(canary_result['summary_boundary_task_ids'].values()))
            followup_id = canary_result.get('tracked_followup', {}).get('new_task_id')
            if followup_id is not None:
                ids.append(followup_id)
            if len(ids) not in {4, 5} or len(set(ids)) != len(ids):
                raise ValueError('finite canary task IDs are missing or duplicated')
            owned = host_observations.verify_owned_tasks(
                captured, ids, policy['targets'][args.provider], native_probe=True,
                expected_input_sha256=(path.parent / 'input/brief.sha256').read_text().strip())
            audit_result['owned_children_terminal'] = owned['verified']
            protocol = load_canary_role_protocol(path.parent, canary.get('role_protocol'))
            evidence = actor_bound_evidence(captured, canary_result, args.provider, protocol)
            audit_result.update(evidence)
            write_canary_role_receipt(path.parent, args.provider, canary, protocol, canary_result, evidence)
            audit_result['native_child_visibility'] = owned['native_child_visibility']
            audit_result['native_probe_checks'] = owned['native_probe_checks']
            audit_result['pending_approvals'] = owned['pending_approvals']
            client = host_observations.CapturedTaskClient(captured)
            tools = [{'name': 'task_status', 'inputSchema': {'type': 'object',
                      'properties': {'taskId': {'type': 'string'}}, 'required': ['taskId']}}]
            wait['summary_boundary_audit'] = driver_module.verify_summary_boundary_tasks(
                client, tools, canary_result, path.parent / 'input', path.parent / 'observations')
            wait['tracked_followup_audit'] = driver_module.verify_tracked_followup(
                client, tools, canary_result, path.parent / 'observations')
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            audit_result['owned_children_terminal'] = False
            audit_result['host_observation_error'] = str(exc)
        boundary = wait.get('summary_boundary_audit')
        boundary_rows = boundary.get('records') if isinstance(boundary, dict) else None
        audit_result['summary_boundary_verified'] = (
            isinstance(boundary, dict) and boundary.get('verified') is True
            and isinstance(boundary_rows, list) and len(boundary_rows) == 3
            and {row.get('expected_utf8_bytes') for row in boundary_rows if isinstance(row, dict)}
            == {32767, 32768, 32769}
            and all(isinstance(row, dict) and row.get('exact') is True
                    and row.get('actual_utf8_bytes') == row.get('expected_utf8_bytes')
                    for row in boundary_rows))
        followup_audit = wait.get('tracked_followup_audit')
        # Fail-closed owner decision: a refused continuation is recorded, never a pass.
        audit_result['tracked_followup_recorded'] = tracked_followup_accepted(followup_audit)
        audit_result['input_hash_reported'] = (
            isinstance(canary_result, dict)
            and canary_result.get('input_sha256') ==
            (path.parent / 'input' / 'brief.sha256').read_text(encoding='ascii').strip())
        audit_result['github_login_reported'] = (
            isinstance(canary_result, dict) and canary_result.get('github_login') == 'bench-user')
        audit_result['thread_completed'] = wait.get('status') == 'completed' and not wait.get('timed_out')
        # An unavailable log after the run is missing evidence, never a pass.
        github_delta = count_delta(github_event_count(manifest['containers']['github'], logs), github_before)
        audit_result['synthetic_github_reached'] = github_delta is not None and github_delta > 0
        gateway_after = gateway_rejection_count(manifest['containers']['gateway'], logs)
        audit_result['gateway_policy_clean'] = count_delta(gateway_after, gateway_before) == 0
        audit_result['assigned_helper_output_valid'] = helper_output_valid(
            path.parent / 'workspace', args.provider, path.parent / 'input' / 'brief.sha256',
            [row['provider'] for row in manifest['canary_attempts']])
        workspace_changes = workspace_changes_since(path.parent / 'workspace', workspace_before)
        audit_result['workspace_write_scope_valid'] = workspace_write_scope_valid(
            path.parent / 'workspace', workspace_changes, args.provider)
        canary['workspace_changes'] = workspace_changes
        response_audit = gateway_model_observations(manifest['containers']['gateway'],
                                                   expected, args.provider, logs, identities[args.provider]['response_model_id'])
        audit_result['provider_response_observations'] = response_audit
        native_launches = canary_native_launch_audit(
            manifest['created_resources']['container_agent']['id'], native_before, args.provider, logs)
        audit_result['native_launch_shim_observed'] = native_launches
        audit_result['transcript_audit_verified'] = audit_result.get('verified') is True
        audit_result['verified'] = (response_audit['verified']
                                    and audit_result['thread_completed']
                                    and audit_result['readback_model_matches']
                                    and audit_result['original_message_exact']
                                    and audit_result['final_message_retrieval_exact']
                                    and audit_result['summary_boundary_verified']
                                    and audit_result['tracked_followup_recorded']
                                    and audit_result['input_hash_reported']
                                    and audit_result['github_login_reported']
                                    and audit_result['synthetic_github_reached']
                                    and audit_result['gateway_policy_clean']
                                    and audit_result['assigned_helper_output_valid']
                                    and audit_result.get('helper_invocation_host_observed') is True
                                    and audit_result.get('host_recorded_writes_bound') is True
                                    and audit_result.get('canary_roles_bound_to_host_dispatch') is True
                                    and native_launches['verified'] is True
                                    and audit_result['workspace_write_scope_valid'])
        audit_result['verified'] &= audit_result.get('owned_children_terminal') is True
        audit_result['transport_verified'] = audit_result['verified']
        # Advertised lifecycle capabilities and app-owned rows cannot prove
        # coverage of invisible provider-native channels. Keep this required
        # live observation open rather than weakening the quality-start gate.
        audit_result['native_child_visibility_verified'] = owned.get('native_child_visibility_verified') is True
        audit_result['verified'] &= audit_result['native_child_visibility_verified']
        if not audit_result['native_child_visibility_verified']:
            audit_result['remaining_live_gap'] = 'provider-native child visibility has no independent live probe'
        canary.update({'phase': 'completed' if audit_result['thread_completed'] else 'unfinished',
                       'run_status': wait.get('status'), 'model_audit': audit_result})
        if not audit_result.get('verified'):
            manifest['status'] = 'model-mismatch-or-unverified'
        write_manifest(path, manifest)
        print(json.dumps({'canary_started': True, 'provider': args.provider,
                          'slot': canary['slot'], 'expected_model': expected, 'thread_id': thread_id,
                          'status': wait.get('status'), 'model_audit': audit_result,
                          'prompt_staged': prompt_path.is_file()},
                         sort_keys=True))
        return 0 if audit_result.get('verified') else 2
    if args.command == 'down':
        statuses = {}
        # A manifest committed before any identity was recorded (a crash after the
        # first write-ahead intent) has no created map; it means none recorded.
        resources = manifest.get('created_resources', {})
        expected_containers = {'agent': f't3-issue28-agent-{args.run_id}',
                               'gateway': f't3-issue28-gateway-{args.run_id}',
                               'github': f't3-issue28-github-{args.run_id}'}
        if (manifest.get('run_id') != args.run_id
                or manifest.get('image') != f't3-issue28-s1b:{args.run_id}'
                or manifest.get('networks') != [f't3-issue28-private-{args.run_id}',
                                                  f't3-issue28-egress-{args.run_id}']
                or manifest.get('containers') != expected_containers
                or not isinstance(resources, dict)
                or set(resources) - {'image', 'network_private', 'network_egress',
                                     'container_gateway', 'container_github', 'container_agent'}):
            raise RuntimeError('cleanup manifest failed run scope or schema validation')
        scopes = {'container_agent': ('container', expected_containers['agent']),
                  'container_github': ('container', expected_containers['github']),
                  'container_gateway': ('container', expected_containers['gateway']),
                  'network_private': ('network', manifest['networks'][0]),
                  'network_egress': ('network', manifest['networks'][1]),
                  'image': ('image', manifest['image'])}
        # Resources that may exist without a committed immutable identity.
        unrecorded = unrecorded_cleanup_roles(manifest, scopes, args.run_id)
        clean = True
        reconciled = {}
        for role, (kind, name) in scopes.items():
            statuses[role], recorded_clean = cleanup_recorded(
                manifest, path, logs, role, kind, resources.get(role), args.run_id)
            clean &= recorded_clean
            if role not in unrecorded:
                continue
            if recorded_clean:
                reconciled[role] = reconcile_by_run_labels(kind, args.run_id, name, logs)
            else:
                reconciled[role] = {'absence_confirmed': False,
                                    'reason': 'recorded identity preserved; exact-name cleanup deferred'}
            clean &= reconciled[role]['absence_confirmed'] is True
        if reconciled:
            manifest['unrecorded_cleanup'] = reconciled
        # Stopped means nothing labelled for this run is left, recorded or not.
        manifest['labelled_leftovers'] = labelled_leftovers(args.run_id, logs)
        clean &= manifest['labelled_leftovers']['absence_confirmed']
        manifest['status'] = 'stopped' if clean else 'cleanup-failed'
        manifest['cleanup'] = statuses
        write_manifest(path, manifest)
        print(json.dumps({'resources_stopped': clean}))
        return 0 if clean else 2
    raise RuntimeError('unsupported action')


def unrecorded_cleanup_roles(manifest, scopes, run_id):
    """Roles named by a write-ahead intent or an unrecorded-cleanup receipt.

    Each entry's authority is its role's deterministic name for this run; any
    kind, name, run or labels it states must match that scope exactly.
    """
    entries = []
    for key in ('pending_resources', 'unrecorded_resources'):
        group = manifest.get(key, {})
        if not isinstance(group, dict):
            raise RuntimeError('cleanup manifest failed run scope or schema validation')
        entries.extend(group.items())
    if 'gateway_replacement_unrecorded' in manifest:
        entries.append(('container_gateway', manifest['gateway_replacement_unrecorded']))
    roles = set()
    for role, entry in entries:
        if role not in scopes or not isinstance(entry, dict):
            raise RuntimeError('cleanup manifest failed run scope or schema validation')
        kind, name = scopes[role]
        expected = {'kind': kind, 'name': name, 'run_id': run_id, 'labels': run_labels(run_id)}
        if any(field in entry and entry[field] != value for field, value in expected.items()):
            raise RuntimeError('cleanup manifest failed run scope or schema validation')
        roles.add(role)
    return roles


def cleanup_recorded(manifest, path, logs, role, kind, expected, run_id):
    """Remove one recorded immutable identity; return (status, clean)."""
    if expected is None:
        return 'not-created-no-cleanup-authority', True
    try:
        row = docker_inspect_json(kind, expected['id'])
        if not validate_owned_resource(kind, row, expected, run_id):
            raise RuntimeError('Docker object identity/ownership mismatch')
    except subprocess.CalledProcessError as exc:
        # Docker saying this exact immutable ID does not exist means it is gone.
        if docker_reports_absent(exc, expected['id']):
            return 'already-absent', True
        return 'identity-or-ownership-mismatch-preserved', False
    except (RuntimeError, KeyError, TypeError):
        return 'identity-or-ownership-mismatch-preserved', False
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 'inspection-failed-preserved', False
    if kind == 'container':
        stopped = run(['docker', 'stop', '--time', '10', expected['id']], logs, check=False)
        if role == 'container_gateway':
            retain_gateway_events(manifest, path.parent, expected['id'])
        removed = run(['docker', 'rm', expected['id']], logs, check=False)
        return {'stop': stopped, 'remove': removed}, stopped == 0 and removed == 0
    removed = run([*(['docker', 'network'] if kind == 'network' else ['docker', 'image']),
                   'rm', expected['id']], logs, check=False)
    return {'remove': removed}, removed == 0


PROFILE_CHECKS = frozenset({'state_read_denied', 'state_write_denied', 'uid_is_worker',
                            'no_new_privileges', 'capabilities_dropped',
                            'owner_state_directory_denied', 'workspace_write_allowed',
                            'input_read_allowed'})


def preflight_profile_verified(observed):
    """Every named profile and CLI check is present and exactly True; an empty set never passes."""
    profile = observed.get('native_process_profile_checks')
    cli = observed.get('native_cli_checks')
    resolution = observed.get('native_binary_resolution')
    return (isinstance(profile, dict) and set(profile) == PROFILE_CHECKS
            and all(value is True for value in profile.values())
            and isinstance(cli, dict) and set(cli) == {'claude', 'codex'}
            and all(value is True for value in cli.values())
            and isinstance(resolution, dict) and resolution.get('verified') is True)


def driver(manifest, arguments, logs):
    command = ['docker', 'exec', manifest['containers']['agent'], 'python3',
               '/opt/bench/driver.py', *arguments]
    with logs.open('ab') as stream:
        try:
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=stream,
                                    check=False, text=True, timeout=2850 if '--wait-thread' in arguments else 900)
        except subprocess.TimeoutExpired:
            raise RuntimeError('container driver timed out; inspect retained accepted identity; wait/read only, never relaunch') from None
    if result.returncode:
        raise RuntimeError(f'container driver failed ({result.returncode})')
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise RuntimeError('container driver returned no machine result') from None
    if not isinstance(value, dict):
        raise RuntimeError('container driver result was malformed')
    return value


def capture_parent_observations(manifest, thread_id, run_dir, logs):
    """Snapshot the owned app store, then retain it outside every worker mount."""
    filename = hashlib.sha256(thread_id.encode()).hexdigest() + '.host.sqlite'
    expected = manifest['created_resources']['container_agent']
    inspected = docker_inspect_json('container', expected['id'])
    if not validate_owned_resource('container', inspected, expected, manifest['run_id']):
        raise RuntimeError('host observation container identity changed')
    code = ('import sqlite3; s=sqlite3.connect('
            '"file:/bench/t3/userdata/statev2.sqlite?mode=ro",uri=True); '
            'd=sqlite3.connect("/bench/t3/' + filename + '"); '
            's.backup(d); d.close(); s.close()')
    result = subprocess.run(['docker', 'exec', expected['id'],
                             'python3', '-c', code], stdout=subprocess.DEVNULL,
                            stderr=logs.open('ab'), timeout=30, check=False)
    if result.returncode:
        raise RuntimeError('owned host observation snapshot unavailable')
    destination = run_dir / 'observations'
    destination.mkdir(mode=0o700, exist_ok=True)
    snapshot = destination / filename
    with snapshot.open('xb') as destination_stream, logs.open('ab') as error_stream:
        copied = subprocess.run(['docker','exec',expected['id'],'cat','/bench/t3/'+filename], stdout=destination_stream,stderr=error_stream,timeout=30)
    if copied.returncode:
        raise RuntimeError('protected observation backup export failed')
    snapshot.chmod(0o600)
    raw_name = driver_module.thread_artifact_path('/bench/results', thread_id).name
    raw_export = destination / raw_name
    descriptor = os.open(raw_export, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            exported = subprocess.run(['docker', 'exec', expected['id'], 'python3', '-c',
                'import os,stat,sys; p=sys.argv[1]; f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW); '
                's=os.fstat(f); assert stat.S_ISREG(s.st_mode) and s.st_size<=268435456; '
                'b=os.fdopen(f,"rb").read(268435457); assert len(b)<=268435456; sys.stdout.buffer.write(b)',
                '/bench/t3/observations/' + raw_name], stdout=stream, stderr=logs.open('ab'), timeout=30, check=False)
        if exported.returncode:
            raise RuntimeError('owned private thread transport export unavailable')
    except BaseException:
        raw_export.unlink(missing_ok=True)
        raise
    captured = host_observations.read_snapshot(snapshot, thread_id)
    output = destination / (filename + '.json')
    output.write_text(json.dumps(captured, ensure_ascii=False) + '\n', encoding='utf-8')
    output.chmod(0o600)
    return captured


def configure_gateway(manifest, runtime_policy, logs):
    """Replace the deny-all bootstrap gateway with one using the locked catalog targets."""
    old = manifest['containers']['gateway']
    run_id = manifest['run_id']
    recorded = manifest['created_resources']['container_gateway']
    current = docker_inspect_json('container', recorded['id'])
    if not validate_owned_resource('container', current, recorded, run_id):
        raise RuntimeError('bootstrap gateway identity changed; refusing replacement')
    run(['docker', 'stop', '--time', '5', recorded['id']], logs, check=False)
    retain_gateway_events(manifest, runtime_policy.parent.parent, recorded['id'])
    run(['docker', 'rm', recorded['id']], logs)
    # The bootstrap gateway is gone. Drop its identity at once so cleanup never
    # chases a stale ID, and keep it as history.
    manifest.setdefault('retired_resources', []).append(manifest['created_resources'].pop('container_gateway'))
    # The same write commits the replacement's intent before it is created.
    declare_pending(manifest, 'container_gateway', 'container', old)
    mpath = find_manifest(run_id)
    write_manifest(mpath, manifest)
    argv = ['docker', 'run', '-d', '--name', old, '--network', manifest['networks'][1],
            '--label', 'io.t3.issue28.stage=s1b', '--label', f'io.t3.issue28.run={run_id}',
            '-e', 'BENCH_MODEL_POLICY=/bench/config/runtime-targets.json',
            '--env-file', str(SECRET_ENV),
            '-v', f'{runtime_policy}:/bench/config/runtime-targets.json:ro',
            '-v', f'{runtime_policy.parent.parent / "tls" / "gateway.crt"}:/run/secrets/gateway.crt:ro',
            '-v', f'{runtime_policy.parent.parent / "tls" / "gateway.key"}:/run/secrets/gateway.key:ro',
            '--entrypoint', 'python3', manifest['image'], '/opt/bench/gateway.py']
    try:
        run(argv, logs)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        # A failed `docker run -d` can still leave a created container behind.
        abandon_unrecorded(manifest, lambda: find_manifest(run_id), 'container', 'container_gateway',
                           old, logs, 'replacement gateway creation failed',
                           'gateway_replacement_unrecorded')
    # The shared recorder commits the replacement identity atomically or removes it.
    record_replacement_gateway(manifest, run_id, old, logs)
    run(['docker', 'network', 'connect', '--alias', 'gateway.bench.test',
         manifest['networks'][0], old], logs)
    # The replacement prints its ready event after startup; wait a bounded time for it.
    deadline = time.monotonic() + 20
    while True:
        ready = subprocess.run(['docker', 'logs', old], stdout=subprocess.PIPE,
                               stderr=logs.open('ab'), timeout=10, check=False, text=True)
        if any(json.loads(line).get('event') == 'ready' for line in ready.stdout.splitlines()
               if line.startswith('{')):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('runtime model gateway did not load its locked target manifest')
        time.sleep(0.5)
    health = subprocess.run(['docker', 'exec', manifest['containers']['agent'], 'python3', '-c',
                             "import ssl,urllib.request; c=ssl.create_default_context(cafile='/run/secrets/bench-gateway-ca.pem'); urllib.request.urlopen('https://gateway.bench.test:8443/healthz', context=c, timeout=3)"],
                            stdout=subprocess.DEVNULL, stderr=logs.open('ab'),
                            timeout=10, check=False)
    if health.returncode:
        raise RuntimeError('runtime model gateway did not become ready')


def record_replacement_gateway(manifest, run_id, name, logs, attempts=3):
    """Record the replacement's immutable identity, or remove it by run labels and exact name."""
    record_or_remove(manifest, lambda: find_manifest(run_id), 'container', 'container_gateway',
                     name, logs, attempts, description='replacement gateway',
                     receipt_key='gateway_replacement_unrecorded')


def agent_command(name, private_net, task_input, workspace, raw, state,
                  config_dir, ca_cert, image):
    run_id = re.search(r'\d{8}T\d{6}Z-[0-9a-f]{6}$', name).group(0)
    return ['docker', 'run', '-d', '--name', name, '--network', private_net,
            '--label', 'io.t3.issue28.stage=s1b', '--label', f'io.t3.issue28.run={run_id}',
            '--add-host', 'host.docker.internal:host-gateway',
            '-e', 'ANTHROPIC_API_KEY=bench-synthetic-anthropic',
            '-e', 'OPENAI_API_KEY=bench-synthetic-openai',
            '-e', 'NODE_EXTRA_CA_CERTS=/run/secrets/bench-gateway-ca.pem',
            '-e', 'SSL_CERT_FILE=/run/secrets/bench-gateway-ca.pem',
            '-v', f'{task_input}:/bench/input:ro', '-v', f'{workspace}:/bench/ws:rw',
            '-v', f'{raw}:/bench/results:rw', '-v', f'{state}:/bench/t3:rw',
            '-v', f'{raw / "claude-projects"}:/opt/bench-home/.claude/projects:rw',
            '-v', f'{raw / "codex-sessions"}:/opt/bench-home/.codex/sessions:rw',
            '-v', f'{config_dir}:/bench/config:ro',
            '-v', f'{ca_cert}:/run/secrets/bench-gateway-ca.pem:ro', image]


def gateway_bootstrap_command(name, egress_net, config_dir, cert, key, image):
    run_id = re.search(r'\d{8}T\d{6}Z-[0-9a-f]{6}$', name).group(0)
    return ['docker', 'run', '-d', '--name', name, '--network', egress_net,
            '--label', 'io.t3.issue28.stage=s1b', '--label', f'io.t3.issue28.run={run_id}',
            '-e', 'BENCH_MODEL_POLICY=/bench/config/bootstrap.json',
            '--env-file', str(SECRET_ENV),
            '-v', f'{config_dir}:/bench/config:ro',
            '-v', f'{cert}:/run/secrets/gateway.crt:ro',
            '-v', f'{key}:/run/secrets/gateway.key:ro',
            '--entrypoint', 'python3', image, '/opt/bench/gateway.py']


def helper_command(provider):
    return ('python3 /opt/bench/smoke_helper.py /bench/input/brief.txt '
            f'/bench/ws/canary/{provider}/task-1/helper.json')


def actor_bound_evidence(captured, canary_result, provider, protocol):
    """Host-recorded helper run and file changes, bound to the captured primary dispatch.

    The primary task is the one the host captured the parent dispatching with the frozen
    primary role, never the final report's own classification. The report's finite-role
    IDs must still equal that captured assignment authority.
    """
    binding = host_observations.reported_role_bindings(captured, protocol, canary_result)
    primary = binding['assignments'].get('primary')
    return {'helper_invocation_host_observed': host_observations.helper_invocation_observed(
                captured, helper_command(provider), primary),
            'host_recorded_writes_bound': host_observations.file_changes_bound_to_primary(
                captured, primary),
            'canary_roles_bound_to_host_dispatch': binding['ok'],
            'role_assignments': binding['assignments'],
            'role_assignment_problems': binding['problems']}


def write_canary_role_receipt(run_dir, provider, canary, protocol, canary_result, evidence):
    """Retain the captured assignments, frozen digest and report mapping host-side."""
    destination = run_dir / 'observations'
    destination.mkdir(mode=0o700, exist_ok=True)
    receipt = destination / f'canary-role-audit-{provider}.json'
    body = {'schema_version': 1, 'provider': provider,
            'protocol_sha256': canary.get('role_protocol', {}).get('sha256'),
            'protocol_roles': [role.get('role') for role in protocol.get('roles', [])],
            'assignments': evidence.get('role_assignments'),
            'problems': evidence.get('role_assignment_problems'),
            'verified': evidence.get('canary_roles_bound_to_host_dispatch') is True,
            'report': {'primary_task_id': canary_result.get('primary_task_id') if isinstance(canary_result, dict) else None,
                       'summary_boundary_task_ids': canary_result.get('summary_boundary_task_ids') if isinstance(canary_result, dict) else None,
                       'tracked_followup': canary_result.get('tracked_followup') if isinstance(canary_result, dict) else None}}
    receipt.write_text(json.dumps(body, sort_keys=True) + '\n', encoding='utf-8')
    receipt.chmod(0o600)
    return receipt


def resolve_uncertain_launch(manifest, launch_title, logs):
    """Classify a launch whose response was lost; this never dispatches again."""
    try:
        found = driver(manifest, ['--find-launch', launch_title], logs).get('thread_ids')
    except RuntimeError as exc:
        return {'status': 'unresolved', 'reason': str(exc), 'relaunched': False}
    if not isinstance(found, list):
        return {'status': 'unresolved', 'reason': 'malformed lookup', 'relaunched': False}
    status = {0: 'absent-observed', 1: 'accepted-recovered'}.get(len(found), 'ambiguous')
    return {'status': status, 'thread_ids': found, 'relaunched': False}


def host_loopback_positive(fixture, port):
    """Prove from the host that this exact fixture listener accepts a connection."""
    nonce = secrets.token_hex(8).encode()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
            client.sendall(nonce)
            accepted, _ = fixture.accept()
            with accepted:
                accepted.settimeout(2)
                return accepted.recv(len(nonce)) == nonce
    except OSError:
        return False


def loopback_connections_after(fixture):
    """Count connections the fixture received after the host control; must be zero."""
    count = 0
    while True:
        try:
            accepted, _ = fixture.accept()
        except (socket.timeout, BlockingIOError):
            return count
        accepted.close()
        count += 1


def retain_gateway_events(manifest, run_dir, container_id):
    """Retain the stopped gateway's complete metadata log before removal."""
    destination = Path(run_dir) / ('gateway-' + container_id + '.jsonl')
    try:
        result = subprocess.run(['docker', 'logs', container_id], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('stopped gateway log unavailable')
        destination.write_text(result.stdout + result.stderr, encoding='utf-8'); destination.chmod(0o600)
        manifest.setdefault('gateway_log_receipts', []).append({'container_id': container_id,
            'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(), 'complete_process_lifetime': True})
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        manifest.setdefault('gateway_log_receipts', []).append({'container_id': container_id, 'complete_process_lifetime': False, 'reason': type(exc).__name__})


def gateway_forward_count(container, logs):
    """Count every provider request the gateway began, inference or token estimation."""
    stdout = container_log_text(container, logs)
    if stdout is None:
        return None  # No log is no evidence of zero requests.
    events, damaged = gateway_events(stdout)
    requests = set()
    for event in events:
        # A forwarded count_tokens call still reaches the provider; the
        # no-model smoke must see zero provider requests of any kind.
        if event.get('event') in {'forward-started', 'forwarded', 'forward-failed'}:
            requests.add(event.get('request_id') or 'unattributed-start')
    # A damaged line could have been a request; count it so zero stays provable.
    return len(requests) + damaged


def gateway_events(stdout):
    """The gateway prints only JSON objects; anything else is damage, never skipped."""
    events, damaged = [], 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if isinstance(event, dict):
            events.append(event)
        elif line.strip():
            damaged += 1
    return events, damaged


SMOKE_REQUIRED_PROBES = ('gateway-tls', 'gateway-reachable-positive-control',
                         'no-direct-provider-egress', 'host-gateway-resolves-positive-control',
                         'host-loopback-excluded')


def smoke_probe_results(stdout):
    """Probe outcomes printed by one smoke run; each negative needs its paired positive."""
    probes = {}
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get('probe'), str):
            if row['probe'] in probes:
                probes[row['probe']] = False  # A repeated probe name is ambiguous evidence.
            else:
                probes[row['probe']] = row.get('passed') is True
    return {'probes': probes,
            'paired_controls_passed': all(probes.get(name) is True for name in SMOKE_REQUIRED_PROBES)}


NATIVE_LAUNCH_LOG = '/bench/t3/native-launches.jsonl'
NATIVE_PROGRAMS = {'claudeAgent': 'claude', 'codex': 'codex'}
NATIVE_LAUNCH_KEYS = {'program', 'pid', 'parent_uid', 'worker_uid', 'nonce', 'argv_sha256'}
NATIVE_LOG_READ = (
    'import os,stat,sys\n'
    'try:\n'
    '    f=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW)\n'
    'except FileNotFoundError:\n'
    '    sys.exit(3)\n'
    's=os.fstat(f)\n'
    'assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)&0o077==0\n'
    'b=os.fdopen(f,"rb").read(16777217)\n'
    'assert len(b)<=16777216\n'
    'sys.stdout.buffer.write(b)\n')


def parse_native_launches(data):
    """Strictly parse the shim's coordinator-only launch log; any malformed row rejects it."""
    rows = []
    for line in data.decode('utf-8').splitlines():
        row = json.loads(line, object_pairs_hook=driver_module._strict_object,
                         parse_constant=driver_module._reject_constant)
        if (not isinstance(row, dict) or set(row) != NATIVE_LAUNCH_KEYS
                or row['program'] not in NATIVE_PROGRAMS.values()
                or type(row['pid']) is not int or row['parent_uid'] != 0 or type(row['parent_uid']) is not int
                or row['worker_uid'] != 1001 or type(row['worker_uid']) is not int
                or not isinstance(row['nonce'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['nonce'])
                or not isinstance(row['argv_sha256'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', row['argv_sha256'])):
            raise ValueError('native launch log row is malformed')
        rows.append(row)
    return rows


def read_native_launches(container_id, logs, allow_missing=False):
    """Read the shim log as the container coordinator; workers cannot read or write it."""
    with logs.open('ab') as errors:
        result = subprocess.run(['docker', 'exec', container_id, 'python3', '-c', NATIVE_LOG_READ,
                                 NATIVE_LAUNCH_LOG], stdout=subprocess.PIPE, stderr=errors,
                                timeout=20, check=False)
    if result.returncode == 3 and allow_missing:
        return []
    if result.returncode:
        raise RuntimeError('coordinator-only native launch log is missing or unreadable')
    return parse_native_launches(result.stdout)


def native_launch_evidence(before, after, provider):
    """Require new shim launches (worker UID) for the provider under test during this canary."""
    program = NATIVE_PROGRAMS[provider]
    appended = after[len(before):]
    launches = [row for row in appended if row['program'] == program]
    append_only = after[:len(before)] == before
    verified = append_only and bool(launches)
    return {'verified': verified, 'program': program, 'shim_launches': len(launches),
            'other_program_launches': len(appended) - len(launches), 'append_only': append_only,
            'reason': None if verified else
            'no worker-UID shim launch of the provider CLI was recorded during this canary'}


def canary_native_launch_audit(container_id, before, provider, logs):
    try:
        return native_launch_evidence(before, read_native_launches(container_id, logs), provider)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {'verified': False, 'program': NATIVE_PROGRAMS[provider], 'shim_launches': 0,
                'reason': 'native launch log unavailable: ' + type(exc).__name__}


def tracked_followup_accepted(audit):
    """Only a supported, host-verified continuation passes. A refusal never does (fail-closed)."""
    return (isinstance(audit, dict) and audit.get('recorded') is True
            and audit.get('supported') is True and audit.get('verified') is True)


ABSENT_MARKERS = ('no such container', 'no such object', 'no such image', 'no such network')


def docker_reports_absent(error, object_id):
    """True only when Docker's inspect error says this exact object does not exist."""
    text = str(error.stderr or '').lower()
    object_id = str(object_id).lower()
    return bool(object_id) and object_id in text and (
        any(f'{marker}: {object_id}' in text for marker in ABSENT_MARKERS)
        or f'network {object_id} not found' in text)


def docker_exists(command):
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            check=False, timeout=20, text=True)
    if result.returncode == 0:
        return True
    if ('no such object' in result.stderr.lower() or 'no such network' in result.stderr.lower()
            or 'no such image' in result.stderr.lower()):
        return False
    raise RuntimeError('Docker resource inspection failed')


def container_log_text(container, logs):
    """The container's complete log, or None when Docker could not return it."""
    result = subprocess.run(['docker', 'logs', container], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=20, check=False)
    with logs.open('a', encoding='utf-8') as stream:
        stream.write(result.stdout or '')
    if result.returncode != 0 or not isinstance(result.stdout, str):
        return None
    return result.stdout


def github_event_count(container, logs):
    """Synthetic GitHub reads so far, or None when the log is unavailable."""
    stdout = container_log_text(container, logs)
    if stdout is None:
        return None
    return sum(1 for line in stdout.splitlines() if '"event":"read"' in line)


def count_delta(after, before):
    """after - before, or None unless both counts were observed."""
    if type(after) is not int or type(before) is not int:
        return None
    return after - before


def gateway_rejection_count(container, logs):
    """Rejections plus damaged lines so far, or None when the log is unavailable."""
    stdout = container_log_text(container, logs)
    if stdout is None:
        return None
    events, damaged = gateway_events(stdout)
    # New damage between two counts must break gateway_policy_clean, like a rejection.
    count = damaged
    for event in events:
        if event.get('event') == 'rejected' or (event.get('event') == 'forwarded'
                                                 and not 200 <= event.get('status', 0) < 300):
            count += 1
    return count


def gateway_model_observations(container, expected, provider, logs, canonical=None):
    try:
        stdout = container_log_text(container, logs)
    except (OSError, subprocess.TimeoutExpired):
        stdout = None
    if stdout is None:
        # Recorded as an unverified audit after the slot is used, never raised past it.
        return {'verified': False, 'requests': [], 'token_estimates': [], 'damaged_log_lines': None,
                'inference_requests_started': None, 'inference_requests_failed': None,
                'all_inference_responses_completed': False, 'usage_complete': False,
                'usage_reason': 'usage-absent', 'reason': 'gateway log unavailable',
                'transcript_visibility': 'separate audit; empty transcripts do not establish native child visibility'}
    rows, estimates, started, failed = [], [], set(), set()
    events, damaged = gateway_events(stdout)
    for event in events:
        if event.get('request_kind') == 'inference' and event.get('provider') == ('openai' if provider == 'codex' else 'anthropic'):
            if event.get('event') == 'forward-started': started.add(event.get('request_id'))
            if event.get('event') == 'forward-failed': failed.add(event.get('request_id'))
        if event.get('event') == 'forwarded' and event.get('provider') == (
                'openai' if provider == 'codex' else 'anthropic'):
            (estimates if event.get('request_kind') == 'token-estimation' else rows).append(event)
    all_finished = bool(started) and not failed and started == {row.get('request_id') for row in rows}
    verified = bool(canonical) and not damaged and all_finished and bool(rows) and all(row.get('model') == expected
                                 and row.get('response_model_ids') == [canonical]
                                 and row.get('response_complete') is True and row.get('status') == 200 for row in rows)
    usage_reasons = {usage_status(row.get('usage'), provider) for row in rows}
    usage_reason = ('usage-absent' if not rows or usage_reasons == {'usage-absent'}
                    else 'usage-partial' if usage_reasons - {None} else None)
    return {'verified': verified, 'requests': rows, 'token_estimates': estimates,
            'damaged_log_lines': damaged,
            'inference_requests_started': len(started), 'inference_requests_failed': len(failed),
            'all_inference_responses_completed': all_finished,
            'usage_complete': verified and usage_reason is None,
            'usage_reason': usage_reason,
            'reason': ('gateway log has damaged lines' if damaged
                       else 'missing, mismatched or incomplete provider response identity' if not verified
                       else usage_reason),
            'transcript_visibility': 'separate audit; empty transcripts do not establish native child visibility'}


# Both pinned providers report these counters on every complete inference response:
# Anthropic Messages usage and OpenAI Responses usage.
REQUIRED_USAGE = {'claudeAgent': ('input_tokens', 'output_tokens'),
                  'codex': ('input_tokens', 'output_tokens')}


def usage_status(usage, provider):
    """Return None when the provider's required counters are present, else a reason."""
    if not isinstance(usage, dict) or not usage:
        return 'usage-absent'
    required = REQUIRED_USAGE.get(provider)
    if not required or not all(isinstance(usage.get(name), int) and not isinstance(usage.get(name), bool)
                               for name in required):
        return 'usage-partial'
    return None


def helper_output_valid(workspace, provider, expected_file, _allowed_providers=()):
    """The helper output is a regular file physically inside its assigned directory."""
    expected = expected_file.read_text(encoding='ascii').strip()
    folder = workspace / 'canary' / provider
    assigned = folder / 'task-1'
    helper = assigned / 'helper.json'
    try:
        # No link may stand anywhere between the workspace and the output file.
        for ancestor in (workspace / 'canary', folder, assigned):
            if not stat.S_ISDIR(ancestor.lstat().st_mode):
                return False
        if (assigned.resolve(strict=True) != workspace.resolve(strict=True) / 'canary' / provider / 'task-1'
                or any(path.is_symlink() for path in folder.rglob('*'))):
            return False
        fd = os.open(helper, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return False
            output = json.loads(stream.read().decode('utf-8'))
        contained = helper.resolve(strict=True).parent == assigned.resolve(strict=True)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    canary_files = (path for path in folder.rglob('*') if path.is_file())
    return (contained and isinstance(output, dict) and output.get('input_sha256') == expected
            and all(path.is_relative_to(assigned) for path in canary_files))


WORKSPACE_WRITABLE_TYPES = {'file', 'directory'}


def workspace_write_scope_valid(root, changes, provider):
    """Only the assigned directory may change, and only with files and directories.

    Outside canary/<provider>/task-1/ the one permitted change is creating the
    assigned ancestors canary, canary/<provider> and canary/<provider>/task-1 as
    directories. Any other entry created, removed, modified, type-changed,
    chmodded or chowned there fails, the workspace root included, as do links,
    special files or unlistable directories in the assigned directory and any
    unreadable entry or unlistable directory elsewhere. Inside the assigned
    directory, entries may be added or deleted; of the entries that already
    existed, only the helper output may change, and only as a regular file.
    """
    assigned = f'canary/{provider}/task-1'
    ancestors = {'canary', f'canary/{provider}', assigned}
    inside = assigned + '/'
    helper_output = inside + 'helper.json'

    def permitted(change):
        if not isinstance(change, dict) or not isinstance(change.get('path'), str):
            return False
        kind, before, after = change.get('kind'), change.get('before'), change.get('after')
        writable = (isinstance(after, dict) and after.get('type') in WORKSPACE_WRITABLE_TYPES
                    and not after.get('unlisted'))
        if change['path'].startswith(inside):
            if kind == 'deleted':
                return True
            if kind == 'added':
                return writable
            return (change['path'] == helper_output and kind == 'modified'
                    and isinstance(before, dict) and before.get('type') == 'file'
                    and isinstance(after, dict) and after.get('type') == 'file')
        return (change['path'] in ancestors and kind == 'added' and writable
                and after.get('type') == 'directory')
    current = workspace_inventory(root)
    return (isinstance(changes, list) and all(permitted(change) for change in changes)
            and not any(name.startswith(inside) and item['type'] not in WORKSPACE_WRITABLE_TYPES
                        for name, item in current.items())
            and not any(item.get('unlisted') or (item.get('unreadable') and not name.startswith(inside))
                        for name, item in current.items()))


SPECIAL_TYPES = ((stat.S_ISFIFO, 'fifo'), (stat.S_ISSOCK, 'socket'),
                 (stat.S_ISCHR, 'char-device'), (stat.S_ISBLK, 'block-device'))


def entry_metadata(info):
    """Mode bits and ownership: who may later mutate or list this entry.

    Files also carry their link count, so a hard link made to an inode outside
    the assigned path changes that entry. A directory's link count follows its
    subdirectories and is left out.
    """
    metadata = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
    if stat.S_ISREG(info.st_mode):
        metadata['links'] = info.st_nlink
    return metadata


def workspace_entry(path):
    """Describe one entry without following links or opening special files."""
    info = os.lstat(path)
    metadata = entry_metadata(info)
    if stat.S_ISDIR(info.st_mode):
        return {'type': 'directory', **metadata}
    if stat.S_ISLNK(info.st_mode):
        return {'type': 'symlink', 'target': os.readlink(path), **metadata}
    if not stat.S_ISREG(info.st_mode):
        return {'type': next((name for test, name in SPECIAL_TYPES if test(info.st_mode)), 'other'),
                **metadata}
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise
    except OSError:
        return {'type': 'file', 'sha256': None, 'unreadable': True, **metadata}
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(opened.st_mode):
            return {'type': 'other', 'reason': 'changed while inventoried', **metadata}
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return {'type': 'file', 'sha256': digest.hexdigest(), **metadata}


WORKSPACE_ROOT_KEY = '.'


def workspace_inventory(root):
    """Record the type and metadata of every entry below root, never following links.

    Files carry a content hash, links their target and other entries their kind,
    and every entry its mode bits and owner, so creating, removing, retyping,
    chmodding or chowning any entry (an empty directory or a FIFO included)
    shows as a change. The root itself is recorded under '.'. A directory that
    cannot be listed is marked unlisted so the scope check fails closed.
    """
    root = Path(root)
    result = {WORKSPACE_ROOT_KEY: workspace_entry(root)}
    pending = [root]
    while pending:
        folder = pending.pop()
        key = folder.relative_to(root).as_posix()
        try:
            with os.scandir(folder) as entries:
                names = sorted(entry.name for entry in entries)
        except FileNotFoundError:
            if folder == root:
                raise
            result.pop(key, None)  # Removed while inventoried: it is absent now.
            continue
        except OSError:
            if folder == root:
                raise
            result[key] = dict(result[key], unlisted=True)
            continue
        for name in names:
            path = folder / name
            try:
                item = workspace_entry(path)
            except FileNotFoundError:
                continue  # Removed while inventoried: it is absent now.
            result[path.relative_to(root).as_posix()] = item
            if item['type'] == 'directory':
                pending.append(path)
    return result


def workspace_changes_since(root, before):
    """Every entry added, deleted, modified or type-changed since the baseline."""
    after = workspace_inventory(root)
    changes = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        kind = ('added' if old is None else 'deleted' if new is None
                else 'type-changed' if old.get('type') != new.get('type') else 'modified')
        changes.append({'path': name, 'kind': kind, 'before': old, 'after': new})
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('up', help='build and start one fresh isolated container set')
    for action in ('smoke', 'preflight', 'catalog', 'canary', 'down'):
        command = sub.add_parser(action)
        command.add_argument('run_id')
        if action == 'canary':
            command.add_argument('--provider', choices=('codex', 'claudeAgent'), required=True)
    args = parser.parse_args()
    if args.command == 'up':
        setup(args)
        return 0
    return manage(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as exc:
        print('bench container command blocked: ' + str(exc), file=sys.stderr)
        sys.exit(2)
