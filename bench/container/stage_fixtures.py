#!/usr/bin/env python3
"""Stage the frozen non-five-stage bench v2 fixtures for one start.

`stage(scenario_id, workspace, results)` copies only the hashed frozen inputs of a
workflow or negative scenario into the host directory mounted at /bench/ws. The
expected outputs in the fixture directory (observations, receipts, backups) are
never copied. It also builds what the scenario needs around them:

- workflow-ape: two read-only synthetic source repositories, mounted at /bench/sources;
- workflow-agent-tuneup: an editable copy of the synthetic settings, outside any
  provider home;
- workflow-babysitter: a deterministic bare fixture repository, the sidecar scenario and
  per-run TLS material (all carried in the sidecar env-file), the agent-only
  `--add-host` template for github.com and api.github.com, and the agent's gh environment;
- negative starts: the five-stage workspace (reused per bench/v2/protocol.md), their
  inputs, and for unavailable-required-review a repository routing policy whose only
  reviewer target cannot run.

`results` must be coordinator-owned and outside the workspace: TLS material, the
sidecar env-file and the read-only source mount live there. The return value lists
the extra mounts and environment for the agent and sidecar containers; this module
starts nothing. The missing-delegation catalog change is `mcp_shim`, not staged here.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V2 = REPO / 'bench' / 'v2'
WORKFLOWS = V2 / 'fixtures' / 'workflows'
CONTRACTS = WORKFLOWS / 'contracts.json'
CONTAINER_WS = '/bench/ws'
SOURCES_MOUNT = '/bench/sources'
SYNTHETIC_TOKEN = 'bench-synthetic-token'
UNAVAILABLE_REVIEWER = 'reviewer-1'  # negative-unavailable-required-review/input.json
IDENTITY = {'GIT_AUTHOR_NAME': 'bench fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_NAME': 'bench fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
            'GIT_AUTHOR_DATE': '2026-10-12T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-10-12T00:00:00+00:00'}
OUTCOME_DIRS = {'workflow-ape': 'ape', 'workflow-elephant-goldfish': 'elephant-goldfish',
                'workflow-babysitter': 'babysitter', 'workflow-agent-tuneup': 'agent-tuneup',
                'negative-missing-delegation': 'negative-missing-delegation',
                'negative-unavailable-required-review': 'negative-unavailable-required-review'}
NEGATIVES = ('negative-missing-delegation', 'negative-unavailable-required-review')
# A commit can start a detached `git maintenance run --auto` that holds .git/objects/maintenance.lock
# after git returns, then deletes it while the seed is copied or locked down (#58). Runner-created
# repositories never start it. `-c` appends to GIT_CONFIG_PARAMETERS, which git reads after
# GIT_CONFIG_COUNT with the last entry winning, so these values override anything inherited.
QUIET_GIT = {'maintenance.auto': 'false', 'gc.auto': '0'}
QUIET_GIT_ARGS = tuple(arg for key, value in QUIET_GIT.items() for arg in ('-c', f'{key}={value}'))
SCENARIOS = tuple(OUTCOME_DIRS)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(scenario_id: str) -> dict:
    document = json.loads(CONTRACTS.read_text(encoding='utf-8'))
    if document.get('schema_version') != 3:
        raise ValueError('workflow contract schema_version must be 3')
    table = document['negative_scenarios'] if scenario_id in NEGATIVES else document['scenarios']
    return table[scenario_id]


def _git(path: Path, *args) -> str:
    env = dict(os.environ, **IDENTITY, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(['git', *QUIET_GIT_ARGS, '-C', str(path), *args], env=env, check=True,
                          capture_output=True, text=True, timeout=60).stdout.strip()


def prepare_five_stage(workspace: Path) -> dict:
    """Run the frozen prepare_workspace in a child whose git carries QUIET_GIT; it only forwards its environment."""
    params = [os.environ.get('GIT_CONFIG_PARAMETERS', ''), *(f"'{key}={value}'" for key, value in QUIET_GIT.items())]
    env = dict(os.environ, GIT_CONFIG_PARAMETERS=' '.join(filter(None, params)))
    done = subprocess.run([sys.executable, str(V2 / 'tools' / 'prepare_workspace.py'), str(workspace)], env=env,
                          capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise SystemExit(done.stderr.strip() or f'prepare_workspace exited with {done.returncode}')
    return json.loads(done.stdout)


def _private(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    return path


def _container_path(workspace: Path, path: Path) -> str:
    return CONTAINER_WS + '/' + path.relative_to(workspace).as_posix()


def _copy_inputs(scenario_id: str, outcome: Path) -> dict:
    """Copy each frozen input byte for byte and prove its digest; nothing else."""
    terms = contract(scenario_id)
    source = WORKFLOWS / terms['fixture_dir']
    staged = {}
    outcome.mkdir(parents=True, exist_ok=False)
    for name, digest in sorted(terms['input_sha256'].items()):
        if _sha256(source / name) != digest:
            raise ValueError(f'frozen input {scenario_id}/{name} does not match contracts.json')
        shutil.copyfile(source / name, outcome / name)
        if _sha256(outcome / name) != digest:
            raise OSError(f'staged copy of {name} differs from the frozen input')
        staged[name] = digest
    leaked = set(terms['required_outputs']) & {p.name for p in outcome.iterdir()}
    if leaked:
        raise ValueError(f'expected outputs must not be staged: {sorted(leaked)}')
    return staged


def _exclude(workspace: Path, *patterns):
    """Keep coordinator-staged files out of `git status` in the five-stage repository."""
    exclude = workspace / '.git' / 'info' / 'exclude'
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding='utf-8') if exclude.exists() else ''
    with exclude.open('a', encoding='utf-8') as stream:
        for pattern in patterns:
            if pattern not in existing.splitlines():
                stream.write(pattern + '\n')


def _five_stage(workspace: Path) -> dict:
    sys.path.insert(0, str(V2 / 'tools'))
    import prepare_workspace
    if (workspace / '.git').is_dir():
        expected = prepare_workspace.tree_digest(prepare_workspace.FIXTURE)
        if prepare_workspace.tree_digest(workspace) != expected:
            raise ValueError('existing workspace is not the frozen five-stage fixture')
        return {'workspace': str(workspace), 'head': _git(workspace, 'rev-parse', 'HEAD'),
                'fixture_tree_sha256': expected, 'reused': True}
    return prepare_five_stage(workspace)


def _source_repo(root: Path, meta: dict) -> dict:
    """One synthetic source repository with the files its frozen descriptor names."""
    repo = root / meta['repository']
    for relative in meta['files']:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        stem = Path(relative).stem
        target.write_text(f'"""Synthetic {meta["repository"]} module for the bench v2 ape study."""\n\n\n'
                          f'def {stem}_value():\n    return {len(stem)}\n', encoding='utf-8')
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', f'fixture: {meta["repository"]}')
    return {'path': SOURCES_MOUNT + '/' + meta['repository'], 'head': _git(repo, 'rev-parse', 'HEAD'),
            'frozen_descriptor_commit': meta['commit'], 'files': list(meta['files'])}


def _read_only(root: Path):
    for path in sorted(root.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if not path.is_symlink():
            path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _stage_ape(workspace, outcome, area, result):
    sources = area / 'ape-sources'
    sources.mkdir(mode=0o755)
    repos = {}
    for name in ('source-alpha.json', 'source-beta.json'):
        meta = json.loads((outcome / name).read_text(encoding='utf-8'))
        if meta.get('readonly') is not True:
            raise ValueError(f'{name} must describe a read-only source')
        repos[meta['repository']] = _source_repo(sources, meta)
    _read_only(sources)
    result['mounts'].append({'source': str(sources), 'target': SOURCES_MOUNT, 'readonly': True})
    # Git refuses repositories owned by another UID; this is command-line config scoped
    # to the two read-only paths, not a host or provider-home change.
    paths = sorted(repo['path'] for repo in repos.values())
    result['agent_env'].update({'GIT_CONFIG_COUNT': str(len(paths))})
    for index, path in enumerate(paths):
        result['agent_env'][f'GIT_CONFIG_KEY_{index}'] = 'safe.directory'
        result['agent_env'][f'GIT_CONFIG_VALUE_{index}'] = path
    result['paths']['sources'] = repos
    result['notes'].append('source descriptors pin synthetic commit IDs; the staged repositories carry real '
                           'Git commits recorded under paths.sources.*.head')


def _stage_tuneup(workspace, outcome, area, result):
    target = outcome / 'target'
    target.mkdir()
    shutil.copyfile(outcome / 'settings-before.json', target / 'settings.json')
    result['paths']['settings_target'] = _container_path(workspace, target / 'settings.json')
    result['notes'].append('the editable settings file sits in the workspace, never in a provider home; '
                           'settings-after.json and backup.bin are outputs the run must write')


def _stage_babysitter(workspace, outcome, area, result):
    sys.path.insert(0, str(HERE))
    import github_sidecar
    scenario = github_sidecar.scenario_from_fixture(WORKFLOWS / 'workflow-babysitter')
    pull = scenario['pulls'][0]
    repo = scenario['repository']
    # The bare repository reaches the sidecar as a bundle in its env-file; the agent
    # clones it from https://github.com/<owner>/<repo>.git, exactly as the scripts do.
    commits = github_sidecar.build_fixture_repository(area / 'github-git', scenario)
    tls = github_sidecar.tls_material(area / 'github-tls')
    env_file = github_sidecar.write_env_file(area / 'github-sidecar.env', scenario, tls,
                                             github_sidecar.git_bundle(commits['bare']))
    template = [arg for name in github_sidecar.REAL_NAMES for arg in ('--add-host', name + ':{sidecar_ip}')]
    result['sidecar'] = {'env_file': str(env_file), 'docker_args': github_sidecar.container_args(env_file),
                         'ca_cert': str(tls['ca_cert']), 'tls_port': 443, 'http_port': 8080,
                         'tls_names': list(tls['names']), 'host': scenario['host'],
                         'scenario_sha256': hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest(),
                         'agent_add_hosts': {'names': list(github_sidecar.REAL_NAMES), 'template': template,
                                             'fill': 'github_sidecar.agent_host_args(<sidecar IP on the private '
                                                     'network, read with github_sidecar.sidecar_ip_command>)',
                                             'apply_to': 'agent container only'}}
    result['agent_env'].update({'GH_HOST': 'github.com', 'GH_TOKEN': SYNTHETIC_TOKEN, 'GITHUB_TOKEN': SYNTHETIC_TOKEN,
                                'GH_PROMPT_DISABLED': '1', 'GH_NO_UPDATE_NOTIFIER': '1'})
    result['trust'] = {'github_ca': str(tls['ca_cert']),
                       'instruction': 'concatenate with the gateway CA via github_sidecar.trust_bundle and mount '
                                      'the bundle where SSL_CERT_FILE/NODE_EXTRA_CA_CERTS/CURL_CA_BUNDLE point'}
    head_commit = commits['heads'][pull['head_ref']]
    result['paths'].update({'repository': f'{repo["owner"]}/{repo["name"]}', 'pull_request': pull['number'],
                            'clone_url': f'https://github.com/{repo["owner"]}/{repo["name"]}.git',
                            'api': 'https://api.github.com', 'head_ref': pull['head_ref'],
                            'git_head_commit': head_commit, 'git_base_commit': commits['base_sha'],
                            'served_head_sha': pull['head_sha'], 'head_matches_git': head_commit == pull['head_sha']})
    if head_commit != pull['head_sha']:
        result['notes'].append(f'the frozen head {pull["head_sha"]} is not a Git object ID, so merge-pr.sh rejects '
                               f'the PR state as invalid; the deterministic fixture commit is {head_commit}')


def unavailable_review_routing(capabilities: dict) -> dict:
    """Owner-default routing from the frozen catalog, with only an unrunnable reviewer.

    Workhorse and judgement resolve exactly as `t3-plugins setup` would write them —
    the advertised cheap-family models work, the parent model judges; the reviewer role
    names a provider instance the catalog lacks.
    """
    sys.path.insert(0, str(REPO / 'scripts'))
    import routing
    config = routing.default_config(capabilities)
    if any(p.get('providerInstanceId') == UNAVAILABLE_REVIEWER for p in capabilities.get('providers', [])):
        raise ValueError(f'catalog unexpectedly lists {UNAVAILABLE_REVIEWER}')
    config['roles']['reviewer'] = [{'providerInstanceId': UNAVAILABLE_REVIEWER, 'model': UNAVAILABLE_REVIEWER,
                                    'tier': 'medium', 'lineage': 'bench-unavailable'}]
    routing.validate(config)
    reviewer = routing.resolve('reviewer', capabilities, config)
    workhorse = routing.resolve('workhorse', capabilities, config)
    if reviewer['candidates'] or not workhorse['candidates']:
        raise ValueError('routing seed must leave no reviewer and at least one workhorse candidate')
    return config


def _stage_review_routing(workspace, capabilities, result):
    if capabilities is None:
        raise ValueError('negative-unavailable-required-review needs the frozen orchestrator_capabilities '
                         'response (capabilities=...) to seed routing')
    config = unavailable_review_routing(capabilities)
    policy = workspace / '.t3-plugins' / 'routing.json'
    policy.parent.mkdir()
    policy.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    _exclude(workspace, '/.t3-plugins/')
    result['paths']['routing'] = _container_path(workspace, policy)
    result['routing_sha256'] = _sha256(policy)


def stage(scenario_id: str, workspace: Path, results: Path, *, capabilities: dict | None = None) -> dict:
    """Seed one non-five-stage start; returns extra mounts, environment and paths.

    Returned keys: scenario, outcome_dir (container path), host_outcome_dir,
    staged_inputs {name: sha256}, mounts [{source, target, readonly}], docker_args
    (agent `-v` flags), agent_env {name: value}, sidecar (babysitter only), trust,
    paths (scenario-specific container paths) and notes.
    """
    if scenario_id not in SCENARIOS:
        raise ValueError(f'unknown non-five-stage scenario {scenario_id!r}')
    workspace, results = Path(workspace).absolute(), Path(results).absolute()
    if results == workspace or results.is_relative_to(workspace) or workspace.is_relative_to(results / 'stage-fixtures'):
        raise ValueError('results must be coordinator-owned and outside the worker workspace')
    if not workspace.is_dir():
        raise ValueError('workspace must be an existing directory')
    area = _private(results / 'stage-fixtures' / scenario_id)
    result = {'scenario': scenario_id, 'mounts': [], 'agent_env': {}, 'sidecar': None, 'trust': None,
              'paths': {}, 'notes': []}
    if scenario_id in NEGATIVES:
        result['five_stage'] = _five_stage(workspace)
        _exclude(workspace, '/' + OUTCOME_DIRS[scenario_id] + '/')
    elif any(workspace.iterdir()):
        raise ValueError('workflow scenarios need an empty workspace')
    outcome = workspace / OUTCOME_DIRS[scenario_id]
    result['staged_inputs'] = _copy_inputs(scenario_id, outcome)
    if scenario_id == 'workflow-ape':
        _stage_ape(workspace, outcome, area, result)
    elif scenario_id == 'workflow-agent-tuneup':
        _stage_tuneup(workspace, outcome, area, result)
    elif scenario_id == 'workflow-babysitter':
        _stage_babysitter(workspace, outcome, area, result)
    elif scenario_id == 'negative-unavailable-required-review':
        _stage_review_routing(workspace, capabilities, result)
    elif scenario_id == 'negative-missing-delegation':
        result['notes'].append('catalog mutation is applied by mcp_shim.container_args, not by staging')
    result['outcome_dir'] = _container_path(workspace, outcome)
    result['host_outcome_dir'] = str(outcome)
    result['docker_args'] = [arg for mount in result['mounts'] for arg in
                             ('-v', f'{mount["source"]}:{mount["target"]}:{"ro" if mount["readonly"] else "rw"}')]
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('scenario', choices=SCENARIOS)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--capabilities', type=Path, help='saved orchestrator_capabilities response')
    args = parser.parse_args()
    caps = None
    if args.capabilities:
        caps = json.loads(args.capabilities.read_text(encoding='utf-8'))
        caps = caps.get('response', caps) if isinstance(caps, dict) else caps
    print(json.dumps(stage(args.scenario, args.workspace, args.results, capabilities=caps), indent=2))
