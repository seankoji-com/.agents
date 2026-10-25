"""Real isolated installed jobs used by continuous receipt and upgrade regressions."""
import io
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

from tests.test_rebuild_installed import ROOT, Sandbox, worker_result


def source_package(base):
    """Copy a developer package together with the external contracts it imports."""
    root = Path(base)
    package = root / 'plugins/babysitter'
    shutil.copytree(ROOT / 'plugins/babysitter', package)
    for name in ('shared', 'core'):
        shutil.copytree(ROOT / name, root / name)
    return package


def plan(manifest, job_id, request_id='fix-request'):
    return {
        'schema_version': 1, 'job_id': job_id,
        'installation_id': manifest['installation_id'], 'workflow': 'babysitter/repo',
        'owner': {'id': 'fixture-owner'}, 'objective': 'maintain a synthetic PR',
        'requirements': {'R1': 'retain immutable evidence'},
        'authorization': {'actions': ['read']}, 'constraints': ['No live services.'],
        'dependencies': [{'key': 'babysitter', 'plugin': 'babysitter'}], 'pins': {},
        'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
        'result_contract': {'schema_version': 1},
        'stages': [{'id': 'repair', 'depends_on': [], 'requirements': ['R1'],
                    'execution_mode': 'workers', 'validator_dependency': 'babysitter',
                    'revision': 'fixture-r1', 'status': 'pending'}],
        'tasks': [{'task_id': 'fix', 'stage_id': 'repair', 'logical_slot_id': 'primary',
                   'request_id': request_id, 'worker_id': 'babysitter/pr-maintainer',
                   'dependency_key': 'babysitter', 'status': 'pending', 'attempt': 0,
                   'handles': [], 'followups': [], 'dispatch_retries': 0}],
        'decisions': [], 'history': [], 'metrics': {},
    }


class AcceptedJob:
    def __init__(self, base, request_id, host='host-fixer'):
        self.box = Sandbox(base)
        self.package, manifest = self.box.install('babysitter')
        self.caller = self.box.caller(manifest, 'babysitter/repo')
        self.job_id, self.host = 'receipt-fixture', host
        self.box.create(self.package, plan(manifest, self.job_id, request_id))
        self.brief = self.box.dispatch(self.package, self.job_id, self.caller, 'fix', host)
        self.directory = self.box.jobs / self.job_id
        self.transport = self.directory / 'results' / (request_id + '.json')

    def complete(self, malformed=False):
        return self.box.complete(self.package, self.job_id, self.caller, 'fix', self.brief,
                                 self.host, 'not a task result' if malformed
                                 else worker_result(self.brief))


def install_legacy(box, source):
    """Bootstrap an old installation with its archived registry and matrix.

    The installer adapter is copied outside the packaged roots. Historical
    plugin/core/shared bytes stay intact; current installs still use today's
    stricter registry. This models a package installed before the upgrade.
    """
    scripts = source / 'scripts'
    scripts.mkdir()
    for name in ('install.py', 'registry.py'):
        shutil.copy2(ROOT / 'scripts' / name, scripts / name)
    result = box.run([sys.executable, scripts / 'install.py', '--plugin', 'babysitter',
                      '--prefix', box.prefix, '--agents-root', box.agents])
    package = Path(json.loads(result.stdout)['data']['version_dir'])
    return package, json.loads((package / 'install-manifest.json').read_text())


def legacy_source(base, revision='4fc614b363a147c4f3220176607156be52941fa9'):
    """Extract actual pinned public source, including in a shallow/offline checkout."""
    source = Path(base) / 'legacy-source'
    source.mkdir()
    fixtures = ROOT / 'tests/fixtures/babysitter-packages'
    pin = json.loads((fixtures / 'provenance.json').read_text())['revisions'][revision]
    archive = (fixtures / pin['archive']).read_bytes()
    if hashlib.sha256(archive).hexdigest() != pin['sha256']:
        raise AssertionError('historical package fixture digest differs from its pin')
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for item in stream.getmembers():
            if item.issym() or item.islnk() or Path(item.name).is_absolute() \
                    or '..' in Path(item.name).parts:
                raise AssertionError('unsafe historical fixture archive')
        stream.extractall(source)
    return source
