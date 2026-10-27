#!/usr/bin/env python3
"""Bounded read-only inventories, evidence calculations and private local reports."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
from analysis import VERSION, PROFILES, analyze, evidence_rejections, expiry, expired_exceptions, current_findings
from render import render

GENERATOR = '0.1.2'
PACKAGE = Path(__file__).resolve().parents[1]
MAX_INPUT = 8 * 1024 * 1024


class ScopeUnavailable(ValueError):
    """Valid request whose requested evidence could not be collected."""


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def unique(pairs):
    value = {}
    for k, v in pairs:
        if k in value:
            raise ValueError('duplicate JSON key')
        value[k] = v
    return value


def read(path, limit=MAX_INPUT):
    """Refuse symlink leaf files and bound untrusted input size."""
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('regular file required')
        raw = f.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('input exceeds byte limit')
        return raw


def load(path, limit=MAX_INPUT):
    return json.loads(read(path, limit), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON number')))


def git(repo, *args):
    # No repository-provided fsmonitor, pager or optional lock writes. No hooks or
    # repository commands are executed. Keep command arguments literal.
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0', 'GIT_PAGER': 'cat'}
    p = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(repo), *args],
                       capture_output=True, timeout=15, env=env)
    if p.returncode:
        raise ScopeUnavailable('read-only Git inventory unavailable: ' + args[0])
    if len(p.stdout) > MAX_INPUT:
        raise ValueError('Git inventory exceeds byte limit')
    return p.stdout


def snapshot_limits(max_files=4000, seconds=30, max_bytes=32 * 1024 * 1024, max_file_bytes=MAX_INPUT):
    limits = {'files': max_files, 'seconds': seconds, 'bytes': max_bytes, 'file_bytes': max_file_bytes}
    ceilings = {'files': 100000, 'seconds': 120, 'bytes': 512 * 1024 * 1024, 'file_bytes': 64 * 1024 * 1024}
    if any(type(v) is not int or not 1 <= v <= ceilings[k] for k, v in limits.items()):
        raise ValueError('snapshot limits require files 1..100000, seconds 1..120, bytes 1..536870912, file bytes 1..67108864')
    return limits


def snapshot(repo, max_files=4000, seconds=30, max_bytes=32 * 1024 * 1024,
             max_file_bytes=MAX_INPUT, selected_paths=None, inventory_binding=True):
    limits = snapshot_limits(max_files, seconds, max_bytes, max_file_bytes)
    repo = Path(repo).resolve()
    root = Path(os.fsdecode(git(repo, 'rev-parse', '--show-toplevel')).strip()).resolve()
    if repo != root:
        raise ValueError('audit path must be a repository root')
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    names = sorted(set(os.fsdecode(p) for p in git(repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0') if p))
    started, total = time.monotonic(), 0
    files, limitations = {}, []
    selected = names if selected_paths is None else sorted(selected_paths)
    if selected_paths is not None:
        # Reinspect exactly the saved partial selection; never widen old coverage
        # because a later machine can hash more files before its deadline.
        limitations.append('Saved partial source selection; full inventory remains uninspected.')
    for position, name in enumerate(selected):
        if position >= max_files or time.monotonic() - started > seconds or total >= max_bytes:
            limitations.append('Source inventory file/time/byte budget exhausted.')
            break
        path = repo / name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('unsafe source inventory path')
        try:
            if path.is_symlink():
                files[name] = {'symlink_sha256': digest(os.fsencode(os.readlink(path)))}
            elif not path.exists():
                files[name] = {'deleted': True}
            elif path.is_file() and path.resolve().is_relative_to(repo):
                allowance = min(max_file_bytes, max_bytes - total)
                if path.stat().st_size > allowance:
                    limitations.append('Source bytes unavailable: ' + name)
                    continue
                raw = read(path, allowance)
                total += len(raw)
                files[name] = {'sha256': digest(raw), 'mode': stat.S_IMODE(path.stat().st_mode)}
            else:
                limitations.append('Uninspected source directory/submodule: ' + name)
        except (OSError, ValueError):
            limitations.append('Source bytes unavailable: ' + name)
    binding = {'head_sha': head, 'files': files}
    if inventory_binding:
        binding['inventory_sha256'] = digest(canonical(names))
    return {**binding, 'sha256': digest(canonical(binding)), 'limitations': limitations,
            'inventory_count': len(names), 'inspected_count': len(files),
            'policy': 'tracked and nonignored untracked bytes, modes and symlink identities; no symlink traversal; ignored files excluded',
            'limits': limits}


def snapshot_options(saved):
    limits = saved.get('limits', {})
    return snapshot_limits(limits.get('files', 4000), limits.get('seconds', 30),
                           limits.get('bytes', 32 * 1024 * 1024), limits.get('file_bytes', MAX_INPUT))


def snapshot_saved(repo, saved):
    limits = snapshot_options(saved)
    return snapshot(repo, max_files=limits['files'], seconds=limits['seconds'],
                    max_bytes=limits['bytes'], max_file_bytes=limits['file_bytes'],
                    selected_paths=list(saved['files']) if saved.get('limitations') else None,
                    inventory_binding='inventory_sha256' in saved)


def source_identity(locator, scope):
    # Local checkout identity, not a display label or an untrusted input claim.
    # Different clones stay separate; a moved checkout needs a new audit lineage.
    identity = {'kind': 'local-repository', 'root': str(Path(locator).resolve())} if locator else {
        'kind': 'organization', 'owner': scope['owner'], 'expected_source': scope.get('expected_source'),
        'inventory': sorted(r['name'] for r in scope['inventory'])}
    return digest(canonical(identity))


def history_errors(data):
    history = data.get('history', {})
    errors = list(history.get('errors', []))
    requested = history.get('requested', [])
    if 'runs' in requested and history.get('runs_complete') is not True:
        errors.append('Requested run/job/attempt history incomplete.')
    if 'incidents' in requested and history.get('bugs_accessible') is not True:
        errors.append('Requested incident/fix history inaccessible.')
    return errors


def private_dir(path):
    path = Path(path).absolute()
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError('symlink state directory refused')
        if not part.exists():
            part.mkdir(mode=0o700)
    if not path.is_dir() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('state directory must be owned and private (0700)')
    return path


def state_root(raw, repo=None, create=True):
    path = Path(raw).expanduser().absolute()
    if repo and path.resolve().is_relative_to(Path(repo).resolve()):
        raise ValueError('state root must be outside the audited repository')
    if create:
        return private_dir(path)
    for p in [path, *path.parents]:
        if p.is_symlink(): raise ValueError('symlink state directory refused')
    if not path.is_dir(): raise ValueError('state root missing')
    if stat.S_IMODE(path.stat().st_mode) & 0o077: raise ValueError('state root is not private')
    return path


def write(path, raw):
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if path.is_symlink(): raise ValueError('symlink destination refused')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


@contextmanager
def locked(root):
    import fcntl
    fd = os.open(root / '.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def run_dir(root, run_id):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', run_id):
        raise ValueError('invalid run ID')
    path = root / 'runs' / run_id
    if any(p.is_symlink() for p in (root / 'runs', path)):
        raise ValueError('symlink run directory refused')
    return path


def pending_path(root, run_id):
    run_dir(root, run_id)  # same strict identifier validation
    return root / ('pending-' + run_id + '.json')


def checkpoint(root, record):
    with locked(root):
        write(pending_path(root, record['run_id']), canonical(record))


def verify(root, run_id):
    folder = run_dir(root, run_id)
    manifest = load(folder / 'manifest.json')
    if manifest.get('schema_version') != 1 or manifest.get('run_id') != run_id:
        raise ValueError('manifest identity/version mismatch')
    for name in ('audit.json', 'report.html', 'input.json'):
        if digest(read(folder / name, 32 * MAX_INPUT)) != manifest.get('hashes', {}).get(name):
            raise ValueError(name + ' digest mismatch; revalidation required')
    audit = load(folder / 'audit.json', 32 * MAX_INPUT)
    if (audit['run_id'] != run_id or audit['input_sha256'] != manifest['hashes']['input.json'] or
            audit['generator_version'] != manifest['generator_version']):
        raise ValueError('audit/manifest identity mismatch')
    return folder, manifest, audit


def authorize_input(data, run_checks):
    if not isinstance(data, dict) or data.get('schema_version', 1) != 1:
        raise ValueError('unsupported input schema')
    if data.get('execution') and not run_checks:
        raise ValueError('execution receipts require explicit --run-checks')
    if data.get('strategy'):
        sys.path.insert(0, str(PACKAGE if (PACKAGE / 'shared').is_dir() else PACKAGE.parent.parent))
        from shared import planning_review
        strategy = data['strategy']
        if not strategy.get('snapshot_sha256') or not strategy.get('receipt'):
            raise ValueError('written strategy requires a content-bound shared planning receipt before dependent work')
        planning_review.validate_receipt(strategy['receipt'], expected_snapshot=strategy['snapshot_sha256'])
    for receipt in data.get('execution', []):
        for k in ('argv', 'cwd', 'timeout_seconds', 'prerequisites', 'authorization', 'exit_code', 'duration_seconds', 'cleanup'):
            if k not in receipt: raise ValueError('execution receipt missing ' + k)
        if not receipt['authorization'] or not 0 < receipt['timeout_seconds'] <= 600:
            raise ValueError('bounded authorized execution required')
        if receipt.get('production') or receipt.get('uncontrolled_network'):
            raise ValueError('unsafe execution receipt')
    if data.get('findings') or any(g.get('assessment_state') == 'supported' for g in data.get('groups', [])):
        # Shared admission, not a new model dispatcher. The coordinator supplies
        # the actual producing selection and independent retained binding.
        sys.path.insert(0, str(PACKAGE if (PACKAGE / 'shared').is_dir() else PACKAGE.parent.parent))
        from shared import execution_agreement, model_selection
        context = data.get('selection_context', {})
        if not context.get('selection_sha256'):
            raise ValueError('authored judgments require shared model-selection admission')
        model_selection.gate(context['record'], invocation_id=context['invocation_id'],
                             scope_id=context['scope_id'], action='synthesis',
                             expected=context['selection_sha256'])
        execution_agreement.admit(context['record'], operation='tests-omg/audit')


def sanitize(value):
    """Defense in depth for common accidental credentials, not a DLP guarantee.

    The coordinator must remove personal fixture data before ingestion. The full
    record stays private; local generation never grants publication authority.
    """
    if isinstance(value, dict):
        return {k: ('[redacted]' if re.search(r'(?i)^(?:password|token|api_key|authorization_header|secret)$', k)
                    else sanitize(v)) for k, v in value.items()}
    if isinstance(value, list): return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{16,})', '[redacted]', value)
        value = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [redacted]', value)
        value = re.sub(r'(https?://)[^/\s@]+@', r'\1[redacted]@', value)
        value = re.sub(r'(?i)([?&](?:token|key|secret|signature|password|access_token)=)[^&#\s]+', r'\1[redacted]', value)
    return value


def inventory(org, data, repo_budget, seconds):
    source = data.get('org', {})
    if source.get('owner') != org:
        raise ValueError('--org requires matching paginated owner evidence')
    rows, errors, pages, next_page = {}, [], 0, 1
    started = time.monotonic()
    for page in source.get('pages', []):
        if pages >= 100 or time.monotonic() - started >= seconds:
            errors.append('inventory page/time budget exhausted'); break
        if page.get('page') != next_page:
            errors.append('pagination discontinuity'); break
        pages += 1
        if page.get('error'):
            errors.append(str(page['error'])); break
        for repo in page.get('repos', []):
            name = repo['name']
            if name in rows:
                errors.append('duplicate repository across pages'); continue
            rows[name] = {**repo, 'classification': repo.get('classification') or 'unknown',
                          'owner': repo.get('owner') or org,
                          'next_action': 'Classify consequence and compose profiles.' if not repo.get('classification') else 'Inspect test value.'}
        next_page = page.get('next_page')
        if next_page is None: break
    if next_page is not None: errors.append('repository listing incomplete')
    expected = source.get('expected_repos')
    authoritative = source.get('expected_source') and isinstance(expected, list)
    missing = sorted(set(expected or []) - set(rows)) if authoritative else []
    selected = sorted(rows, key=lambda name: (rows[name].get('priority', 999), name))[:repo_budget]
    if len(rows) > repo_budget: errors.append('repository audit budget exhausted')
    results = []
    for name in selected:
        # Cheap inventory covers everyone before this pass. Existing normalized
        # per-repo records are inputs, never remote code or automatic clones.
        repo = rows[name]
        pack = data.get('repositories', {}).get(name)
        if pack and time.monotonic() - started < seconds:
            authorize_input(pack['evidence'], False)
            result = analyze(pack['evidence'], pack['snapshot'], now())
            results.append({'repository': name, 'analysis': result})
            if not result['evidence_current'] or not pack['evidence'].get('inspected_groups'):
                errors.append('test value assessment incomplete: ' + name)
            if result['sample']['omitted']:
                errors.append('selected test value sample incomplete: ' + name)
            history = pack['evidence'].get('history', {})
            if history.get('runs_complete') is not True or history.get('errors'):
                errors.append('run/job/attempt history incomplete: ' + name)
            if history.get('bugs_accessible') is not True:
                errors.append('incident/fix history inaccessible: ' + name)
            result['asserted_binding_consistent'] = result['binding_consistent']
            result['evidence_current'] = False
            result['source_verification'] = 'coordinator-asserted; not independently verified'
            result['limitations'].append('Organization source snapshots and inspection claims are coordinator-asserted; this helper has not independently inspected those repositories or verified their Git commits.')
        else:
            results.append({'repository': name, 'test_value_assessment': 'incomplete',
                            'reason': 'Inventory triage only; no snapshot-bound test-value evidence.',
                            'owner': repo['owner'], 'next_action': 'Inspect test groups within a separately retained budget.'})
            errors.append('test value assessment incomplete: ' + name)
    return {'kind': 'organization', 'owner': org, 'inventory': list(rows.values()),
            'pages_collected': pages, 'expected_source': source.get('expected_source'),
            'denominator_state': 'gap' if missing else ('meets' if authoritative and not errors else 'unknown'),
            'missing_repositories': missing, 'fleet_wide': bool(authoritative and not errors and not missing),
            'visibility': 'owner-reconciled' if authoritative else 'credential-visible only',
            'source_verification': 'coordinator-asserted; not independently verified',
            'fleet_wide_basis': 'Inventory and submitted assessment completeness only; source and judgment truth require coordinator evidence.',
            'errors': list(dict.fromkeys(errors)), 'results': results,
            'limits': {'repos': repo_budget, 'seconds': seconds, 'pages': 100},
            'counters': {'inventoried': len(rows), 'assessed': len([r for r in results if 'analysis' in r])},
            'completion': 'partial' if errors or missing else 'complete'}


def save(root, audit, locator):
    with locked(root):
        runs = private_dir(root / 'runs')
        folder = run_dir(root, audit['run_id'])
        if folder.exists(): raise ValueError('run already exists')
        folder.mkdir(mode=0o700)
        index_path = root / 'index.json'
        index = load(index_path) if index_path.exists() else {'schema_version': 1, 'runs': []}
        audit['source_identity'] = source_identity(locator, audit['scope'])
        # A legacy basename cannot prove which source produced a record. Leave
        # those entries immutable and unjoined rather than guessing a migration.
        predecessors = [r for r in index['runs'] if r.get('source_identity') == audit['source_identity']]
        predecessor = predecessors[-1]['run_id'] if predecessors else None
        audit['predecessor'] = predecessor
        audit['comparison'] = {'state': 'unknown', 'reason': 'No compatible prior observation.'}
        if predecessor:
            try:
                _, _, old = verify(root, predecessor)
                old_identity = old['input'].get('identity', {})
                new_identity = audit['input'].get('identity', {})
                expired_prior = bool(expired_exceptions(old['input'])) or any(r.get('available') is False or (r.get('expires_at') and
                                    expiry(r['expires_at']) <= datetime.now(timezone.utc)) for r in old['input'].get('references', []))
                compatible = (old['benchmark_version'] == audit['benchmark_version'] and
                              not expired_prior and
                              all(new_identity.get(k) and old_identity.get(k) == new_identity.get(k)
                                  for k in ('config_version', 'environment', 'tool_versions')) and
                              old['profiles'] == audit['profiles'] and old['analysis']['evidence_current'] and audit['analysis']['evidence_current'])
                if compatible:
                    audit['comparison'] = {'state': 'available', 'predecessor': predecessor,
                                           'prior_recommendations': old['analysis']['recommendations'],
                                           'prior_timing': old['analysis']['timing'],
                                           'verification': 'Compare retained/lost cases and runner-minutes; adoption and causal improvement require coordinator inspection.'}
            except (OSError, ValueError):
                audit['comparison']['reason'] = 'Predecessor supporting evidence unavailable.'
        input_raw = canonical(audit['input'])
        audit['input_sha256'] = digest(input_raw)
        content = {'input.json': input_raw, 'audit.json': canonical(audit), 'report.html': render(audit).encode()}
        hashes = {name: digest(raw) for name, raw in content.items()}
        manifest = {'schema_version': 1, 'generator_version': GENERATOR, 'benchmark_version': VERSION,
                    'run_id': audit['run_id'], 'hashes': hashes, 'source_locator': str(locator) if locator else None,
                    'snapshot_sha256': audit['snapshot']['sha256'], 'created_at': audit['generated_at'],
                    'attachment_retention_days': 30, 'compact_records': 'retain until owner deletes',
                    'authenticity': 'hashes detect drift, not manifest rewrite by a privileged actor'}
        for name, raw in content.items(): write(folder / name, raw)
        write(folder / 'manifest.json', canonical(manifest))
        for r in predecessors:
            if r['revision'] != audit['snapshot']['head_sha'] or r.get('snapshot_sha256') != audit['snapshot']['sha256']:
                r['superseded_by'] = audit['run_id']
        index['runs'].append({'run_id': audit['run_id'], 'repository': audit['repository'],
                              'source_identity': audit['source_identity'], 'snapshot_sha256': audit['snapshot']['sha256'],
                              'revision': audit['snapshot']['head_sha'], 'benchmark_version': VERSION,
                              'config_version': audit['input'].get('identity', {}).get('config_version'),
                              'history_window': audit['input'].get('history', {}), 'predecessor': predecessor,
                              'generated_at': audit['generated_at'], 'superseded_by': None})
        write(index_path, canonical(index))
        resumed = audit['scope'].get('resumed_from')
        if resumed and pending_path(root, resumed).exists():
            write(root / ('resumed-' + resumed + '.json'), canonical({'successor': audit['run_id']}))
            pending_path(root, resumed).unlink()
    return folder


def doctor():
    required = ['plugin.json', 'entry.md', 'scripts/audit.py', 'scripts/analysis.py', 'scripts/render.py',
                'playbooks/audit.md', 'references/evidence.md', 'templates/evidence.example.json']
    # A source checkout keeps the canonical body at skills/<name>/SKILL.md; packages map it to entry.md.
    canonical_entry = PACKAGE.parents[1] / 'skills' / PACKAGE.name / 'SKILL.md'
    missing = [name for name in required if not (PACKAGE / name).is_file()
               and not (name == 'entry.md' and canonical_entry.is_file())]
    if not shutil.which('git'):
        missing.append('Git executable unavailable')
    if importlib.util.find_spec('fcntl') is None:
        missing.append('POSIX fcntl file locking unavailable; state operations require a POSIX host')
    installed = PACKAGE / 'install-manifest.json'
    if installed.exists():
        for item in load(installed)['files']:
            relative = Path(item['path'])
            if relative.is_absolute() or not relative.parts or '..' in relative.parts:
                raise ValueError('unsafe installed manifest path')
            candidate = PACKAGE
            for part in relative.parts:
                candidate /= part
                if candidate.is_symlink():
                    raise ValueError('symlink installed manifest path refused')
            try:
                if digest(read(candidate)) != item['sha256']: missing.append(item['path'] + ': digest mismatch')
            except (OSError, ValueError): missing.append(item['path'] + ': unavailable')
    return {'completion': 'blocked' if missing else 'complete', 'python': sys.version.split()[0],
            'generator_version': GENERATOR, 'installed_receipt': installed.exists(),
            'errors': missing, 'model_launches': 0, 'target_writes': 0,
            'limits': 'Local artifact integrity only; live provider and host interaction unverified.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', default=str(Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'agents/tests-omg'))
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    for op in ('status', 'report'):
        p = sub.add_parser(op); p.add_argument('run_id')
    p = sub.add_parser('audit')
    p.add_argument('path', nargs='?', default='.')
    p.add_argument('--input', help='normalized existing evidence; never code to execute')
    p.add_argument('--org')
    p.add_argument('--run-checks', action='store_true', help='admit coordinator-collected bounded execution receipts; this helper executes no repo code')
    p.add_argument('--repo-budget', type=int, default=10)
    p.add_argument('--seconds', type=int, default=120)
    p.add_argument('--profiles', nargs='*', choices=list(PROFILES), default=[])
    p.add_argument('--resume', help='retain original scope and counters; source drift refuses continuation')
    p.add_argument('--snapshot', action='store_true', help='print bounded source binding only, without storing an audit')
    p.add_argument('--snapshot-summary', action='store_true', help='with --snapshot, omit file rows from output; the digest still binds their bytes')
    p.add_argument('--snapshot-files', type=int, default=4000)
    p.add_argument('--snapshot-seconds', type=int, default=None)
    p.add_argument('--snapshot-bytes', type=int, default=32 * 1024 * 1024)
    p.add_argument('--snapshot-file-bytes', type=int, default=MAX_INPUT)
    args = parser.parse_args(argv)
    pending = None
    try:
        if sys.version_info < (3, 10): raise ValueError('Python 3.10+ required')
        if args.command == 'doctor':
            result = doctor(); print(json.dumps(result)); return 0 if not result['errors'] else 1
        if args.command in ('status', 'report'):
            root = state_root(args.state_root, create=False)
            original_id = args.run_id
            redirect = root / ('resumed-' + args.run_id + '.json')
            if redirect.exists():
                args.run_id = load(redirect)['successor']
            pp = pending_path(root, args.run_id)
            if pp.exists() and not (run_dir(root, args.run_id) / 'manifest.json').exists():
                record = load(pp)
                print(json.dumps({**record, 'report': None,
                                  'next_action': 'Resume the same scope and cumulative budget; no completed report exists.'}))
                return 1
            folder, manifest, audit = verify(root, args.run_id)
            freshness = 'unknown'
            if manifest.get('source_locator'):
                try:
                    current = snapshot_saved(manifest['source_locator'], audit['snapshot'])
                    freshness = ('stale' if current['sha256'] != audit['snapshot']['sha256'] else
                                 'partial' if current['limitations'] else 'current')
                except (OSError, ValueError, subprocess.TimeoutExpired): freshness = 'unavailable'
            expired = [r['id'] for r in audit['input'].get('references', []) if r.get('expires_at') and
                       expiry(r['expires_at']) <= datetime.now(timezone.utc)]
            unavailable = [r['id'] for r in audit['input'].get('references', []) if r.get('available') is False]
            exceptions = expired_exceptions(audit['input'])
            index = load(root / 'index.json')
            superseded = next((r.get('superseded_by') for r in index['runs'] if r['run_id'] == args.run_id), None)
            # Re-render only the saved record. Do not upgrade any observation.
            if args.command == 'report':
                if manifest['generator_version'] != GENERATOR: raise ValueError('use pinned generator version to re-render')
                if digest(render(audit).encode()) != manifest['hashes']['report.html']:
                    raise ValueError('render differs from saved report')
            current_evidence = freshness == 'current' and audit['analysis']['evidence_current'] and not expired and not unavailable and not exceptions and not superseded
            freshness_reason = ('Organization evidence is coordinator-asserted; no local source locator or independent Git/source verification. Exit 0 describes a complete saved advisory only.'
                                if audit['scope'].get('kind') == 'organization' else
                                'Source rechecked within the saved inventory scope and limits; current_evidence also requires available support and unexpired exceptions.')
            # Older records have the same saved input binding but no rejection
            # codes. Inspect that binding without re-running the audit.
            rejected = audit['analysis'].get('evidence_rejections')
            if rejected is None:
                rejected = evidence_rejections(audit['input'], audit['snapshot'])
            print(json.dumps({'run_id': args.run_id, 'requested_run_id': original_id,
                              'completion': audit['completion'], 'freshness': freshness,
                              'freshness_reason': freshness_reason,
                              'current_evidence': bool(current_evidence),
                              'current_findings': current_findings(audit['analysis']['findings'], exceptions),
                              'expired_exceptions': exceptions,
                              'evidence_rejections': rejected,
                              'expired_evidence': expired, 'unavailable_evidence': unavailable, 'superseded_by': superseded,
                              'report': str(folder / 'report.html'), 'audit': str(folder / 'audit.json'),
                              'manifest': str(folder / 'manifest.json'), 'generator_version': GENERATOR,
                              'limitations': audit['analysis']['limitations']}))
            return 1 if (audit['completion'] != 'complete' or freshness in ('stale', 'unavailable')
                         or rejected or expired or unavailable or exceptions or superseded) else 0
        if not 1 <= args.repo_budget <= 100 or not 1 <= args.seconds <= 3600:
            raise ValueError('repo budget 1..100 and audit seconds 1..3600 required')
        if args.snapshot and args.org: raise ValueError('--snapshot requires a local repository')
        if args.snapshot_summary and not args.snapshot:
            raise ValueError('--snapshot-summary requires --snapshot')
        limits = snapshot_limits(args.snapshot_files, args.snapshot_seconds if args.snapshot_seconds is not None else min(args.seconds, 30),
                                 args.snapshot_bytes, args.snapshot_file_bytes)
        if limits['seconds'] > args.seconds:
            raise ValueError('snapshot seconds cannot exceed the audit seconds budget')
        started = time.monotonic()
        requested = {'repository_path': str(Path(args.path).resolve()) if not args.org else None,
                     'org': args.org, 'profiles': args.profiles, 'repo_budget': args.repo_budget,
                     'seconds': args.seconds, 'run_checks': args.run_checks}
        requested['snapshot_limits'] = limits
        resumed_pending = None
        if not args.snapshot:
            root = state_root(args.state_root, requested['repository_path'])
            old_pending = pending_path(root, args.resume) if args.resume else None
            if args.resume and (root / ('resumed-' + args.resume + '.json')).exists():
                raise ScopeUnavailable('Interrupted run already resumed; use its successor from status.')
            if old_pending and old_pending.exists() and not (run_dir(root, args.resume) / 'manifest.json').exists():
                resumed_pending = load(old_pending)
                if resumed_pending['requested_scope'] != requested:
                    raise ValueError('resume must retain original requested scope and limits')
            pending = {'schema_version': 1, 'run_id': 'omg-' + uuid.uuid4().hex[:20],
                       'completion': 'partial', 'phase': 'source collection', 'generated_at': now(),
                       'requested_scope': requested, 'snapshot_sha256': None,
                       'elapsed_seconds': (resumed_pending or {}).get('elapsed_seconds', 0),
                       'elapsed_before_attempt': (resumed_pending or {}).get('elapsed_seconds', 0),
                       'counters': (resumed_pending or {}).get('counters', {'repos': 0}),
                       'owned_handles': (resumed_pending or {}).get('owned_handles', [])}
            with locked(root):
                if resumed_pending:
                    original = load(old_pending)
                    if original.get('resumed_by'):
                        raise ScopeUnavailable('Interrupted run already resuming; use its successor ' + original['resumed_by'])
                    original.update(phase='resuming', resumed_by=pending['run_id'])
                    write(old_pending, canonical(original))
                write(pending_path(root, pending['run_id']), canonical(pending))
        if args.org:
            if args.run_checks: raise ValueError('org execution requires individually scoped repository invocations')
            data = load(args.input) if args.input else {}
            authorize_input(data, False)
            data = sanitize(data)
            scope = inventory(args.org, data, args.repo_budget, args.seconds)
            bindings = {name: {'head_sha': pack['snapshot']['head_sha'], 'sha256': pack['snapshot']['sha256']}
                        for name, pack in data.get('repositories', {}).items()}
            snap = {'head_sha': None, 'sha256': digest(canonical({'inventory': scope['inventory'], 'repository_bindings': bindings})),
                    'repository_bindings': bindings, 'limitations': []}
            repo, locator = args.org, None
            result = analyze({}, snap, now())
            result['findings'] = []
            result['limitations'].append('Organization scope conformance is separate metadata; TEST findings belong only to the repositories in scope.results.')
            completion = scope['completion']
        else:
            locator = Path(args.path).resolve()
            snap = snapshot(locator, max_files=limits['files'], seconds=limits['seconds'],
                            max_bytes=limits['bytes'], max_file_bytes=limits['file_bytes'])
            if args.snapshot:
                print(json.dumps({k: v for k, v in snap.items() if k != 'files'} if args.snapshot_summary else snap))
                return 1 if snap['limitations'] else 0
            if resumed_pending and resumed_pending.get('snapshot_sha256') not in (None, snap['sha256']):
                raise ValueError('source changed since interrupted collection; resume refuses rebinding')
            pending.update(snapshot_sha256=snap['sha256'], phase='evidence analysis',
                           elapsed_seconds=pending['elapsed_before_attempt'] + time.monotonic() - started,
                           counters={'repos': 1})
            checkpoint(root, pending)
            data = load(args.input) if args.input else {'schema_version': 1}
            authorize_input(data, args.run_checks)
            data = sanitize(data)
            scope = {'kind': 'repository', 'profiles': {k: PROFILES[k] for k in args.profiles},
                     'classification': 'composed profiles' if args.profiles else 'unknown',
                     'owner': 'repository owner', 'next_action': 'Classify risk and compose profiles.' if not args.profiles else 'Inspect named critical decisions.',
                     'limits': {'seconds': args.seconds, 'repos': 1, 'snapshot': limits}, 'counters': {'repos': 1},
                     'run_checks': args.run_checks, 'owned_handles': [],
                     'inspected_groups': data.get('inspected_groups', [])}
            result = analyze(data, snap, now())
            scope['collection_errors'] = history_errors(data)
            scope['test_value_assessment'] = ('inspected sample' if result['evidence_current'] and
                                               result['sample']['inspected'] and not result['sample']['omitted'] else 'incomplete')
            repo = data.get('repository') or locator.name
            completion = 'partial' if snap['limitations'] or scope['collection_errors'] or time.monotonic() - started > args.seconds else 'complete'
        root = state_root(args.state_root, locator)
        coordinator_seconds = data.get('audit_effort', {}).get('incremental_seconds', 0)
        if type(coordinator_seconds) not in (int, float) or not 0 <= coordinator_seconds <= 86400:
            raise ValueError('coordinator incremental audit effort must be finite nonnegative seconds')
        scope['effort_scope'] = ('coordinator-reported incremental tool/inspection effort plus measured helper time'
                                 if data.get('audit_effort') else 'helper time only; coordinator effort unavailable')
        if not data.get('audit_effort'):
            result['limitations'].append('Coordinator inspection/tool effort not supplied; helper counters alone do not prove the complete audit stayed within budget.')
        if args.resume and not resumed_pending:
            _, _, old = verify(root, args.resume)
            if old['snapshot']['sha256'] != snap['sha256'] or old['repository'] != repo:
                raise ValueError('source/scope changed; resume refuses rebinding; start a successor audit')
            if old['scope'].get('limits') != scope.get('limits') or old['profiles'] != args.profiles or old['scope'].get('run_checks') != scope.get('run_checks'):
                raise ValueError('resume must retain original limits, profiles and authorization')
            old_selection = old['input'].get('selection_context')
            if old_selection and old_selection != data.get('selection_context'):
                raise ValueError('resume must retain producing model-selection admission')
            scope['counters'] = old['scope']['counters']
            scope['owned_handles'] = old['scope'].get('owned_handles', [])
            scope['resumed_from'] = args.resume
            scope['elapsed_seconds'] = old['scope'].get('elapsed_seconds', 0) + time.monotonic() - started + coordinator_seconds
            if scope['elapsed_seconds'] > args.seconds: completion = 'partial'
        else:
            scope['elapsed_seconds'] = (resumed_pending or {}).get('elapsed_seconds', 0) + time.monotonic() - started + coordinator_seconds
            if resumed_pending:
                scope['owned_handles'] = resumed_pending['owned_handles']
                scope['resumed_from'] = args.resume
            if scope['elapsed_seconds'] > args.seconds: completion = 'partial'
        if not args.profiles:
            result['limitations'].append('Repository unclassified: owner must select consequence-based profiles.')
        audit = {'schema_version': 1, 'benchmark_version': VERSION, 'generator_version': GENERATOR,
                 'run_id': pending['run_id'], 'repository': repo, 'snapshot': snap,
                 'generated_at': now(), 'completion': completion, 'scope': scope,
                 'profiles': args.profiles, 'risks': data.get('risks', []), 'input': data, 'analysis': result}
        folder = save(root, audit, locator)
        with locked(root):
            pending_path(root, pending['run_id']).unlink()
        print(json.dumps({'run_id': audit['run_id'], 'completion': completion,
                          'report': str(folder / 'report.html'), 'audit': str(folder / 'audit.json'),
                          'manifest': str(folder / 'manifest.json'), 'validation_verdict': result['validation_verdict']}))
        return 0 if completion == 'complete' else 1
    except KeyboardInterrupt:
        if pending:
            pending.update(phase='interrupted', elapsed_seconds=pending['elapsed_before_attempt'] + time.monotonic() - started)
            checkpoint(root, pending)
        print(json.dumps({'completion': 'partial', 'run_id': pending['run_id'] if pending else None,
                          'error': 'Audit interrupted; no readiness claim. Resume the saved scope without resetting its budget.'})); return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError, OverflowError, subprocess.TimeoutExpired) as exc:
        code = 1 if isinstance(exc, (ScopeUnavailable, BlockingIOError, subprocess.TimeoutExpired)) else 2
        if pending:
            try:
                pending.update(completion='blocked', phase='blocked', error=str(exc),
                               elapsed_seconds=pending['elapsed_before_attempt'] + time.monotonic() - started)
                checkpoint(root, pending)
            except (OSError, ValueError): pass
        print(json.dumps({'completion': 'blocked', 'error': str(exc)})); return code


if __name__ == '__main__':
    raise SystemExit(main())
