#!/usr/bin/env python3
"""Run one planned bench-v2 quality start end to end in its own isolated container set.

  python3 bench/container/startctl.py run --scenario engineering-five-stage --arm baseline \\
      --provider codex --repetition 3 --env-file PATH --results DIR \\
      --packages DIR --canary-run RUN_ID

One command does: select the start from bench/v2/plan.json; verify the read-only package
arm; seed the scenario workspace; `benchctl up` with the package, seed and fixture mounts;
smoke, preflight and catalog; link reusable canary evidence; launch the parent with the
scenario prompt (model policy role `parent`); for the interrupt repetition, stop at the
declared stage boundary and send `resume` (role `resume`); wait up to a deadline; capture
the host observations; grade in a separate `--network none` grader container with
T3_BENCH_ISOLATED_GRADER=1; collect usage, ledgers and the attempt record; write a
sanitised summary; and always `down`. The env file is passed to Docker by path only.

`list` prints the exact command for each of the 24 planned starts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V2 = ROOT / 'bench' / 'v2'
sys.path.insert(0, str(V2 / 'tools'))
sys.path.insert(0, str(HERE))
import attempt_record  # noqa: E402
import captured_ledger  # noqa: E402
import observations_to_context  # noqa: E402
import packages  # noqa: E402
import usage  # noqa: E402

PLAN = V2 / 'plan.json'
PROMPTS = HERE / 'prompts'
FIVE_STAGE_PROMPT = V2 / 'fixtures' / 'five_stage' / 'prompt.md'
PROVIDERS = {'codex': 'codex', 'claude': 'claudeAgent', 'claudeAgent': 'claudeAgent'}
PLUGIN_OF = {'engineering-five-stage': ('imps', 'run'), 'negative-missing-delegation': ('imps', 'run'),
             'negative-unavailable-required-review': ('imps', 'run'), 'workflow-ape': ('ape', 'study'),
             'workflow-elephant-goldfish': ('elephant-goldfish', 'check'),
             'workflow-babysitter': ('babysitter', 'pr'), 'workflow-agent-tuneup': ('agent-tuneup', 'audit')}
FIVE_STAGE_SEEDED = {'engineering-five-stage', 'negative-missing-delegation', 'negative-unavailable-required-review'}
DEFAULT_SCENARIO_DIR = 'bench-scenario'
WORKSPACE = '/bench/ws'
JOB_STATE = '/opt/bench-home/.local/state/t3-plugins/jobs'
TRANSCRIPTS = {'claude-jsonl': '/opt/bench-home/.claude/projects', 'codex-rollout': '/opt/bench-home/.codex/sessions'}
DEFAULT_DEADLINE = 4 * 3600  # v1 allowed 4 h for a five-stage job (bench/protocol.md).
BOUNDARY_POLL_SECONDS = 2
STATUS_EVERY_POLLS = 15
GRADER_TIMEOUT = 1800
ACCEPTED_PREFIX = 'accepted'

# Runs inside the agent as the worker UID: stage-N commit subjects with commit times, and a
# summary of rebuilt job state. It never executes workspace code (log only; fsmonitor off).
BOUNDARY_PROBE = r'''
import json, pathlib, re, subprocess
out = {"commits": None, "commit_times": {}, "jobs": []}
r = subprocess.run(["git", "-c", "core.fsmonitor=", "-c", "safe.directory=*", "-C", "/bench/ws", "log",
                    "--format=%s%x09%cI"], capture_output=True, text=True, timeout=20)
if r.returncode == 0:
    out["commits"] = []
    for line in r.stdout.splitlines():
        subject, _, when = line.rpartition("\t")
        m = re.match(r"stage-([1-5]):", subject)
        if m:
            out["commits"].append(int(m.group(1)))
            out["commit_times"].setdefault(m.group(1), when)
root = pathlib.Path("/opt/bench-home/.local/state/t3-plugins/jobs")
if root.is_dir():
    for path in sorted(root.glob("*/job.json"))[:20]:
        try:
            j = json.loads(path.read_text())
        except Exception:
            continue
        out["jobs"].append({"job_id": j.get("job_id"), "status": j.get("status"),
            "stages": [{"id": s.get("id"), "status": s.get("status")} for s in j.get("stages", []) if isinstance(s, dict)],
            "fallbacks": len(j.get("fallbacks") or []), "tasks": len(j.get("tasks") or []),
            "blockers": [b.get("code") for b in j.get("blockers", []) if isinstance(b, dict)]})
print(json.dumps(out))
'''


class StartBlocked(RuntimeError):
    """The start cannot proceed; nothing after this point dispatched a model request."""


# --------------------------------------------------------------------------- plan

def load_plan(path=PLAN):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def select_start(plan, scenario, arm, provider, repetition):
    provider = PROVIDERS.get(provider)
    rows = [s for s in plan['starts'] if s['scenario'] == scenario and s['arm'] == arm
            and s['provider'] == provider and s['repetition'] == repetition]
    if len(rows) != 1:
        raise StartBlocked(f'no single planned start for {scenario}/{arm}/{provider}/r{repetition}')
    return rows[0]


def start_command(start):
    provider = 'claude' if start['provider'] == 'claudeAgent' else 'codex'
    return ('python3 bench/container/startctl.py run --scenario {scenario} --arm {arm} --provider {p} '
            '--repetition {rep} --env-file "$BENCH_ENV_FILE" --results "$BENCH_RESULTS" '
            '--packages "$BENCH_PACKAGES/{arm}" --canary-run "$BENCH_CANARY_RUN_{P}"').format(
        scenario=start['scenario'], arm=start['arm'], p=provider, rep=start['repetition'], P=provider.upper())


# --------------------------------------------------------------------------- inputs

def optional_module(name):
    """The concurrently owned fixture/shim adapters, imported only if present."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _mount_row(row):
    if isinstance(row, dict) and 'source' in row:
        return (row['source'], row['target'], not row.get('readonly', True))
    if isinstance(row, dict):
        return (row['host'], row['container'], bool(row.get('rw', False)))
    host, container, rw = row
    return (host, container, bool(rw))


def normalise_stage(result):
    """Map stage_fixtures.stage() output to what `up`, the prompt and collection need."""
    result = dict(result or {})
    scenario_dir = result.get('outcome_dir') or DEFAULT_SCENARIO_DIR
    if scenario_dir.startswith(WORKSPACE + '/'):
        scenario_dir = scenario_dir[len(WORKSPACE) + 1:]
    if Path(scenario_dir).is_absolute() or '..' in Path(scenario_dir).parts:
        raise StartBlocked('fixture outcome_dir must be inside the workspace')
    paths = result.get('paths') or {}
    sidecar = result.get('sidecar') or None
    values = {}
    if paths.get('settings_target'):
        values['SETTINGS_PATH'] = paths['settings_target']
    if paths.get('sources'):
        values['SOURCES_DIR'] = os.path.commonpath([row['path'] for row in paths['sources'].values()])
    aliases = list(result.get('host_aliases') or ((sidecar or {}).get('agent_add_hosts') or {}).get('names') or [])
    if sidecar and sidecar.get('host'):
        # With agent-only aliases the scripts' own github.com names reach the sidecar.
        values['GITHUB_URL'] = 'https://' + ('github.com' if 'github.com' in aliases else sidecar['host'])
    values.update(result.get('prompt_values') or {})
    return {'mounts': [_mount_row(row) for row in result.get('mounts', []) or []],
            'env': dict(result.get('agent_env') or result.get('env') or {}), 'outcome_dir': scenario_dir,
            'prompt_values': values, 'host_observations': result.get('host_observations'),
            'coordinator_outputs': dict(result.get('coordinator_outputs') or {}),
            'sidecar_args': list((sidecar or {}).get('docker_args') or []), 'sidecar': sidecar is not None,
            'extra_ca': (result.get('trust') or {}).get('github_ca'),
            'host_aliases': aliases,
            'record': {k: result[k] for k in ('staged_inputs', 'notes', 'five_stage', 'routing_sha256')
                       if k in result}}


def seed_inputs(start, seed, private, fixtures=None, capabilities=None):
    """Prepare the workspace seed and any scenario fixtures; returns the normalised stage record."""
    scenario = start['scenario']
    if scenario == 'engineering-five-stage':
        # Loaded by path: bench/tools/prepare_workspace.py (v1) shares the module name.
        spec = importlib.util.spec_from_file_location('bench_v2_prepare_workspace', V2 / 'tools' / 'prepare_workspace.py')
        prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare)
        info = normalise_stage({})
        info['record']['five_stage'] = {k: v for k, v in prepare.prepare(seed).items() if k != 'workspace'}
        return info
    fixtures = fixtures if fixtures is not None else optional_module('stage_fixtures')
    if fixtures is None or not hasattr(fixtures, 'stage'):
        raise StartBlocked('scenario fixtures need bench/container/stage_fixtures.py, which is unavailable')
    seed.mkdir(parents=True)
    # Negatives get the five-stage workspace from stage() itself (protocol: same scenario source).
    return normalise_stage(fixtures.stage(scenario, seed, private, capabilities=capabilities))


def shim_args(scenario, provider, private, shim=None):
    shim = shim if shim is not None else optional_module('mcp_shim')
    if shim is None or not hasattr(shim, 'enabled_for') or not shim.enabled_for(scenario):
        if scenario == 'negative-missing-delegation':
            raise StartBlocked('missing-delegation needs mcp_shim to flip canRunChildTask; adapter unavailable')
        return []
    return list(shim.container_args(scenario, provider, private))


def sidecar_observation(observed, scenario_input):
    """The coordinator-owned sidecar-observation.json, built from the sidecar's own log only."""
    return {'authorized_merge': scenario_input.get('merge_authorized') is True, 'authorized_post': False,
            'head_sha': observed.get('observed_head_sha'), 'merge_calls': observed.get('merge_calls', []),
            'observed_check_sha': observed.get('observed_check_sha'),
            'observed_comment_id': observed.get('observed_comment_id'), 'post_calls': observed.get('post_calls', [])}


def render_prompt(start, identity, staged):
    scenario = start['scenario']
    plugin, operation = PLUGIN_OF[scenario]
    entry = identity['plugins'][plugin]['entry']
    five = FIVE_STAGE_PROMPT.read_text(encoding='utf-8')
    if scenario == 'engineering-five-stage':
        task = five
    else:
        task = (PROMPTS / f'task-{scenario}.md').read_text(encoding='utf-8').replace('{FIVE_STAGE_TASK}', five.rstrip('\n'))
    values = {'SCENARIO_DIR': f'{WORKSPACE}/{staged["outcome_dir"]}',
              'GITHUB_URL': 'http://github.bench.test:8080', **staged['prompt_values']}
    for key, value in values.items():
        task = task.replace('{' + key + '}', str(value))
    wrapper = (PROMPTS / 'wrapper.md').read_text(encoding='utf-8')
    text = (wrapper.replace('{PLUGIN}', plugin).replace('{ENTRY}', entry).replace('{OPERATION}', operation)
            .replace('{WORKSPACE}', WORKSPACE).replace('{TASK}', task.rstrip('\n')))
    unresolved = re.findall(r'\{[A-Z_]+\}', text.replace(five, ''))
    if unresolved:
        raise StartBlocked('scenario prompt has unresolved values: ' + ', '.join(sorted(set(unresolved))))
    return text


# --------------------------------------------------------------------------- canary link

def image_identity(manifest):
    """What makes two runs' images equivalent: pinned sources and programs, not the per-run image ID."""
    keys = ('base_image', 't3_version', 'claude_version', 'codex_version', 'node_version',
            'node_binary_sha256', 't3_binary_sha256', 'build_source_sha256')
    body = {key: manifest.get(key) for key in keys}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def frozen_targets(manifest):
    return manifest.get('runtime_targets'), {
        provider: (row or {}).get('response_model_id')
        for provider, row in (manifest.get('response_identity_metadata', {}).get('identities') or {}).items()}


def canary_evidence(manifest, provider):
    """A verified canary for this provider in a prior run, or a blocker."""
    rows = [row for row in manifest.get('canary_attempts', []) if row.get('provider') == provider]
    if not rows or (rows[-1].get('model_audit') or {}).get('verified') is not True:
        raise StartBlocked(f'no verified {provider} canary in the linked run')
    return {'run_id': manifest.get('run_id'), 'image_identity': image_identity(manifest),
            'targets': frozen_targets(manifest)[0], 'response_identities': frozen_targets(manifest)[1],
            'target_manifest_sha256': manifest.get('target_manifest_sha256')}


def link_canary(evidence, manifest):
    """Reuse rule: same pinned image identity and the same frozen catalog targets and response IDs."""
    checks = {'image_identity_equal': evidence['image_identity'] == image_identity(manifest),
              'frozen_targets_equal': evidence['targets'] == frozen_targets(manifest)[0],
              'response_identities_equal': evidence['response_identities'] == frozen_targets(manifest)[1]}
    if not all(checks.values()):
        raise StartBlocked('canary evidence does not match this run: ' +
                           ', '.join(k for k, v in checks.items() if not v))
    return {'canary_run_id': evidence['run_id'], 'image_identity': evidence['image_identity'],
            'target_manifest_sha256': evidence['target_manifest_sha256'], **checks}


# --------------------------------------------------------------------------- harness

def safe_extract(stream, destination):
    """Extract regular files and directories only; links, devices and escaping names are skipped."""
    skipped = []
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for member in archive:
            name = Path(member.name)
            if name.is_absolute() or '..' in name.parts:
                skipped.append(member.name)
                continue
            target = destination / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source = archive.extractfile(member)
                with open(target, 'xb') as handle:
                    shutil.copyfileobj(source, handle)
                os.chmod(target, 0o700 if member.mode & 0o111 else 0o600)
            else:
                skipped.append(member.name)
    return skipped


class DockerHarness:
    """The live adapter over benchctl and Docker. Tests replace it with a fake."""

    def __init__(self):
        import benchctl
        self.benchctl = benchctl

    def run_dir(self, run_id):
        return self.benchctl.RESULTS / run_id

    def manifest(self, run_id):
        return json.loads((self.run_dir(run_id) / 'resource-manifest.json').read_text(encoding='utf-8'))

    def prior_manifest(self, run_id):
        return json.loads(self.benchctl.find_manifest(run_id).read_text(encoding='utf-8'))

    def up(self, options):
        return self.benchctl.setup(options)

    def step(self, command, run_id):
        return self.benchctl.manage(SimpleNamespace(command=command, run_id=run_id, provider=None))

    def driver(self, run_id, arguments):
        manifest = self.manifest(run_id)
        return self.benchctl.driver(manifest, arguments, self.run_dir(run_id) / 'private.log')

    def write_input(self, run_id, name, text):
        path = self.run_dir(run_id) / 'input' / name
        path.write_text(text, encoding='utf-8')
        path.chmod(0o444)
        return '/bench/input/' + name

    def probe(self, run_id):
        from native_exec import DROP
        agent = self.manifest(run_id)['created_resources']['container_agent']['id']
        result = subprocess.run(['docker', 'exec', agent, *DROP, 'python3', '-c', BOUNDARY_PROBE],
                                capture_output=True, text=True, timeout=60, check=False)
        try:
            return json.loads(result.stdout.splitlines()[-1])
        except (IndexError, ValueError):
            return {'commits': None, 'commit_times': {}, 'jobs': [], 'error': 'probe unavailable'}

    def export(self, run_id, container_path, destination):
        agent = self.manifest(run_id)['created_resources']['container_agent']['id']
        with subprocess.Popen(['docker', 'exec', agent, 'tar', '-C', container_path, '-cf', '-', '.'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
            skipped = safe_extract(process.stdout, destination)
            process.wait(timeout=600)
        if process.returncode:
            raise RuntimeError(f'export of {container_path} failed')
        return skipped

    def capture(self, run_id, thread_id):
        manifest = self.manifest(run_id)
        run_dir = self.run_dir(run_id)
        return self.benchctl.capture_parent_observations(manifest, thread_id, run_dir, run_dir / 'private.log')

    def prior_catalog(self, run_id):
        path = self.benchctl.find_manifest(run_id).parent / 't3-state' / 'observations' / 'isolated-live-catalog.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None

    def github_log(self, run_id):
        manifest = self.manifest(run_id)
        return self.benchctl.container_log_text(manifest['containers']['github'], self.run_dir(run_id) / 'private.log')

    def shim_log(self, run_id):
        path = self.run_dir(run_id) / 't3-state' / 'mcp-shim.jsonl'
        return path.read_text(encoding='utf-8') if path.is_file() and not path.is_symlink() else None

    def catalog(self, run_id):
        path = self.run_dir(run_id) / 't3-state' / 'observations' / 'isolated-live-catalog.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None

    def grade(self, run_id, grade_dir, argv):
        """Run a frozen checker in a fresh no-network grader container; mounts are read-only."""
        manifest = self.manifest(run_id)
        command = grader_command(manifest['image'], run_id, grade_dir, argv)
        result = subprocess.run(command, capture_output=True, text=True, timeout=GRADER_TIMEOUT, check=False)
        return result.returncode, result.stdout


def grader_command(image, run_id, grade_dir, argv):
    return ['docker', 'run', '--rm', '--network', 'none',
            '--label', 'io.t3.issue28.stage=s1b', '--label', f'io.t3.issue28.run={run_id}',
            '--user', '1001:1001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--read-only', '--tmpfs', '/tmp:rw,size=1g', '-e', 'HOME=/tmp',
            '-e', 'T3_BENCH_ISOLATED_GRADER=1',
            '-e', 'GIT_CONFIG_COUNT=1', '-e', 'GIT_CONFIG_KEY_0=safe.directory', '-e', 'GIT_CONFIG_VALUE_0=*',
            '-v', f'{V2}:/opt/grader/v2:ro', '-v', f'{grade_dir}:/grade:ro',
            '--entrypoint', 'python3', image, *argv]


# --------------------------------------------------------------------------- lifecycle pieces

def boundary_reached(arm, probe):
    """Baseline: a stage-3 commit exists. Rebuilt: the job's third stage is accepted."""
    if arm == 'baseline':
        return isinstance(probe.get('commits'), list) and 3 in probe['commits']
    for job in probe.get('jobs') or []:
        stages = job.get('stages') or []
        third = next((s for s in stages if s.get('id') == 's3'), stages[2] if len(stages) > 2 else None)
        if third and str(third.get('status', '')).startswith(ACCEPTED_PREFIX):
            return True
    return False


def overshoot(arm, probe):
    """Whether work past the boundary was already recorded when the interrupt landed."""
    if arm == 'baseline':
        return isinstance(probe.get('commits'), list) and any(n > 3 for n in probe['commits'])
    for job in probe.get('jobs') or []:
        stages = job.get('stages') or []
        fourth = next((s for s in stages if s.get('id') == 's4'), stages[3] if len(stages) > 3 else None)
        if fourth and str(fourth.get('status', '')).startswith(ACCEPTED_PREFIX):
            return True
    return False


def await_boundary(harness, run_id, arm, thread_id, deadline, clock=time.monotonic, sleep=time.sleep):
    polls = 0
    while clock() < deadline:
        probe = harness.probe(run_id)
        if boundary_reached(arm, probe):
            return probe
        polls += 1
        if polls % STATUS_EVERY_POLLS == 0:
            status = harness.driver(run_id, ['--thread-status', thread_id]).get('status')
            if status not in {'preparing', 'queued', 'starting', 'running', 'waiting'}:
                return None
        sleep(BOUNDARY_POLL_SECONDS)
    return None


def session_id(path, fmt):
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            for _, line in zip(range(200), handle):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if fmt == 'claude-jsonl' and isinstance(row.get('sessionId'), str):
                    return row['sessionId']
                if fmt == 'codex-rollout' and row.get('type') == 'session_meta':
                    value = (row.get('payload') or {}).get('id')
                    if isinstance(value, str):
                        return value
    except OSError:
        return None
    return None


def _contains(value, needle):
    if isinstance(value, str):
        return value == needle
    if isinstance(value, dict):
        return any(_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains(item, needle) for item in value)
    return False


def attribute(session, captured):
    """parent / worker(task) / unattributed by the provider session ID T3 projected for each thread."""
    if not session or not captured:
        return {'role': 'unattributed'}
    threads = {row.get('id'): row for row in captured.get('threads', []) if isinstance(row, dict)}
    if _contains(threads.get(captured.get('parent_thread_id')), session):
        return {'role': 'parent'}
    for row in captured.get('subagents', []):
        child = threads.get(row.get('childThreadId'))
        if child is not None and _contains(child, session) and isinstance(row.get('id'), str):
            return {'role': 'worker', 'task_id': row['id']}
    return {'role': 'unattributed'}


def build_usage_manifest(raw_root, directory, captured, boundaries):
    """Copy transcripts under neutral names next to a usage.py manifest; return (path, sha list)."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    sources, hashes = [], []
    for fmt in ('claude-jsonl', 'codex-rollout'):
        for index, path in enumerate(sorted((raw_root / fmt).rglob('*.jsonl'))):
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            name = f'{fmt}-{index:03d}-{digest[:12]}.jsonl'
            (directory / name).write_bytes(data)
            hashes.append(digest)
            sources.append({'file': name, 'format': fmt, **attribute(session_id(path, fmt), captured)})
    manifest = {'schema_version': 1, 'sources': sources, 'boundaries': boundaries}
    path = directory / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return path, hashes


def worker_usage(summary):
    result = {}
    for row in (summary or {}).get('workers', []):
        totals, unknown = row.get('totals') or {}, row.get('unknown') or {}
        entry = {'inferences': totals.get('inferences', 0)}
        reasons = {}
        for field in ('input', 'cache_read', 'cache_write', 'output', 'context'):
            entry[field] = totals.get(field)
            if entry[field] is None:
                reasons[field] = unknown.get(field) or 'unknown in parser summary'
        entry['unknown'] = reasons
        result[row['task_id']] = entry
    return result


def make_record(ctx):
    """The schema-1 attempt record from collected evidence; unknowns are null with reasons."""
    wait, manifest = ctx.get('wait') or {}, ctx.get('manifest') or {}
    provider = wait.get('readback_provider')
    model = wait.get('readback_model')
    target = (manifest.get('runtime_targets') or {}).get(ctx['provider']) or {}
    reasons, metric_reasons = {}, {}
    readback = None
    if isinstance(provider, str) and provider and isinstance(model, str) and model:
        readback = {'provider_instance_id': provider, 'model_id': model}
        options = dict(target.get('options') or {})
    else:
        provider = None
        reasons['provider_instance_id'] = reasons['model_as_read_back'] = 'thread readback unavailable'
        options = {'provider_instance_id': ctx['provider'], **(target.get('options') or {})}
    summary = ctx.get('parser_summary')
    if summary is None:
        reasons['parser_summary'] = ctx.get('parser_error') or 'usage parser not run'
    job_id = ctx.get('job_id')
    if job_id is None:
        reasons['job_id'] = 'no rebuilt job state observed' if ctx['arm'] == 'rebuilt' else 'baseline arm has no generic job state'
    thread_id = ctx.get('thread_id')
    if thread_id is None:
        reasons['thread_id'] = 'launch not accepted'
    t3_build = manifest.get('t3_version')
    if t3_build is None:
        reasons['t3_build'] = 'resource manifest unavailable'
    peak = (summary or {}).get('parent', {}).get('peak_context') if summary else None
    metrics = {'wall_seconds': ctx.get('wall_seconds'), 'repair_count': None,
               'task_count': ctx.get('task_count'), 'compaction_count': None,
               'fallback_count': ctx.get('fallback_count'), 'repeated_setup': None,
               'parent_peak_context': peak, 'worker_usage': worker_usage(summary) if summary else None,
               'attribution_gaps': (summary or {}).get('gaps') if summary else None,
               'retained_plan_correct': None}
    defaults = {'wall_seconds': 'launch or wait did not complete', 'repair_count': 'not derived; owner reads job attempt ledger',
                'task_count': 'no host tool records captured', 'compaction_count': 'not derived from transcripts by this harness',
                'fallback_count': 'no rebuilt job state observed', 'repeated_setup': 'not derived by this harness',
                'parent_peak_context': (summary or {}).get('parent', {}).get('peak_reason') or 'parser summary unavailable',
                'worker_usage': 'parser summary unavailable', 'attribution_gaps': 'parser summary unavailable',
                'retained_plan_correct': ('owner judges retained plan and decisions from recorded state after resume'
                                          if ctx.get('interrupted') else 'no interrupt in this start')}
    for key, value in metrics.items():
        if value is None:
            metric_reasons[key] = defaults[key]
    return {'schema_version': 1, 'start_id': ctx['start_id'], 'attempt': ctx['attempt'], 'arm': ctx['arm'],
            'provider_instance_id': provider, 'model_as_read_back': readback, 'model_options': options,
            'runtime_mode': 'auto', 'os': 'linux (debian bookworm-slim bench image)', 't3_build': t3_build,
            'package_digests': ctx['package_digests'], 'bundle_digests': ctx['bundle_digests'],
            'job_id': job_id, 'thread_id': thread_id, 'task_ids': ctx.get('task_ids', []),
            'check_results': [{'id': c['id'], 'required': bool(c['required']), 'passed': bool(c['passed'])}
                              for c in ctx.get('checks', [])],
            'parser_summary': summary, 'interventions': ctx.get('interventions', []),
            'failures': ctx.get('failures', []), 'private_raw_sha256': sorted(set(ctx.get('raw_sha256', []))),
            'metrics': metrics, 'unknown_reasons': reasons, 'metrics_unknown_reasons': metric_reasons}


def sanitise(value, private_markers):
    """Replace any string carrying a private location with a fixed token; count replacements."""
    count = 0

    def walk(item):
        nonlocal count
        if isinstance(item, str):
            if any(marker and marker in item for marker in private_markers):
                count += 1
                return '<private>'
            return item
        if isinstance(item, dict):
            return {key: walk(sub) for key, sub in item.items()}
        if isinstance(item, list):
            return [walk(sub) for sub in item]
        return item
    return walk(value), count


def allocate_attempt(start_root, retry_reason=None):
    start_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    first = start_root / 'attempt-1'
    if not first.exists():
        return 1, first
    if (start_root / 'attempt-2').exists():
        raise StartBlocked('both attempts of this start are used; a second invalid attempt blocks the requirement')
    previous = json.loads((first / 'summary.json').read_text(encoding='utf-8')) if (first / 'summary.json').is_file() else {}
    if not retry_reason or previous.get('infrastructure_invalid_candidate') is not True:
        raise StartBlocked('attempt 1 exists; a retry needs --retry-infrastructure-invalid and an '
                           'infrastructure-invalid candidate attempt 1')
    return 2, start_root / 'attempt-2'


# --------------------------------------------------------------------------- the start

def run_start(cfg, harness, *, fixtures=None, shim=None, clock=time.monotonic, sleep=time.sleep):
    plan = load_plan(cfg.plan)
    start = select_start(plan, cfg.scenario, cfg.arm, cfg.provider, cfg.repetition)
    provider, scenario = start['provider'], start['scenario']
    results = Path(cfg.results).absolute()
    attempt, attempt_dir = allocate_attempt(results / start['id'], getattr(cfg, 'retry_reason', None))
    private = attempt_dir / 'private'
    private.mkdir(parents=True, mode=0o700)
    summary = {'schema_version': 1, 'protocol': 'bench-v2', 'start_id': start['id'], 'attempt': attempt,
               'scenario': scenario, 'arm': start['arm'], 'provider': provider, 'repetition': start['repetition'],
               'expected_outcome': start['expected_outcome'], 'phase': 'preparing', 'status': 'blocked',
               'infrastructure_invalid_candidate': False, 'blockers': [], 'failures': [], 'interventions': [],
               'started_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    if attempt == 2:
        summary['retry_reason'] = cfg.retry_reason
    ctx = {'start_id': start['id'], 'attempt': attempt, 'arm': start['arm'], 'provider': provider,
           'failures': summary['failures'], 'interventions': summary['interventions'], 'raw_sha256': []}
    run_id = None
    launched = False
    try:
        identity_path = Path(cfg.packages).absolute() / packages.IDENTITY
        verified = packages.verify_identity(identity_path)
        if not verified['verified']:
            raise StartBlocked('package arm failed verification: ' + ', '.join(verified['problems']))
        identity = json.loads(identity_path.read_text(encoding='utf-8'))
        if identity['arm'] != start['arm']:
            raise StartBlocked('package arm does not match the planned start arm')
        ctx.update(package_digests=identity['package_digests'], bundle_digests=identity['bundle_digests'])
        summary['package'] = {'arm': identity['arm'], 'identity_sha256': verified['identity_sha256'],
                              'package_digests': identity['package_digests'],
                              'bundle_digests': identity['bundle_digests'],
                              'versions': {p: r['version'] for p, r in identity['plugins'].items()}}
        evidence = canary_evidence(harness.prior_manifest(cfg.canary_run), provider) if cfg.canary_run else None
        if evidence is None:
            raise StartBlocked('quality starts need --canary-run naming a run with a verified canary')
        # The linked canary run's frozen catalog; routing for the unavailable-review start is built from it.
        capabilities = harness.prior_catalog(cfg.canary_run) if scenario != 'engineering-five-stage' else None
        staged = seed_inputs(start, private / 'seed', private, fixtures, capabilities)
        summary['fixtures'] = staged['record']
        prompt = render_prompt(start, identity, staged)
        options = SimpleNamespace(env_file=str(cfg.env_file), pkg_dir=str(Path(cfg.packages).absolute()),
                                  seed_dir=str(private / 'seed'), agent_mounts=staged['mounts'],
                                  agent_env=staged['env'], agent_args=shim_args(scenario, provider, private, shim),
                                  extra_ca=staged['extra_ca'], sidecar_args=staged['sidecar_args'],
                                  host_aliases=staged['host_aliases'])
        summary['phase'] = 'up'
        run_id = harness.up(options)
        summary['run_id'] = run_id
        for step in ('smoke', 'preflight', 'catalog'):
            summary['phase'] = step
            if harness.step(step, run_id) != 0:
                summary['infrastructure_invalid_candidate'] = True
                raise StartBlocked(f'{step} did not pass before launch')
        manifest = harness.manifest(run_id)
        ctx['manifest'] = manifest
        summary['canary_link'] = link_canary(evidence, manifest)
        summary['parent_target'] = (manifest.get('runtime_targets') or {}).get(provider)
        prompt_name = harness.write_input(run_id, 'start-prompt.md', prompt)
        summary['prompt_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
        prelaunch_path = None
        if scenario != 'engineering-five-stage':
            spec = observations_to_context.contract(scenario)
            prelaunch_path = private / 'ledgers' / 'prelaunch.json'
            prelaunch_path.parent.mkdir(mode=0o700)
            captured_ledger.create_prelaunch(scenario, f'{start["id"]}-a{attempt}-{run_id}',
                                             secrets.token_hex(32), spec['input_sha256'], prelaunch_path)
        title = f'Issue 28 {start["id"]} attempt {attempt} {secrets.token_hex(6)}'
        summary['phase'] = 'launch'
        started = clock()
        deadline = started + cfg.deadline_seconds
        try:
            launch = harness.driver(run_id, ['--launch-provider', provider, '--role', 'parent',
                                             '--prompt-file', prompt_name, '--title', title])
        except RuntimeError as exc:
            found = harness.driver(run_id, ['--find-launch', title]).get('thread_ids')
            if not isinstance(found, list) or len(found) != 1:
                summary['infrastructure_invalid_candidate'] = not found
                raise StartBlocked(f'launch not accepted ({exc}); recovery found {found!r}') from None
            launch = {'threadId': found[0], 'status': 'recovered'}
        thread_id = launch.get('threadId')
        launched = True
        ctx['thread_id'] = summary['thread_id'] = thread_id
        summary['phase'] = 'running'
        if start.get('interrupt_after') == 's3':
            summary['phase'] = 'awaiting-boundary'
            probe = await_boundary(harness, run_id, start['arm'], thread_id, deadline, clock, sleep)
            if probe is None:
                summary['failures'].append('declared s3 boundary was not observed before the run ended or the deadline')
            else:
                interrupted = harness.driver(run_id, ['--interrupt-thread', thread_id])
                after = harness.probe(run_id)
                summary['boundary'] = {'rule': 'stage-3 commit' if start['arm'] == 'baseline' else 'job stage 3 accepted',
                                       'overshoot_at_interrupt': overshoot(start['arm'], after),
                                       'status_after_interrupt': interrupted.get('status'),
                                       'interrupted_after_seconds': round(clock() - started, 1)}
                summary['interventions'].append('interrupt at declared s3 boundary')
                resume = harness.write_input(run_id, 'resume.txt', (PROMPTS / 'resume.txt').read_text(encoding='utf-8'))
                harness.driver(run_id, ['--send-thread', thread_id, '--launch-provider', provider,
                                        '--message-file', resume])
                summary['interventions'].append('resume sent to the same thread')
                ctx['interrupted'] = True
        summary['phase'] = 'waiting'
        remaining = max(1, int(deadline - clock()))
        wait = harness.driver(run_id, ['--wait-thread', thread_id, '--deadline-seconds', str(remaining),
                                       '--expected-message', prompt_name])
        ctx['wait'] = wait
        ctx['wall_seconds'] = round(clock() - started, 1)
        summary.update(run_status=wait.get('status'), timed_out=bool(wait.get('timed_out')),
                       readback={'provider': wait.get('readback_provider'), 'model': wait.get('readback_model')},
                       original_message_exact=wait.get('original_message_exact'))
        target = summary.get('parent_target') or {}
        if wait.get('readback_model') != target.get('model') or wait.get('readback_provider') != provider:
            summary['failures'].append('thread readback differs from the frozen parent target')
        if wait.get('timed_out'):
            summary['failures'].append('run did not finish before the deadline')
        collect(cfg, harness, start, staged, run_id, thread_id, private, prelaunch_path, ctx, summary)
        required = [c for c in ctx.get('checks', []) if c['required']]
        passed = bool(required) and all(c['passed'] for c in required) and not summary['failures']
        summary['status'] = 'passed' if passed else 'failed'
    except StartBlocked as exc:
        summary['blockers'].append(str(exc))
        summary['status'] = 'blocked' if not launched else 'failed'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        summary['failures'].append(f'{type(exc).__name__}: {exc}')
        summary['status'] = 'failed' if launched else 'blocked'
        if not launched:
            summary['infrastructure_invalid_candidate'] = True
    finally:
        if run_id is None and summary['phase'] == 'up':
            summary['blockers'].append('up failed before returning a run ID; find its partial-failure '
                                       'manifest under the bench results root and run benchctl down on it')
        if run_id is not None:
            try:
                summary['down_exit'] = harness.step('down', run_id)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                summary['down_exit'] = None
                summary['blockers'].append(f'down failed: {exc}; rerun benchctl down {run_id}')
        summary['phase'] = 'done'
        summary['finished_utc'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        if 'package_digests' in ctx:
            record = make_record(ctx)
            summary['attempt_record_errors'] = attempt_record.validate(record)
            write_public(attempt_dir / 'attempt-record.json', record, cfg, results)
        write_public(attempt_dir / 'summary.json', summary, cfg, results)
    return summary


def collect(cfg, harness, start, staged, run_id, thread_id, private, prelaunch_path, ctx, summary):
    scenario = start['scenario']
    summary['phase'] = 'capture'
    captured = harness.capture(run_id, thread_id)
    ctx['captured'] = captured
    delegations = observations_to_context._delegations(captured)
    ctx['task_ids'] = [row['output']['taskId'] for row in delegations]
    ctx['task_count'] = len(delegations)
    summary['dispatches'] = observations_to_context.dispatch_calls(captured)
    probe = harness.probe(run_id)
    summary['stage_commits'] = probe.get('commits')
    jobs_dir = private / 'job-state'
    if probe.get('jobs'):
        harness.export(run_id, JOB_STATE, jobs_dir)
    job_states = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(jobs_dir.glob('*/job.json'))] \
        if jobs_dir.is_dir() else []
    if job_states:
        summary['dispatches'] = observations_to_context.dispatch_calls(captured, job_states)
        if len(job_states) == 1:
            ctx['job_id'] = job_states[0].get('job_id')
            ctx['fallback_count'] = len(job_states[0].get('fallbacks') or [])
    # Brief text stays private; the summary keeps operation, worker and host task identity only.
    summary['dispatches'] = [{k: v for k, v in row.items() if k != 'input'} for row in summary['dispatches']]
    workers = sorted({row['worker'] for row in summary['dispatches'] if row.get('worker')})
    summary['workers_dispatched'] = workers
    summary['workers_expected_missing'] = sorted(set(start['workers_expected']) - set(workers))
    # Grading inputs: an exported copy, outside every worker mount.
    summary['phase'] = 'grade'
    grade_dir = private / 'grade'
    exported = grade_dir / 'ws'
    skipped = harness.export(run_id, WORKSPACE, exported)
    if skipped:
        summary['failures'].append(f'{len(skipped)} workspace entries were links or special files and were not graded')
    if scenario == 'negative-missing-delegation':
        import mcp_shim
        text = harness.shim_log(run_id)
        audit = mcp_shim.audit_log(text, start['provider']) if text is not None else {'verified': False,
                                                                                       'reason': 'shim log missing'}
        summary['mcp_shim_audit'] = audit
        if audit.get('verified') is not True:
            # Proposed rule: without a verified catalog mutation the start is infrastructure-invalid.
            summary['failures'].append('catalog mutation not verified by the mcp shim log')
            summary['infrastructure_invalid_candidate'] = True
    extra_host = staged['host_observations']
    if isinstance(extra_host, (str, Path)):
        extra_host = json.loads(Path(extra_host).read_text(encoding='utf-8'))
    extra_host = dict(extra_host or {})
    if staged['sidecar']:
        import github_sidecar
        text = harness.github_log(run_id)
        observed = github_sidecar.observations_from_log(text or '')
        summary['sidecar_log'] = {k: observed.get(k) for k in ('log_complete', 'malformed_lines', 'read_count')}
        if text is None or not observed.get('log_complete'):
            summary['failures'].append('synthetic GitHub log unavailable or incomplete; sidecar routes untraced')
        for key in ('post_calls', 'merge_calls', 'observed_head_sha', 'observed_check_sha', 'observed_comment_id'):
            extra_host[key] = observed.get(key)
        extra_host['trace_coverage'] = sorted(set(extra_host.get('trace_coverage', [])) | set(observed['trace_coverage']))
        scenario_input = json.loads((V2 / 'fixtures/workflows' / scenario / 'input.json').read_text(encoding='utf-8'))
        coordinator = private / 'coordinator'
        coordinator.mkdir(mode=0o700, exist_ok=True)
        path = coordinator / 'sidecar-observation.json'
        path.write_text(json.dumps(sidecar_observation(observed, scenario_input), sort_keys=True) + '\n', encoding='utf-8')
        staged['coordinator_outputs']['sidecar-observation.json'] = path
    checker = start['grading']['checker']
    if scenario == 'engineering-five-stage':
        review = observations_to_context.review_context(captured, harness.catalog(run_id),
                                                        (ctx['manifest'].get('runtime_targets') or {}).get(start['provider']))
        argv = ['/opt/grader/v2/' + checker, '/grade/ws', '--json']
        if review is not None:
            (grade_dir / 'review-context.json').write_text(json.dumps(review, sort_keys=True) + '\n', encoding='utf-8')
            argv += ['--review-context', '/grade/review-context.json']
        else:
            summary['failures'].append('no host-recorded review dispatch for C13')
    else:
        outcome = grade_dir / 'outcome'
        source = exported / staged['outcome_dir']
        if source.is_dir():
            shutil.copytree(source, outcome)
        else:
            outcome.mkdir()
            summary['failures'].append('scenario outcome directory missing from the workspace')
        for name, host_path in staged['coordinator_outputs'].items():
            if (outcome / name).exists():
                summary['failures'].append(f'worker wrote coordinator-owned output {name}; replaced')
                (outcome / name).unlink()
            shutil.copyfile(host_path, outcome / name)
        extra = extra_host or None
        prelaunch = json.loads(prelaunch_path.read_text(encoding='utf-8'))
        context, gaps = observations_to_context.build_context(scenario, outcome, captured, prelaunch, job_states, extra)
        summary['context_gaps'] = gaps
        ctx_dir = grade_dir / 'ctx'
        observations_to_context.write_context_and_capture(context, prelaunch_path, ctx_dir)
        shutil.copyfile(prelaunch_path, ctx_dir / 'prelaunch.json')
        argv = ['/opt/grader/v2/' + checker, scenario, '/grade/outcome', '--context', '/grade/ctx/context.json',
                '--prelaunch-ledger', '/grade/ctx/prelaunch.json', '--capture-ledger', '/grade/ctx/capture.json']
    open_for_grader(grade_dir)
    code, stdout = harness.grade(run_id, grade_dir, argv)
    try:
        graded = json.loads(stdout)
        ctx['checks'] = graded['checks']
        summary['grading'] = {'checker': checker, 'exit_code': code, 'required_passed': graded.get('required_passed'),
                              'checks': [{'id': c['id'], 'required': c['required'], 'passed': c['passed']}
                                         for c in graded['checks']]}
    except (ValueError, KeyError, TypeError):
        summary['grading'] = {'checker': checker, 'exit_code': code, 'required_passed': None}
        summary['failures'].append('grader returned no result')
    # Usage, from transcripts exported out of the container.
    summary['phase'] = 'usage'
    raw = private / 'transcripts'
    for fmt, path in TRANSCRIPTS.items():
        harness.export(run_id, path, raw / fmt)
    boundaries = [{'stage': f's{n}', 'at': when} for n, when in sorted((probe.get('commit_times') or {}).items())]
    usage_dir = private / 'usage'
    manifest_path, hashes = build_usage_manifest(raw, usage_dir, captured, boundaries)
    ctx['raw_sha256'] += hashes
    if captured.get('snapshot_sha256'):
        ctx['raw_sha256'].append(captured['snapshot_sha256'])
    try:
        ctx['parser_summary'] = usage.summarise(manifest_path)
    except (OSError, ValueError, TypeError) as exc:
        ctx['parser_summary'] = None
        ctx['parser_error'] = f'usage parser rejected the manifest: {exc}'
    summary['usage_boundaries'] = 'stage-N commit times (proxy for stage boundaries)'


def open_for_grader(root):
    """The grader runs as the container worker UID; give it read access inside the private tree."""
    for path in [root, *root.rglob('*')]:
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)


def write_public(path, value, cfg, results):
    markers = [str(results), str(Path(cfg.env_file).absolute()), str(Path(cfg.packages).absolute()),
               str(Path.home()), '/tmp/t3-issue28-container-results']
    clean, count = sanitise(value, markers)
    if isinstance(clean, dict) and count:
        clean['redacted_strings'] = count
    path.write_text(json.dumps(clean, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    path.chmod(0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='print the command for each planned start')
    run = sub.add_parser('run', help='run one planned start')
    run.add_argument('--scenario', required=True)
    run.add_argument('--arm', choices=('baseline', 'rebuilt'), required=True)
    run.add_argument('--provider', choices=('codex', 'claude'), required=True)
    run.add_argument('--repetition', type=int, default=1)
    run.add_argument('--env-file', type=Path, required=True, help='runtime key file; passed to Docker by path only')
    run.add_argument('--results', type=Path, required=True)
    run.add_argument('--packages', type=Path, required=True, help='arm directory built by packages.py')
    run.add_argument('--canary-run', help='run ID holding a verified canary for this provider')
    run.add_argument('--deadline-seconds', type=int, default=DEFAULT_DEADLINE)
    run.add_argument('--retry-infrastructure-invalid', dest='retry_reason', metavar='REASON')
    run.add_argument('--plan', type=Path, default=PLAN, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.command == 'list':
        for start in load_plan()['starts']:
            print(start_command(start))
        return 0
    if args.deadline_seconds <= 0:
        parser.error('--deadline-seconds must be positive')
    try:
        summary = run_start(args, DockerHarness())
    except StartBlocked as exc:
        print(json.dumps({'status': 'blocked', 'blockers': [str(exc)]}))
        return 2
    print(json.dumps({k: summary.get(k) for k in ('start_id', 'attempt', 'status', 'run_id', 'blockers',
                                                  'failures', 'infrastructure_invalid_candidate')}, sort_keys=True))
    return 0 if summary['status'] == 'passed' else (2 if summary['status'] == 'blocked' else 1)


if __name__ == '__main__':
    sys.exit(main())
