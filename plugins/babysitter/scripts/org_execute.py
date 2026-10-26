#!/usr/bin/env python3
"""One deterministic org execution through T3's app-owned task transport.

Requires an admitted run configuration. It never chooses a model, bypasses a job
gate, launches a provider CLI, accepts a worker's work, or starts a timer.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import org_scan


def load_continuous():
    spec = importlib.util.spec_from_file_location('org_continuous', Path(__file__).with_name('continuous.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


continuous = load_continuous()
TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}


class ExecutionError(Exception):
    pass


class NotSubmitted(ExecutionError):
    """The auto-merge mutation is proven not to have been submitted."""


def require(condition, message):
    if not condition:
        raise ExecutionError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def unwrap(value):
    require(isinstance(value, dict), 't3-response-shape')
    if 'jsonrpc' in value:
        require('error' not in value and isinstance(value.get('result'), dict), 't3-rpc-error')
        return unwrap(value['result'])
    if value.get('isError'):
        raise ExecutionError('t3-tool-error')
    if isinstance(value.get('structuredContent'), dict):
        return value['structuredContent']
    if isinstance(value.get('content'), list):
        blocks = [c['text'] for c in value['content'] if c.get('type') == 'text']
        require(len(blocks) == 1, 't3-response-shape')
        return unwrap(json.loads(blocks[0]))
    return value


class T3Host:
    """An external Python process needs an enclosing native-tool adapter."""
    def __init__(self):
        raise ExecutionError('t3-machine-transport-unavailable: use the native tool bridge')


class ToolBridgeHost:
    """JSON-line requests to an enclosing harness code-mode tool adapter."""
    def call(self, tool, arguments):
        print('T3_CALL ' + json.dumps({'tool': tool, 'arguments': arguments}), flush=True)
        line = sys.stdin.readline(16 * 1024 * 1024 + 1)
        require(bool(line) and len(line) <= 16 * 1024 * 1024, 'bridge-response-unavailable')
        return unwrap(json.loads(line))


@contextlib.contextmanager
def bridge_terminal(enabled):
    # PTY canonical input truncates long capability responses. Keep signals but
    # disable canonical buffering and echo so host data cannot fill the output.
    settings = None
    if enabled and sys.stdin.isatty():
        import termios
        settings = termios.tcgetattr(sys.stdin.fileno())
        updated = list(settings)
        updated[6] = list(settings[6])
        updated[3] &= ~(termios.ECHO | termios.ICANON)
        updated[6][termios.VMIN], updated[6][termios.VTIME] = 1, 0
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, updated)
    try:
        if enabled:
            print('T3_READY ' + json.dumps({'pid': os.getpid()}), flush=True)
        yield
    finally:
        if settings is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, settings)


class Jobs:
    def __init__(self, config, directory):
        self.config, self.directory = config, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def call(self, package, command, job_id, payload):
        with tempfile.NamedTemporaryFile(mode='w', dir=self.directory, suffix='.json') as stream:
            json.dump(payload, stream)
            stream.flush()
            argv = [sys.executable, str(Path(package) / 'shared/job_cli.py'), command,
                    '--state-root', self.config['jobs_root'], '--job', job_id, '--input', stream.name]
            if command == 'create':
                argv += ['--prefix', self.config['prefix'], '--agents-root', self.config['agents_root']]
            result = subprocess.run(argv, text=True, capture_output=True, timeout=60)
        require(result.returncode == 0, 'job-gate:' + command)
        return json.loads(result.stdout)

    def prepare(self, row):
        cfg = self.config
        job_id = 'org-' + digest([cfg['run_id'], row['url']])[:32]
        job_file = Path(cfg['jobs_root']) / job_id / 'job.json'
        if not job_file.exists():
            plan = copy.deepcopy(cfg['job_template'])
            require(plan['workflow'] == 'babysitter/org', 'template-workflow')
            require(len(plan['stages']) == len(plan['tasks']) == 1, 'template-needs-single-maintainer')
            task, stage = plan['tasks'][0], plan['stages'][0]
            require(task['worker_id'] == 'babysitter/pr-maintainer'
                    and not task.get('review_required'), 'template-needs-single-maintainer')
            actions = plan['authorization']['actions']
            require(set(actions) == {'read', 'push', 'communicate', 'merge'}, 'template-authorization')
            plan.update(job_id=job_id, objective='Maintain ' + row['url'] + ' through the authorized endpoint.')
            plan['authorization']['prs'] = {row['url']: list(actions)}
            plan['requirements'] = {'PR': 'Clear every observed blocker on ' + row['url'] + ' and verify the authorized endpoint.'}
            stage.update(requirements=['PR'], revision=stage['id'] + '@' + row['head_sha'][:12])
            stage['validator_contract'].update(pr=row['url'], head_sha=row['head_sha'])
            snapshot = self.directory / (job_id + '-initial.json')
            continuous.save_json(snapshot, row)
            stage.setdefault('resources', {})['org_triage'] = {
                'path': str(snapshot), 'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()}
            task['request_id'] = job_id + '-initial'
            if 'requirements' in task:
                task['requirements'] = ['PR']
            task['write_scope'] = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task['task_id']}
            for key in ('handles', 'followups', 'brief', 'execution_history', 'dispatch_history'):
                task.pop(key, None)
            task.update(status='pending', attempt=0)
            self.call(cfg['package'], 'create', job_id, plan)
        job = json.loads(job_file.read_text())
        require(job['authorization'].get('prs', {}).get(row['url']) is not None, 'job-pr-mismatch')
        package = job['pins']['babysitter']['package_dir']
        caller = {**cfg['caller'], 'package_digest': job['pins']['babysitter']['package_digest']}
        self.call(package, 'overview', job_id, {})  # All pin and ledger checks apply on resume.
        task = job['tasks'][0]
        ledger = continuous.read_state(cfg['continuous_state']) if cfg.get('continuous_state') else None
        rejected = next((d for d in (ledger or {}).get('prs', {}).get(row['url'], {}).get('dispatches', [])
                         if d['request_id'] == task['request_id'] and d['status'] == 'rejected'
                         and not d.get('host_task_id')), None)
        if rejected and not any(h.get('request_id') == task['request_id'] for h in task.get('handles', [])) \
                and not task.get('uncertain_calls'):
            evidence = self.directory / (task['request_id'] + '-not-submitted.json')
            continuous.save_json(evidence, {'request_id': task['request_id'], 'submitted': False,
                'reason': rejected.get('note') or 'Final admission refused before the host call.'})
            self.call(package, 'task-observation', job_id, {'caller': caller, 'task_id': task['task_id'],
                'event': {'kind': 'not-submitted', 'request_id': task['request_id'], 'reference': {
                    'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                    'bytes': evidence.stat().st_size}}})
            self.call(package, 'retry', job_id, {'caller': caller, 'task_id': task['task_id'],
                'reason': 'Refresh an unlaunched request after final admission changed.'})
            job = json.loads(job_file.read_text())
            task = job['tasks'][0]
        current_handles = [h for h in task.get('handles', []) if h.get('request_id') == task['request_id']]
        require(not task.get('uncertain_calls') or current_handles, 'job-uncertain-launch')
        if current_handles:
            require(all(h['status'] in TERMINAL and h.get('work_state') == 'result_available'
                        and h.get('has_pending_child_runs') is False for h in current_handles), 'job-active-handle')
            require(any(e['request_id'] == task['request_id'] for e in task.get('execution_history', [])),
                    'job-needs-result-reconciliation')
            self.call(package, 'retry', job_id, {'caller': caller, 'task_id': task['task_id'],
                'reason': 'Fresh current-head observation still requires repair; retain earlier findings and attempts.'})
            job = json.loads(job_file.read_text())
            task = job['tasks'][0]
        prepared = self.call(package, 'prepare', job_id, {'caller': caller, 'task_id': task['task_id']})
        raw = Path(prepared['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == prepared['sha256'], 'brief-digest')
        brief = json.loads(raw)
        target = (brief.get('model_selection') or {}).get('dispatch', {}).get('target') or brief.get('target')
        require(isinstance(target, dict) and target.get('model'), 'missing-selected-target')
        retry_usage, prior_findings = self.history(task)
        if ledger:
            retry_usage['unlaunched'] = [d['request_id'] for d in ledger['prs'].get(row['url'], {}).get('dispatches', [])
                                        if d['kind'] == 'fixer' and d['status'] == 'rejected' and not d.get('host_task_id')]
        return {'job_id': job_id, 'package': package, 'caller': caller,
                'task_id': task['task_id'], 'brief': prepared, 'request_id': brief['request_id'],
                'target': target, 'attempt': brief['attempt'] + 1,
                'retry_usage': retry_usage, 'prior_findings': prior_findings}

    def retained(self, row):
        job_id = 'org-' + digest([self.config['run_id'], row['url']])[:32]
        path = Path(self.config['jobs_root']) / job_id / 'job.json'
        if not path.exists():
            return []
        job = json.loads(path.read_text())
        self.call(job['pins']['babysitter']['package_dir'], 'overview', job_id, {})
        return [h['task_id'] for task in job['tasks'] for h in task.get('handles', [])]

    @staticmethod
    def history(task):
        executions = task.get('execution_history', [])
        attempts = [{'request_id': e['request_id'], 'completion_id': e['completion_id'],
                     'status': (e.get('result') or {}).get('status', 'malformed-result'),
                     'commands': (e.get('result') or {}).get('commands', [])} for e in executions]
        return ({'attempts': attempts, 'max_attempts': 3, 'max_seconds': 300},
                copy.deepcopy(task.get('finding_dispositions', [])))

    def context(self, row):
        job_id = 'org-' + digest([self.config['run_id'], row['url']])[:32]
        path = Path(self.config['jobs_root']) / job_id / 'job.json'
        if not path.exists():
            return None
        job = json.loads(path.read_text())
        package = job['pins']['babysitter']['package_dir']
        self.call(package, 'overview', job_id, {})
        require(set(job['authorization'].get('prs', {}).get(row['url'], [])) ==
                {'read', 'push', 'communicate', 'merge'}, 'job-pr-authorization')
        return {'job_id': job_id, 'package': package, 'task_id': job['tasks'][0]['task_id'],
                'caller': {**self.config['caller'], 'package_digest': job['pins']['babysitter']['package_digest']},
                'job': job}

    def reconcile(self, row, host):
        """One authoritative read per owned handle; ingestion never implies acceptance."""
        ctx = self.context(row)
        if not ctx:
            return {'active': False, 'ingested': []}
        task = ctx['job']['tasks'][0]
        active, ingested, gaps = False, [], []
        for handle in task.get('handles', []) + task.get('followups', []):
            host_id, request = handle.get('task_id', handle.get('host_task_id')), handle['request_id']
            receipt = host.call('task_status', {'taskId': host_id})
            require(receipt.get('taskId') == host_id, 'host-status-identity-mismatch')
            # Persist the actual response before interpreting it, including pending
            # later child runs on an otherwise terminal original task.
            continuous.save_json(self.directory / ('status-' + digest(host_id)[:24] + '.json'), receipt)
            terminal = (receipt['status'] in TERMINAL and receipt.get('workState') == 'result_available'
                        and receipt.get('hasPendingChildRuns') is False)
            if handle.get('forbidden_followup'):
                self.record(ctx, {'kind': 'reconciled', 'request_id': request, 'host_task_id': host_id,
                    'status': receipt['status'], 'work_state': receipt.get('workState'),
                    'has_pending_child_runs': receipt.get('hasPendingChildRuns')})
                active = active or not terminal
                continue  # Status reconciles its blocker; forbidden work has no launch reservation.
            existing = next((e for e in task.get('execution_history', []) if e['request_id'] == request), None)
            summary = receipt.get('summary')
            completion = 'host-' + digest([host_id, request, receipt.get('childRunId'), summary])
            event = {'kind': 'completion' if terminal and not existing and isinstance(summary, str) else 'reconciled',
                'request_id': request, 'host_task_id': host_id, 'status': receipt['status'],
                'work_state': receipt.get('workState'), 'has_pending_child_runs': receipt.get('hasPendingChildRuns')}
            if event['kind'] == 'completion':
                event['completion_id'] = completion
            self.record(ctx, event)
            if not terminal:
                active = True
                continue
            if not existing:
                if not isinstance(summary, str) or not summary:
                    gaps.append({'task_id': host_id, 'request_id': request, 'kind': 'missing-terminal-result'})
                    continue
                self.call(ctx['package'], 'result', ctx['job_id'], {'caller': ctx['caller'],
                    'task_id': ctx['task_id'], 'request_id': request, 'completion_id': completion,
                    'result': {'json': summary}})
            # Re-read the parser's verdict rather than trusting the worker status.
            fresh = self.context(row)['job']['tasks'][0]
            execution = next(e for e in fresh['execution_history'] if e['request_id'] == request)
            ledger = continuous.read_state(self.config['continuous_state'])['prs'][row['url']]
            dispatch = next((d for d in ledger['dispatches'] if d['request_id'] == request), None)
            require(dispatch is not None, 'job-handle-missing-reservation')
            if existing and dispatch.get('status') in continuous.TERMINAL_DISPATCH:
                continue  # Keep the authoritative status read, but do not replay settled receipts.
            if not dispatch.get('host_task_id'):
                continuous_command(self.config, 'dispatch', pr=row['url'], request_id=request,
                    kind='fixer', head=dispatch['head'], reserve=False, host_task_id=host_id,
                    attempt=dispatch['attempt'], review_triage=dispatch.get('review_triage', False))
            ready = not execution.get('malformed') and (execution.get('result') or {}).get('status') == 'ready-for-acceptance'
            continuous_command(self.config, 'receipt', pr=row['url'], request_id=request,
                kind='fixer', head=dispatch['head'], host_task_id=host_id,
                status='succeeded' if ready else 'failed',
                result=str(Path(self.config['jobs_root']) / ctx['job_id'] / 'results' / (request + '.json')),
                reason='Exact terminal transport ingested. Semantic disposition and landing remain separate.')
            if not existing:
                ingested.append(request)
        require(not gaps, 'missing-terminal-result: ' + json.dumps(gaps))
        require(not task.get('uncertain_calls') or task.get('handles'), 'job-uncertain-launch')
        return {'active': active, 'ingested': ingested}

    def workspace(self, row, prepared):
        require(row.get('head_repo') and row.get('head_ref'), 'head-repository-unavailable')
        root = self.directory / 'workspaces' / digest(row['url'])[:16]
        result = subprocess.run(['bash', str(Path(prepared['package']) / 'scripts/pr-workspace.sh'),
            '--repo', row['head_repo'], '--pr', str(row['number']), '--branch', row['head_ref'],
            '--root', str(root), '--preserve'], text=True, capture_output=True, timeout=120)
        require(result.returncode == 0, 'pr-workspace-unavailable')
        path = Path(result.stdout.strip())
        require(path.is_absolute() and path.is_relative_to(root) and (path / '.git').exists(),
                'pr-workspace-path')
        return str(path)

    def guard(self, row, prepared, worktree):
        """Prove repository and ancestry before any child can write source."""
        def git(*args):
            result = subprocess.run(['git', '-C', worktree, *args], text=True, capture_output=True, timeout=30)
            require(result.returncode == 0, 'pr-workspace-identity')
            return result.stdout.strip()
        require(git('remote', 'get-url', 'origin') == 'https://github.com/' + row['head_repo'] + '.git',
                'pr-workspace-repository')
        git('cat-file', '-e', row['head_sha'] + '^{commit}')
        # Diverged or dirty local work stays intact for the repair worker to integrate.
        return {'path': worktree, 'repository': row['head_repo'], 'branch': row['head_ref'],
                'observed_head': row['head_sha'], 'local_head': git('rev-parse', 'HEAD')}

    def semantic(self, row):
        """Consume explicit coordinator judgments, never a worker's resolution claim."""
        ctx = self.context(row)
        if not ctx:
            return None
        reference = self.config.get('semantic_verifications', {}).get(row['url'])
        if not reference:
            return None
        path = Path(reference['path'])
        require(path.is_absolute() and not path.is_symlink() and path.resolve() == path,
                'semantic-evidence-path')
        require(not path.is_relative_to(Path(self.config['jobs_root']).resolve())
                and not path.is_relative_to((self.directory / 'workspaces').resolve()),
                'semantic-evidence-must-be-coordinator-owned')
        raw = path.read_bytes()
        require(len(raw) == reference['bytes'] and hashlib.sha256(raw).hexdigest() == reference['sha256'],
                'semantic-evidence-changed')
        proof = json.loads(raw)
        require(isinstance(proof, dict), 'semantic-evidence-shape')
        require(proof.get('pr') == row['url'], 'semantic-pr-mismatch')
        if proof.get('head_sha') != row['head_sha'] or proof.get('base_sha') != row.get('base_sha') \
                or proof.get('subject_sha256') != semantic_subject(row):
            return None  # Ordinary movement invalidates evidence, not the continuing authority.
        executions = ctx['job']['tasks'][0].get('execution_history', [])
        if executions and proof.get('request_id') != executions[-1]['request_id']:
            return None
        require(bool(proof.get('verification')) and isinstance(proof.get('findings', []), list)
                and isinstance(proof.get('threads', []), list), 'semantic-verification-required')
        require(isinstance(proof.get('repair_required', False), bool), 'semantic-repair-required-must-be-boolean')
        findings = ctx['job']['tasks'][0].get('finding_dispositions', [])
        for disposition in proof.get('findings', []):
            require(disposition.get('disposition') in {'fixed', 'rejected'}, 'semantic-disposition-must-fix-or-reject')
            retained = next((d for d in findings if d['finding_id'] == disposition['finding_id']
                             and d['finding_sha256'] == disposition['finding_sha256']), None)
            require(retained is not None, 'semantic-finding-not-retained')
            if retained.get('disposition') == disposition['disposition'] and retained.get('evidence', {}).get('sha256') == reference['sha256']:
                continue
            self.call(ctx['package'], 'finding-disposition', ctx['job_id'], {'caller': ctx['caller'],
                'task_id': ctx['task_id'], **disposition, 'evidence': reference})
        return proof

    def semantic_request(self, row, *, landing=False, repair_hold=None):
        ctx = self.context(row)
        if not ctx:
            return None
        task = ctx['job']['tasks'][0]
        executions = task.get('execution_history', [])
        if not executions:
            return None
        latest = executions[-1]
        result = latest.get('result') or {}
        # Coordinator concerns survive worker success, even without findings or
        # threads. Failed or malformed work can retry under the retained budget.
        findings = []
        for finding in task.get('finding_dispositions', []):
            evidence = finding.get('evidence') or {}
            current = False
            if evidence.get('path'):
                raw = Path(evidence['path']).read_bytes()
                require(hashlib.sha256(raw).hexdigest() == evidence['sha256'], 'retained-semantic-evidence-changed')
                try:
                    recorded = json.loads(raw)
                except ValueError:
                    recorded = {}
                current = (isinstance(recorded, dict) and recorded.get('head_sha') == row['head_sha']
                           and recorded.get('base_sha') == row.get('base_sha'))
            if finding.get('disposition') not in {'fixed', 'rejected'} or not current:
                findings.append(finding)
        if (result.get('status') != 'ready-for-acceptance' and not landing) or not (findings or row['unresolved_thread_ids'] or repair_hold):
            return None
        return {'pr': row['url'], 'head_sha': row['head_sha'], 'base_sha': row.get('base_sha'),
                'request_id': latest['request_id'],
                'subject_sha256': semantic_subject(row),
                'findings': findings, 'thread_ids': row['unresolved_thread_ids'],
                **({'semantic_repair': copy.deepcopy(repair_hold)} if repair_hold else {}),
                'result_transport': latest['transport_ref'],
                'instruction': 'Verify the concern at this head; supply coordinator evidence, finding dispositions and thread replies.'}

    def record(self, prepared, event):
        return self.call(prepared['package'], 'task-observation', prepared['job_id'],
                         {'caller': prepared['caller'], 'task_id': prepared['task_id'], 'event': event})

    def recover_receipt(self, row):
        """Replay a returned handle only into its exact pinned job and reservation."""
        ctx = self.context(row)
        if not ctx:
            return None
        task = ctx['job']['tasks'][0]
        request = task.get('request_id')
        require(isinstance(request, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', request),
                'host-receipt-request-id')
        path = self.directory / ((request or '') + '-receipt.json')
        if not request or not path.exists():
            return None
        require(not path.is_symlink() and path.is_file(), 'host-receipt-path')
        ledger = continuous.read_state(self.config['continuous_state'])
        require(ledger.get('run_id') == self.config['run_id'] and row['url'] in ledger['prs'],
                'host-receipt-run-mismatch')
        pr = ledger['prs'][row['url']]
        dispatch = next((d for d in pr.get('dispatches', []) if d.get('request_id') == request), None)
        handles = [h for h in task.get('handles', []) if h.get('request_id') == request]
        if len(handles) == 1 and dispatch and dispatch.get('host_task_id') == handles[0].get(
                'task_id', handles[0].get('host_task_id')):
            return None  # A durable handle pair belongs to ordinary reconciliation, even when settled.
        stage = next((s for s in ctx['job']['stages'] if s['id'] == task['stage_id']), {})
        contract = stage.get('validator_contract', {})
        # A live fixer may already have pushed a new head. Recover ownership at
        # its reserved stage head; the fresh head still needs ordinary validation.
        require(dispatch is not None and dispatch.get('kind') == 'fixer'
                and contract.get('pr') == row['url']
                and dispatch.get('head') == contract.get('head_sha')
                and dispatch.get('status') in continuous.OPEN_DISPATCH,
                'host-receipt-reservation-mismatch')
        require(pr.get('fixer', {}).get('request_id') == request
                and pr.get('fixer', {}).get('in_flight'), 'host-receipt-reservation-mismatch')
        receipt = json.loads(path.read_text())
        require(isinstance(receipt, dict) and isinstance(receipt.get('taskId'), str)
                and bool(receipt['taskId']), 'host-receipt-shape')
        brief_ref = task.get('brief')
        require(isinstance(brief_ref, dict) and isinstance(brief_ref.get('path'), str)
                and isinstance(brief_ref.get('sha256'), str), 'host-receipt-unpinned-brief')
        raw = Path(brief_ref['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == brief_ref['sha256'], 'brief-digest')
        brief = json.loads(raw)
        require(brief.get('request_id') == request and brief.get('task_id') == ctx['task_id'],
                'host-receipt-brief-binding')
        require(dispatch.get('attempt') == brief.get('attempt', 0) + 1,
                'host-receipt-reservation-mismatch')
        target = (brief.get('model_selection') or {}).get('dispatch', {}).get('target') or brief.get('target')
        require(isinstance(target, dict) and target.get('model') and target.get('providerInstanceId'),
                'host-receipt-unpinned-target')
        require(isinstance(target.get('options', {}), dict), 'host-receipt-unpinned-target')
        observed_options = receipt.get('options')
        if isinstance(observed_options, list):
            require(all(isinstance(option, dict) and isinstance(option.get('id'), str)
                        and 'value' in option for option in observed_options), 'host-receipt-options-shape')
            observed_options = {option['id']: option['value'] for option in observed_options}
        require(receipt.get('providerInstanceId') == target['providerInstanceId']
                and receipt.get('model') == target['model']
                and observed_options == target.get('options', {}), 'host-receipt-identity-mismatch')
        require(not task.get('uncertain_calls') or handles, 'job-uncertain-launch')
        if handles:
            require(len(handles) == 1 and handles[0].get('task_id', handles[0].get('host_task_id'))
                    == receipt['taskId'], 'host-receipt-handle-mismatch')
        else:
            if dispatch.get('host_task_id'):
                require(dispatch['host_task_id'] == receipt['taskId'], 'host-receipt-handle-mismatch')
            prepared = {'package': ctx['package'], 'job_id': ctx['job_id'], 'task_id': ctx['task_id'],
                        'caller': ctx['caller'], 'request_id': request}
            self.record(prepared, {'kind': 'accepted', 'request_id': request,
                'host_task_id': receipt['taskId'], 'child_thread_id': receipt.get('childThreadId'),
                'status': receipt.get('status', 'running'), 'work_state': receipt.get('workState', 'working'),
                'has_pending_child_runs': receipt.get('hasPendingChildRuns', False),
                'receipt_identity': {k: receipt[k] for k in ('providerInstanceId', 'model', 'options')
                                     if k in receipt}})
            refreshed = self.context(row)['job']['tasks'][0]
            restored = [h for h in refreshed.get('handles', []) if h.get('request_id') == request]
            require(len(restored) == 1 and restored[0].get('task_id', restored[0].get('host_task_id'))
                    == receipt['taskId'], 'host-receipt-not-recorded')
        if dispatch.get('host_task_id'):
            require(dispatch['host_task_id'] == receipt['taskId'], 'host-receipt-handle-mismatch')
        if not dispatch.get('host_task_id'):
            attached = continuous_command(self.config, 'dispatch', pr=row['url'], request_id=request,
                kind='fixer', head=dispatch['head'], reserve=False, host_task_id=receipt['taskId'],
                attempt=dispatch['attempt'], review_triage=dispatch.get('review_triage', False))
            require(attached.get('attached') or attached.get('dispatch', {}).get('host_task_id')
                    == receipt['taskId'], 'host-receipt-not-attached')
        return receipt['taskId']


def semantic_subject(row):
    return digest({k: row.get(k) for k in ('url', 'head_sha', 'base_sha', 'unresolved_thread_ids')})


def observation(report, owners):
    incomplete = [r for r in report['prs'] if r['unknowns']]
    # Do not replace an admitted PR's failure identity with a narrower read.
    # The continuous ledger retains its observation and marks the omitted PR as
    # a discovery gap, blocking every new writer until a complete read returns.
    return {'complete': report['complete'] and not incomplete,
        'gaps': report['gaps'] + [{'kind': 'incomplete-pr',
            'detail': r['url'] + ': ' + ', '.join(r['unknowns'])} for r in incomplete],
        'preserve_human_blockers': True, 'preserve_reconciliation_detail': True, 'prs': [
        {'repo': r['repo'], 'number': r['number'], 'url': r['url'], 'title': r['title'],
         'state': r.get('state', 'OPEN'), 'draft': r.get('draft', False), 'fork': r['fork'], 'head_sha': r['head_sha'],
         'base_sha': r.get('base_sha'),
         'mergeable': r['mergeable'], 'merge_state_status': r['merge_state_status'],
         'review_decision': r['review_decision'], 'unresolved_threads': len(r['unresolved_thread_ids']),
         'review_threads_complete': not any(s.startswith('threads:') for s in r['unknowns']),
         'checks_complete': not any(s.startswith(('checks:', 'check-')) for s in r['unknowns']),
         'checks_state': {'failed': 'FAILURE', 'pending': 'PENDING', 'passed': 'SUCCESS'}.get(r['checks']),
         'failing': [c['name'] for c in r['failing_checks']],
         'pending_checks': [{'name': c['name'], 'status': c['state'], 'conclusion': None} for c in r['pending_checks']],
         'owner': owners.get(r['url'])} for r in report['prs'] if not r['unknowns']]}


def ownership(host, thread_id, rows):
    data = host.call('t3_thread_list', {'settled': False, 'includeSubagents': True, 'limit': 100})
    require(not data.get('nextCursor'), 'sibling-check-partial')
    owners = {}
    for thread in data['threads']:
        if thread['threadId'] == thread_id or thread.get('parentThreadId') == thread_id:
            continue
        # Parked linked PRs are conservatively treated as owned. A coordinator can
        # confirm a handoff; the deterministic runner never guesses from prose.
        for pr in thread.get('pullRequests') or ([thread['linkedPullRequest']] if thread.get('linkedPullRequest') else []):
            owners[pr['url']] = {'thread_id': thread['threadId'], 'status': 'active'}
        title = thread.get('title') or ''
        for row in rows:
            if (row['url'] in title or re.search(r'(?:#|\bPR\s*#?)' + str(row['number']) + r'\b', title, re.I)
                    or (row.get('head_ref') and row['head_ref'] in title)):
                owners[row['url']] = {'thread_id': thread['threadId'], 'status': 'active'}
    return owners


def read_current_pr(api, row, purpose):
    data = api.query('''query($id:ID!) { node(id:$id) { ... on PullRequest {
          id state isDraft headRefOid autoMergeRequest { enabledAt }
          repository { squashMergeAllowed mergeCommitAllowed rebaseMergeAllowed }
        } } %s }''' % org_scan.RATE, {'id': row['node_id']})
    pr = data.get('node')
    require(pr, 'pr-inaccessible')
    require(pr['headRefOid'] == row['head_sha'], 'head-changed-before-' + purpose)
    require(pr['state'] in {'OPEN', 'MERGED', 'CLOSED'} and type(pr['isDraft']) is bool,
            'pr-lifecycle-unknown')
    return pr


def enable_auto_merge(api, row):
    try:
        pr = read_current_pr(api, row, 'auto-merge')
        if pr['state'] in {'MERGED', 'CLOSED'}:
            return pr['state'].lower()
        require(pr['state'] == 'OPEN' and pr['isDraft'] is False, 'pr-no-longer-non-draft')
        if pr['autoMergeRequest'] is not None:
            return 'no-change'
        methods = [('squashMergeAllowed', 'SQUASH'), ('mergeCommitAllowed', 'MERGE'), ('rebaseMergeAllowed', 'REBASE')]
        method = next((m for flag, m in methods if pr['repository'].get(flag)), None)
        require(method is not None, 'no-permitted-merge-method')
    except (ExecutionError, org_scan.ScanError) as exc:
        raise NotSubmitted(str(exc)) from None
    try:
        result = api.query('''mutation($id:ID!,$method:PullRequestMergeMethod!,$head:GitObjectID!) {
      enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:$method,expectedHeadOid:$head}) {
        pullRequest { state autoMergeRequest { enabledAt } }
      }
    }''', {'id': pr['id'], 'method': method, 'head': row['head_sha']}, estimate=5, mutation=True)
    except org_scan.ScanError as exc:
        if str(exc) in {'request-budget', 'cost-budget', 'rate-reserve', 'deadline'}:
            raise NotSubmitted(str(exc)) from None
        raise
    armed = result['enablePullRequestAutoMerge']['pullRequest']
    require(armed.get('autoMergeRequest') is not None or armed.get('state') == 'MERGED', 'auto-merge-not-confirmed')
    return 'merged' if armed.get('state') == 'MERGED' else 'succeeded'


def continuous_command(config, command, **values):
    return getattr(continuous, 'cmd_' + command.replace('-', '_'))(
        argparse.Namespace(state=config['continuous_state'], now=org_scan.utc_now(), **values))


def reject_unlaunched_fixer(config, row, prepared, reason):
    return continuous_command(config, 'receipt', pr=row['url'], request_id=prepared['request_id'],
        kind='fixer', head=row['head_sha'], status='rejected', host_task_id=None, result=None, reason=reason)


def validate_reserved_fixer(config, row, prepared, action):
    """Recheck local authority after the remote read without counting our hold twice."""
    source = Path(config['authorization_source']).read_bytes()
    require(hashlib.sha256(source).hexdigest() == config['authorization_sha256'], 'authorization-source-changed')
    state = continuous.read_state(config['continuous_state'])
    require(state['run_id'] == config['run_id'] and not state.get('cancelled'), 'run-cancelled-or-replaced')
    require(config.get('wake_kind') != 'schedule' or (state['scheduler']['mode'] == 'scheduled'
            and not state['scheduler'].get('stopped')), 'scheduled-continuation-revoked')
    pr = copy.deepcopy(state['prs'][row['url']])
    require(pr['state'] == 'open' and not pr.get('excluded'), 'pr-no-longer-eligible')
    require(continuous.scope_matches(state['scope'], pr) and not continuous.excluded(
            state['scope'], {**pr, **pr['observation']}), 'pr-outside-saved-scope')
    hold = next((d for d in pr['dispatches'] if d['request_id'] == prepared['request_id']), None)
    require(hold and hold['kind'] == 'fixer' and hold['status'] == 'reserved'
            and not hold.get('host_task_id') and pr['fixer']['request_id'] == prepared['request_id'],
            'fixer-reservation-changed')
    pr['dispatches'].remove(hold)
    pr['fixer'] = {'in_flight': False}
    current = continuous.reconcile_pr(pr, state, continuous.parse_time(org_scan.utc_now()), state['discovery'])[0]
    require(current['kind'] == 'dispatch-fixer' and current['request_id'] == action['request_id']
            and current['head'] == row['head_sha'] and current['attempt'] == action['attempt']
            and bool(current.get('review_triage')) == bool(action.get('review_triage')),
            'fixer-decision-changed-before-launch: ' + current['kind'])


def exclude_current_draft(config, row):
    """Record the targeted draft read without replacing other PR observations."""
    path = continuous.state_path(config['continuous_state'])
    now = continuous.parse_time(org_scan.utc_now())
    with continuous.locked_state(path) as state:
        pr = state['prs'][row['url']]
        require(pr['observation']['head_sha'] == row['head_sha'], 'head-changed-in-ledger')
        pr['observation']['draft'] = True
        pr.update(state='excluded', excluded='draft observed before fixer dispatch',
                  excluded_at=continuous.now_iso(now))
        # Exclusion cannot erase a reservation or a handle that raced this read.
        if (continuous.pending_write(pr, state, now) or (pr.get('fixer') or {}).get('in_flight')
                or continuous.live_merge_dispatch(pr)):
            action, queue, blocked, _ = continuous.reconcile_pr(pr, state, now, state['discovery'])
            pr.update(next_action=action, queue=queue, blocked=blocked)
        else:
            pr.update(next_action=None, queue=None, blocked=None)
        continuous.audit(state, now, 'draft-observed', pr=row['url'], head=row['head_sha'])
        continuous.save_json(path, state)


def coordinator_action(row, action, jobs, config, prepared, proof=None):
    """Run the existing guarded helper synchronously under the same writer lock."""
    kind = action['kind']
    threads = proof.get('threads', []) if kind == 'resolution' else [None]
    require(len(threads) <= 100, 'resolution-batch-budget')
    for thread in threads:
        request = action.get('request_id') or ('resolve-' + digest([
            config['run_id'], row['url'], row['head_sha'], thread])[:32])
        ledger = continuous.read_state(config['continuous_state'])['prs'][row['url']]
        previous = next((d for d in ledger['dispatches'] if d['request_id'] == request), None)
        if previous and previous['status'] in continuous.TERMINAL_DISPATCH:
            continue
        if thread:
            require(thread.get('id') in row['unresolved_thread_ids'] and bool(thread.get('reply')),
                    'resolution-not-verified-on-current-pr')
            require(not any(d.get('status') in continuous.OPEN_DISPATCH for d in ledger['dispatches']),
                    'resolution-reservation-held')
        reserved = continuous_command(config, 'dispatch', pr=row['url'], request_id=request,
            kind=kind, head=row['head_sha'], reserve=True, host_task_id=None,
            attempt=1, review_triage=False)
        require(reserved['status'] == 'recorded', kind + '-reservation-held')
        if thread:
            path = continuous.state_path(config['continuous_state'])
            with continuous.locked_state(path) as state:
                hold = next(d for d in state['prs'][row['url']]['dispatches'] if d['request_id'] == request)
                hold['thread_id'] = thread['id']
                continuous.save_json(path, state)
        argv = ['bash', str(Path(prepared['package']) / 'scripts/merge-pr.sh'),
                '--repo', row['repo'], '--pr', str(row['number'])]
        if kind == 'resolution':
            reply = jobs.directory / (request + '-reply.txt')
            reply.write_text(thread['reply'])
            argv += ['--resolve-thread', thread['id'], '--verified-head', row['head_sha'], '--reply-file', str(reply)]
        else:
            argv += ['--expected-head', row['head_sha'], '--update-only' if kind == 'update-branch' else '--no-auto']
        result_path = jobs.directory / (request + '-helper.json')
        try:
            run = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            result = {'request_id': request, 'returncode': run.returncode, 'stdout': run.stdout}
        except (OSError, subprocess.SubprocessError):
            result = {'request_id': request, 'returncode': None, 'stdout': ''}
        continuous.save_json(result_path, result)
        target = re.escape(row['repo'] + '#' + str(row['number']))
        output = result['stdout'].strip()
        if kind == 'update-branch':
            status, _ = continuous.update_helper_receipt(ledger, reserved['dispatch'], result)
        elif kind == 'resolution':
            expected = 'RESOLVED ' + row['repo'] + '#' + str(row['number']) + ' thread=' + thread['id'] + ' head=' + row['head_sha']
            status = 'succeeded' if result['returncode'] == 0 and output in {expected, expected + ' replied=1'} else 'uncertain'
        else:
            status = 'succeeded' if result['returncode'] == 0 and re.fullmatch(r'MERGED ' + target + r' via [^\n]+', output) else 'uncertain'
        continuous_command(config, 'receipt', pr=row['url'], request_id=request, kind=kind,
            head=row['head_sha'], status=status, host_task_id=None,
            result=str(result_path), reason='Guarded helper outcome; fresh gates/lifecycle required before the next write.')
        if status not in {'succeeded', 'no-change'}:
            return {'status': 'held', 'reason': kind + '-outcome-' + status, 'helper_result': str(result_path)}
    return {'status': kind + '-executed', 'next_action': 'refresh-current-head-and-lifecycle'}


def reconcile_synchronous(row, config):
    """Fresh authoritative reads settle unknown completed helper writes, not tasks."""
    if row['unknowns']:
        return
    ledger = continuous.read_state(config['continuous_state'])['prs'].get(row['url'], {})
    for hold in ledger.get('dispatches', []):
        if hold['status'] not in continuous.OPEN_DISPATCH or hold.get('host_task_id') or not hold.get('result_digest'):
            continue
        status = None
        if hold['kind'] == 'resolution' and hold.get('thread_id') and hold['head'] == row['head_sha'] \
                and hold['thread_id'] not in row['unresolved_thread_ids']:
            status = 'succeeded'
        elif hold['kind'] in {'merge', 'auto-merge', 'resolution'} and row.get('state') in {'MERGED', 'CLOSED'}:
            status = 'succeeded' if hold['kind'] == 'merge' and row['state'] == 'MERGED' else 'superseded'
        if status:
            continuous_command(config, 'receipt', pr=row['url'], request_id=hold['request_id'], kind=hold['kind'],
                head=hold['head'], status=status, host_task_id=None, result=None,
                reason='Fresh complete targeted observation settles the synchronous helper outcome.')


def execute(report, api, host, jobs, config):
    require(report['org'] == config['org'], 'org-scope-mismatch')
    source = Path(config['authorization_source']).read_bytes()
    require(hashlib.sha256(source).hexdigest() == config['authorization_sha256'], 'authorization-source-changed')
    state = continuous.read_state(config['continuous_state'])
    continuous.require_current_package(state)
    require(state['scope']['value'].split('/')[0].lower() == config['org']
            and state['thread_id'] == config['thread_id'], 'continuous-scope-mismatch')
    require(state['run_id'] == config['run_id'], 'continuous-run-mismatch')
    require(not state.get('cancelled'), 'run-cancelled')
    wake_kind = config.get('wake_kind', 'manual')
    require(wake_kind != 'schedule' or (state['scheduler']['mode'] == 'scheduled'
            and not state['scheduler'].get('stopped')), 'scheduled-continuation-revoked')
    caps = host.call('orchestrator_capabilities', {})
    require(caps['parentThreadId'] == config['thread_id'], 'wrong-parent-thread')
    report = copy.deepcopy(report)
    seen = {r['url'] for r in report['prs']}
    for known in state['prs'].values():
        if known['url'] in seen or (known['state'] in {'merged', 'closed'}
                and not (known.get('fixer') or {}).get('in_flight')):
            continue
        try:
            report['prs'].append(org_scan.targeted(api, known))
        except (org_scan.ScanError, KeyError, TypeError, ValueError) as exc:
            report['complete'] = False
            report['gaps'].append({'kind': 'targeted-lifecycle', 'pr': known['url'],
                'detail': str(exc) if isinstance(exc, org_scan.ScanError) else 'malformed-targeted-read'})
    owners = ownership(host, config['thread_id'], report['prs'])
    observed = jobs.directory / 'observation.json'
    observed_data = observation(report, owners)
    for pr in observed_data['prs']:
        pr['external_blockers'] = config.get('external_blockers', {}).get(pr['url'], [])
    continuous.save_json(observed, observed_data)
    continuous_command(config, 'observe', observation=str(observed), wake_kind=wake_kind,
                       wake_id=config.get('wake_id'))
    outcomes = []
    # Rotate the first target each wake. Bounded API exhaustion cannot permanently
    # leave the last PR behind a difficult first repository.
    rows = report['prs']
    if rows:
        offset = state.get('advance_cursor', 0) % len(rows)
        rows = rows[offset:] + rows[:offset]
    for row in rows:
        outcome = {'url': row['url'], 'head_sha': row['head_sha'], 'scan_action': row['action'],
                   'repair_reasons': row['reasons'], 'unknowns': row['unknowns'],
                   'coordinator_actions': row['coordinator_actions'],
                   'auto_merge': 'enabled' if row['auto_merge'] else 'pending'}
        outcomes.append(outcome)
        try:
            reconcile_synchronous(row, config)
            # A returned host receipt can outlive either durable job recording or
            # writer attachment. Recover that exact handle before normal status reads.
            if hasattr(jobs, 'recover_receipt'):
                jobs.recover_receipt(row)
            # Reconcile already-owned work even if scope, draft or ownership has
            # changed. These reads cannot authorize another source writer.
            if hasattr(jobs, 'reconcile'):
                lifecycle = jobs.reconcile(row, host)
                outcome['ingested'] = lifecycle['ingested']
                if lifecycle['active']:
                    outcome['status'] = 'active-fixer'
                    continue
            if row.get('state') in {'MERGED', 'CLOSED'}:
                outcome['status'] = row['state'].lower() + '-observed'
                continue
            if row['url'] in owners:
                outcome['status'] = 'owned-elsewhere'
                continue
            if (not continuous.scope_matches(state['scope'], row)
                    or continuous.excluded(state['scope'], row)):
                outcome['status'] = 'excluded-by-saved-scope'
                continue
            require(not row['unknowns'], 'incomplete-pr-observation: ' + ', '.join(row['unknowns']))
            current = continuous.read_state(config['continuous_state'])['prs'].get(row['url'], {})
            if row['auto_merge']:
                for write in current.get('dispatches', []):
                    if (write['kind'] == 'auto-merge' and write.get('head') == row['head_sha']
                            and write.get('status') in continuous.OPEN_DISPATCH):
                        continuous_command(config, 'receipt', pr=row['url'], request_id=write['request_id'],
                            kind='auto-merge', head=row['head_sha'], status='no-change',
                            host_task_id=None, result=None, reason='Fresh same-head read confirms native auto-merge.')
            current = continuous.read_state(config['continuous_state'])['prs'].get(row['url'], {})
            handles = [] if hasattr(jobs, 'reconcile') else jobs.retained(row)
            if handles:
                statuses = [host.call('task_status', {'taskId': task_id}) for task_id in handles]
                outcome.update(status='active-fixer' if any(s['status'] not in TERMINAL or
                    s.get('hasPendingChildRuns') or s.get('workState') != 'result_available'
                    for s in statuses) else 'needs-result-reconciliation', task_ids=handles)
                continue
            require(not (current.get('fixer') or {}).get('in_flight'), 'fixer-reservation-held')
            require(not continuous.live_merge_dispatch(current), 'merge-reservation-held')
            require(not continuous.pending_write(current, state, continuous.parse_time(org_scan.utc_now())),
                    'coordinator-write-reservation-held')
            ledger = continuous.read_state(config['continuous_state'])
            action = continuous.reconcile_pr(ledger['prs'][row['url']], ledger,
                continuous.parse_time(org_scan.utc_now()), ledger.get('discovery') or {})[0]
            outcome.update(next_action=action, blocker=ledger['prs'][row['url']].get('blocked'))
            repair_exhausted = (ledger['prs'][row['url']].get('blocked') or {}).get('kind') == 'repair-exhausted'
            require(repair_exhausted or action['kind'] not in ('blocked', 'needs-human', 'wait-review'),
                    'continuous-action-held: ' + action['reason'])
            proof = jobs.semantic(row) if hasattr(jobs, 'semantic') else None
            if (proof or {}).get('repair_required') or current.get('semantic_repair_hold'):
                path = continuous.state_path(config['continuous_state'])
                task = jobs.context(row)['job']['tasks'][0]
                with continuous.locked_state(path) as ledger:
                    saved = ledger['prs'][row['url']]
                    hold = saved.get('semantic_repair_hold')
                    if proof and proof.get('repair_required') is False:
                        saved.pop('semantic_repair_hold', None)
                        hold = None
                    # Replaying a proof must not reset the repair's producing IDs.
                    elif proof and proof.get('repair_required') is True and (
                            not hold or hold.get('proof_sha256') != digest(proof)):
                        hold = saved['semantic_repair_hold'] = {
                            'head_sha': row['head_sha'], 'base_sha': row.get('base_sha'),
                            'state': 'needs-repair', 'proof_sha256': digest(proof),
                            'verification': proof['verification'], 'findings': proof.get('findings', []),
                            'prior_requests': [h['request_id'] for h in task.get('handles', [])]}
                    if hold:
                        repaired = next((e for e in reversed(task.get('execution_history', []))
                            if e['request_id'] not in hold['prior_requests']
                            and (e.get('result') or {}).get('status') == 'ready-for-acceptance'
                            and not e.get('malformed')), None)
                        if repaired:
                            hold.update(state='needs-verification', repairing_request_id=repaired['request_id'])
                        if hold['head_sha'] != row['head_sha'] or hold.get('base_sha') != row.get('base_sha'):
                            hold['state'] = 'needs-verification'
                    needs_repair = bool(hold and hold.get('state', 'needs-repair') == 'needs-repair')
                    saved['observation']['semantic_repair'] = needs_repair
                    action = continuous.reconcile_pr(saved, ledger, continuous.parse_time(org_scan.utc_now()), ledger['discovery'])[0]
                    continuous.save_json(path, ledger)
                if needs_repair:
                    row['action'] = 'dispatch'
            repair_hold = continuous.read_state(config['continuous_state'])['prs'][row['url']].get('semantic_repair_hold')
            verifying = repair_hold and repair_hold.get('state') == 'needs-verification'
            semantic = jobs.semantic_request(row, landing=bool(verifying) or action['kind'] == 'merge',
                repair_hold=repair_hold if verifying else None) if hasattr(jobs, 'semantic_request') else None
            if proof and proof.get('threads') and not repair_hold:
                prepared = jobs.context(row)
                outcome.update(coordinator_action(row, {'kind': 'resolution'}, jobs, config, prepared, proof))
                continue
            if semantic and (not repair_hold or verifying):
                outcome.update(status='needs-semantic-verification', semantic_request=semantic)
                continue
            require(action['kind'] not in ('blocked', 'needs-human', 'wait-review'),
                    'continuous-action-held: ' + action['reason'])
            if action['kind'] in {'update-branch', 'merge'}:
                prepared = jobs.context(row) or jobs.prepare(row)
                host.call('link_pull_request', {'url': row['url']})
                outcome.update(coordinator_action(row, action, jobs, config, prepared))
                continue
            if row['action'] == 'dispatch':
                require(action['kind'] == 'dispatch-fixer', 'continuous-repair-not-admitted: ' + action['kind'])
            prepared = None
            arm = not row['auto_merge'] and not row.get('draft')
            if arm or row['action'] == 'dispatch':
                # Admission, frozen selection and package/worker integrity are
                # checked before *any* write, including auto-merge.
                prepared = jobs.prepare(row)
                if row['action'] == 'dispatch' and action['attempt'] > 1:
                    require((prepared['retry_usage'].get('attempts') or prepared['retry_usage'].get('unlaunched'))
                            and isinstance(prepared.get('prior_findings'), list),
                            'retry-needs-retained-counters-and-findings')
                host.call('link_pull_request', {'url': row['url']})
            if arm:
                base = 'arm-' + digest([config['run_id'], row['url'], row['head_sha']])[:32]
                attempts = [d for d in current.get('dispatches', []) if d['kind'] == 'auto-merge'
                            and d['request_id'].startswith(base)]
                require(not any(d.get('status') in continuous.OPEN_DISPATCH for d in attempts),
                        'auto-merge-reservation-held')
                require(len(attempts) < 3, 'auto-merge-attempt-budget')
                request = base + '-' + str(len(attempts) + 1)
                reserved = continuous_command(config, 'dispatch', pr=row['url'], request_id=request,
                    kind='auto-merge', head=row['head_sha'], reserve=True, host_task_id=None,
                    attempt=1, review_triage=False)
                require(reserved['status'] == 'recorded', 'auto-merge-reservation-held')
                try:
                    status = enable_auto_merge(api, row)
                except Exception as exc:
                    continuous_command(config, 'receipt', pr=row['url'], request_id=request,
                        kind='auto-merge', head=row['head_sha'], status='rejected' if isinstance(exc, NotSubmitted) else 'uncertain',
                        host_task_id=None, result=None, reason='Re-read auto-merge before reconciling this write.')
                    raise
                continuous_command(config, 'receipt', pr=row['url'], request_id=request,
                    kind='auto-merge', head=row['head_sha'], status='no-change' if status == 'closed'
                        else 'succeeded' if status == 'merged' else status,
                    host_task_id=None, result=None, reason='Native auto-merge confirmed; this is not merge acceptance.')
                if status in {'merged', 'closed'}:
                    continuous_command(config, 'resolve', pr=row['url'], state_value=status, head=row['head_sha'])
                    outcome.update(status=status + '-observed', auto_merge='not-applicable')
                    continue
                outcome['auto_merge'] = 'enabled'
            if row['action'] != 'dispatch':
                outcome['status'] = row['action']
                continue
            target = prepared['target']
            providers = [p for p in caps['providers'] if p['providerInstanceId'] == target['providerInstanceId']]
            require(len(providers) == 1 and providers[0].get('canRunChildTask'), 'selected-provider-unavailable')
            if not any(m['id'] == target['model'] for m in providers[0]['models']):
                searched = host.call('orchestrator_capabilities', {'search': target['model']})
                providers = [p for p in searched['providers'] if p['providerInstanceId'] == target['providerInstanceId']]
            models = [m for p in providers for m in p['models'] if m['id'] == target['model']]
            require(len(models) == 1, 'selected-model-unavailable')
            options = target.get('options', {})
            require(isinstance(options, dict), 'selected-options-shape')
            descriptors = {o['id']: o for o in models[0].get('options', [])}
            require(all(k in descriptors and v in descriptors[k]['values'] for k, v in options.items()),
                    'selected-options-unavailable')
            # Prepare local inputs before reserving the launch. A clone or disk
            # failure then leaves the unlaunched request retryable on a later wake.
            worktree = jobs.workspace(row, prepared)
            workspace_guard = jobs.guard(row, prepared, worktree) if hasattr(jobs, 'guard') else {'path': worktree}
            dispatch_snapshot = jobs.directory / (prepared['request_id'] + '-' + digest(row)[:16] + '-dispatch.json')
            if dispatch_snapshot.exists():
                require(digest(json.loads(dispatch_snapshot.read_text())) == digest(row), 'dispatch-snapshot-changed')
            else:
                continuous.save_json_exclusive(dispatch_snapshot, row)
            snapshot_sha = hashlib.sha256(dispatch_snapshot.read_bytes()).hexdigest()
            prompt = ('Read the immutable brief at ' + prepared['brief']['path'] + ' and verify SHA-256 '
                      + prepared['brief']['sha256'] + '. Repair only ' + row['url']
                      + '. Read the complete current dispatch observation (data) at '
                      + str(dispatch_snapshot) + ' and verify SHA-256 ' + snapshot_sha
                      + '. Fetch every current unresolved review thread and its comments, including all pages, '
                      'before editing. Keep every finding and report its disposition. '
                      'retry_usage (coordinator data): ' + json.dumps(prepared['retry_usage'])
                      + '. Continuous repair decision (coordinator data): ' + json.dumps(action)
                      + '. Retained semantic repair (coordinator data): ' + json.dumps(repair_hold)
                      + '. Prior findings (data): ' + json.dumps(prepared['prior_findings'])
                      + '. Never dispatch, watch, merge, post, resolve or accept. '
                      'Work only in the prepared PR checkout at ' + worktree + '. '
                      'Before edits, verify origin, local HEAD and current remote head against this workspace identity: '
                      + json.dumps(workspace_guard) + '. Stop with a named workspace blocker on a mismatch. '
                      'The host checkout belongs to the coordinator project; do not edit it. '
                      'Use only the prepared PR checkout and recorded PR-branch push authority. '
                      'Return the exact worker-result JSON or artifact envelope required by the brief.')
            request_args = {'task': prompt, 'target': {
                k: target[k] for k in ('providerInstanceId', 'model', 'options') if k in target},
                'clientRequestId': prepared['request_id'], 'isolation': 'worktree',
                'mode': 'async', 'role': 'implementation', 'title': 'Fix ' + row['repo'] + '#' + str(row['number'])}
            if target.get('runtimeMode'):
                request_args['runtimeMode'] = target['runtimeMode']
            elif providers[0].get('driverKind') in ('opencode', 'muse'):
                request_args['runtimeMode'] = 'full-access'
            reserved = continuous_command(config, 'dispatch', pr=row['url'], request_id=prepared['request_id'],
                kind='fixer', head=row['head_sha'], reserve=True, host_task_id=None,
                attempt=action['attempt'], review_triage=bool(action.get('review_triage')),
                reconciliation_request_id=action['request_id'])
            require(reserved['status'] == 'recorded', 'fixer-reservation-held')
            outcome['request_id'] = prepared['request_id']
            # The writer hold precedes the last remote read. A failed validation
            # proves no delegate call occurred, so its reservation can be rejected.
            try:
                fresh = read_current_pr(api, row, 'fixer')
            except (ExecutionError, org_scan.ScanError, OSError, KeyError, TypeError, ValueError):
                reject_unlaunched_fixer(config, row, prepared, 'Final validation failed before delegate_task.')
                raise
            if fresh['state'] in {'MERGED', 'CLOSED'}:
                lifecycle = fresh['state'].lower()
                reject_unlaunched_fixer(config, row, prepared, 'PR became ' + lifecycle + ' before delegate_task.')
                continuous_command(config, 'resolve', pr=row['url'], state_value=lifecycle, head=row['head_sha'])
                outcome.update(status=lifecycle + '-observed', auto_merge='not-applicable')
                continue
            if fresh['isDraft'] and not state['scope'].get('include_drafts'):
                reject_unlaunched_fixer(config, row, prepared, 'PR became a draft before delegate_task.')
                exclude_current_draft(config, row)
                outcome.update(status='excluded-by-current-lifecycle', reason='pr-became-draft')
                continue
            try:
                validate_reserved_fixer(config, row, prepared, action)
            except (ExecutionError, continuous.ContinuousError, OSError, KeyError, TypeError, ValueError):
                reject_unlaunched_fixer(config, row, prepared, 'Local admission changed before delegate_task.')
                raise
            try:
                receipt = host.call('delegate_task', request_args)
                require(receipt.get('taskId'), 'missing-host-handle')
            except Exception:
                jobs.record(prepared, {'kind': 'uncertain', 'request_id': prepared['request_id']})
                raise
            # Retain the actual host handle before identity checks. A mismatch is
            # still owned work and must never disappear or trigger replacement.
            continuous.save_json(jobs.directory / (prepared['request_id'] + '-receipt.json'), receipt)
            outcome.update(task_id=receipt['taskId'], request_id=prepared['request_id'])
            jobs.record(prepared, {'kind': 'accepted', 'request_id': prepared['request_id'],
                'host_task_id': receipt['taskId'], 'child_thread_id': receipt.get('childThreadId'),
                'status': receipt.get('status', 'running'), 'work_state': receipt.get('workState', 'working'),
                'has_pending_child_runs': receipt.get('hasPendingChildRuns', False),
                'receipt_identity': {k: receipt[k] for k in ('providerInstanceId', 'model', 'options') if k in receipt}})
            continuous_command(config, 'dispatch', pr=row['url'], request_id=prepared['request_id'],
                kind='fixer', head=row['head_sha'], reserve=False, host_task_id=receipt['taskId'],
                attempt=action['attempt'], review_triage=bool(action.get('review_triage')),
                reconciliation_request_id=action['request_id'])
            outcome.update(status='dispatched', task_id=receipt['taskId'], request_id=prepared['request_id'])
            require(receipt.get('providerInstanceId') == target['providerInstanceId']
                    and receipt.get('model') == target['model'], 'host-identity-mismatch')
            requested_options = target.get('options', {})
            observed_options = receipt.get('options')
            if isinstance(observed_options, list):
                observed_options = {o['id']: o['value'] for o in observed_options}
            require(observed_options == requested_options, 'host-options-unreported-or-mismatched')
        except (ExecutionError, org_scan.ScanError, continuous.ContinuousError,
                subprocess.SubprocessError, OSError, KeyError, TypeError, ValueError) as exc:
            outcome.update(status='held', reason=str(exc) if isinstance(exc, (ExecutionError, org_scan.ScanError, continuous.ContinuousError)) else 'malformed-execution-data')
    for outcome in outcomes:
        if outcome['status'] in {'dispatched', 'waiting', 'healthy', 'coordinator', 'active-fixer',
                'merge-executed', 'update-branch-executed', 'resolution-executed', 'needs-semantic-verification'}:
            try:
                host.call('watch_pull_request', {'url': outcome['url']})
                outcome['watch'] = 'armed'
            except ExecutionError:
                outcome['watch'] = 'unavailable'
    path = continuous.state_path(config['continuous_state'])
    with continuous.locked_state(path) as latest:
        latest['advance_cursor'] = state.get('advance_cursor', 0) + 1
        continuous.save_json(path, latest)
    coverage = continuous.scheduler_report(continuous.read_state(path), continuous.parse_time(org_scan.utc_now()))
    return {'schema_version': 1, 'org': report['org'], 'scan_complete': report['complete'],
            'scan_gaps': report['gaps'],
            'complete': report['complete'] and all(r['status'] not in
                {'held', 'needs-result-reconciliation', 'needs-semantic-verification'} for r in outcomes)
                and (state['scheduler']['mode'] != 'scheduled' or coverage['coverage'] == 'scheduled'),
            'coverage': coverage,
            'scan_summary': report['summary'], 'outcomes': outcomes, 'api': api.report()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-config', type=Path)
    parser.add_argument('--continuous-state', type=Path, help='resolve the saved execution configuration')
    parser.add_argument('--advance', action='store_true', help='perform one bounded advancement (the default)')
    parser.add_argument('--bridge', action='store_true', help='use the enclosing harness tool bridge')
    parser.add_argument('--probe', action='store_true', help='read-only transport/capability probe')
    parser.add_argument('--wake-kind', choices=('schedule', 'manual', 'event', 'resume'), default='manual')
    parser.add_argument('--wake-id')
    for option, default in [('max-requests', 100), ('max-cost', 200), ('reserve', 500),
                            ('deadline', 180), ('spacing', 1)]:
        parser.add_argument('--' + option, type=org_scan.positive, default=default)
    args = parser.parse_args(argv)
    if not args.probe and not (args.run_config or args.continuous_state):
        parser.error('--run-config is required except with --probe')
    if args.bridge:
        with bridge_terminal(True):
            return run(args)
    return run(args)


def run(args):
    try:
        if args.probe:
            host = ToolBridgeHost() if args.bridge else T3Host()
            caps = host.call('orchestrator_capabilities', {})
            result = {'complete': True, 'transport': 'harness-tool-bridge',
                      'parent_thread_id': caps['parentThreadId'], 'dispatch_available': bool(
                          caps.get('features', {}).get('appOwnedSubagents'))}
            print(('T3_RESULT ' if args.bridge else '') + json.dumps(result), flush=True)
            return 0
        if not args.run_config:
            saved = continuous.read_state(args.continuous_state)
            require(bool(saved.get('execution_config')), 'missing-execution-config: run one advance with --run-config first')
            args.run_config = Path(saved['execution_config']['path'])
            require(hashlib.sha256(args.run_config.read_bytes()).hexdigest() == saved['execution_config']['sha256'],
                    'execution-config-changed: explicitly advance with the updated --run-config')
        config = json.loads(args.run_config.read_text())
        require(Path(config['continuous_state']).resolve() == (args.continuous_state or Path(config['continuous_state'])).resolve(),
                'execution-state-mismatch')
        config.update(wake_kind=args.wake_kind, wake_id=args.wake_id)
        directory = Path(config['execution_dir'])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / 'execute.lock').open('a') as lock:
            org_scan.fcntl.flock(lock, org_scan.fcntl.LOCK_EX | org_scan.fcntl.LOCK_NB)
            api_args = args
            api = org_scan.GitHub(api_args)
            host = ToolBridgeHost() if args.bridge else T3Host()
            path = continuous.state_path(config['continuous_state'])
            state = continuous.read_state(path)
            continuous.require_current_package(state)
            require(state['run_id'] == config['run_id'] and not state.get('cancelled'), 'run-cancelled-or-replaced')
            repository = state['scope']['value'].split('#')[0] if state['scope']['kind'] != 'org' else None
            report = org_scan.scan(api, config['org'], include_drafts=state['scope'].get('include_drafts', False),
                                   repository=repository, repository_offset=state.get('advance_cursor', 0))
            result = execute(report, api, host, Jobs(config, directory), config)
            with continuous.locked_state(path) as latest:
                continuous.require_current_package(latest)
                latest['execution_config'] = {'path': str(args.run_config.resolve()),
                    'sha256': hashlib.sha256(args.run_config.read_bytes()).hexdigest()}
                continuous.save_json(path, latest)
        print(('T3_RESULT ' if args.bridge else '') + json.dumps(result, sort_keys=True, separators=(',', ':')), flush=True)
        return 0 if result['complete'] and all(r['status'] != 'held' for r in result['outcomes']) else 3
    except (ExecutionError, continuous.ContinuousError, OSError, KeyError, ValueError) as exc:
        print(('T3_RESULT ' if args.bridge else '') + json.dumps({'complete': False,
            'error': str(exc) if isinstance(exc, ExecutionError) else 'execution-unavailable'}), flush=True)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
