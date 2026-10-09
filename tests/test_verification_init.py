"""Source-spec case 16 and REQ-VERIFY-INIT: a generated verification recipe drives
a small fixture product end to end; cleanup removes the run-owned process and
the captured evidence survives."""
import json
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from support import PLUGIN, CoreTestCase, cli, native, result_block


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def facts():
    port_url = 'http://127.0.0.1:${PORT}'
    return {
        'schema_version': 1, 'project': 'notes', 'prerequisites': ['python3 3.10 or later'],
        'variables': {'PORT': 'a free local TCP port', 'DATA': 'a disposable data directory', 'PID': 'launched process id'},
        'launch': {'argv': ['python3', 'app.py', '--port', '${PORT}', '--data', '${DATA}'], 'cwd': '.',
                   'ready': {'kind': 'http', 'url': port_url + '/health', 'timeout_seconds': 15}},
        'doctor': [{'argv': ['python3', '--version'], 'purpose': 'interpreter present'}],
        'cleanup': [{'argv': ['kill', '${PID}'], 'purpose': 'stop the launched service'}],
        'features': [
            {'id': 'F-CREATE', 'name': 'create a note', 'purpose': 'A user stores a note and sees it listed.',
             'observe': 'the created note appears in GET /notes',
             'steps': [{'kind': 'http', 'method': 'POST', 'url': port_url + '/notes', 'body': {'text': 'buy milk'}},
                       {'kind': 'http', 'method': 'GET', 'url': port_url + '/notes'}],
             'expect': [{'kind': 'status', 'step': 1, 'equals': 201},
                        {'kind': 'json_equals', 'step': 2, 'path': '0.text', 'equals': 'buy milk'}]},
            {'id': 'F-HEALTH', 'name': 'health check', 'purpose': 'Operators can see the service is up.',
             'observe': 'GET /health returns ok',
             'steps': [{'kind': 'http', 'method': 'GET', 'url': port_url + '/health'}],
             'expect': [{'kind': 'json_equals', 'step': 1, 'path': 'ok', 'equals': True}]}]}


def substitute(value, variables):
    if isinstance(value, str):
        return re.sub(r'\$\{([A-Z_]+)\}', lambda m: str(variables[m.group(1)]), value)
    if isinstance(value, list):
        return [substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, variables) for key, item in value.items()}
    return value


def http(step):
    data = json.dumps(step['body']).encode() if 'body' in step else None
    request = urllib.request.Request(step['url'], data=data, method=step['method'],
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b'null')
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b'null')


def json_path(value, path):
    for part in path.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


class VerificationInitTest(CoreTestCase):
    def test_generated_recipe_drives_fixture_and_evidence_survives_cleanup(self):
        repo = self.make_repo('verify-product')
        code, env, _ = cli('recipe-scaffold', '--plugin-dir', PLUGIN, '--repo', repo, '--json', json.dumps(facts()))
        self.assertEqual(code, 0, env)
        recipe_dir = repo / '.agents' / 'skills' / 'verify-notes'
        recipe_path = recipe_dir / 'recipe.json'
        self.assertEqual(env['data']['status'], 'draft')
        for name in ('SKILL.md', 'recipe.json', 'features/index.md', 'features/f-create.md', 'features/f-health.md'):
            self.assertTrue((recipe_dir / name).is_file(), name)
        code, env, _ = cli('recipe-check', '--recipe', recipe_path)
        self.assertEqual((env['data']['valid'], env['data']['status']), (True, 'draft'))
        recipe = json.loads(recipe_path.read_text())

        plan = self.plan(repo, brief={'text': 'prove the F-CREATE recipe end to end', 'constraints': [],
                                      'requirements': [{'id': 'REQ-VERIFY-CREATE', 'kind': 'runtime',
                                                        'text': 'F-CREATE recipe creates a note and lists it'}]},
                         policy={'review': {'required': False, 'role': 'reviewer'}, 'checks': [],
                                 'worktree_root': str(self.tmp / 'wt')})
        run = self.init(plan)
        run.claim()
        run.record('transition', {'to': 'executing'})
        generated = sorted(str(p.relative_to(repo)) for p in recipe_dir.rglob('*') if p.is_file())
        run.record('result', {'task_id': 'main', 'text': result_block('main', changed_files=generated)})
        run.record('transition', {'to': 'verifying'})

        for doctor in recipe['doctor']:
            self.assertEqual(native(doctor['argv']).returncode, 0)
        variables = {'PORT': free_port(), 'DATA': str(self.tmp / 'notes-data')}
        launch = substitute(recipe['launch'], variables)
        process = subprocess.Popen([sys.executable if a == 'python3' else a for a in launch['argv']],
                                   cwd=repo / launch['cwd'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        variables['PID'] = process.pid
        run.record('resource', {'kind': 'process', 'pid': process.pid, 'purpose': 'notes service for F-CREATE'})
        deadline = time.time() + launch['ready']['timeout_seconds']
        while True:
            try:
                if http({'method': 'GET', 'url': launch['ready']['url']})[0] == 200:
                    break
            except OSError:
                pass
            self.assertLess(time.time(), deadline, 'service never became ready')
            time.sleep(0.1)

        feature = substitute(next(f for f in recipe['features'] if f['id'] == 'F-CREATE'), variables)
        captured = []
        for number, step in enumerate(feature['steps'], 1):
            status, body = http(step)
            captured.append({'step': number, 'request': step, 'status': status, 'body': body})
        for expect in feature['expect']:
            observed = captured[expect['step'] - 1]
            actual = observed['status'] if expect['kind'] == 'status' else json_path(observed['body'], expect['path'])
            self.assertEqual(actual, expect['equals'])
        evidence = run.scratch('f-create-trace.json', json.dumps(captured, indent=2))
        run.record('acceptance', {'requirement_id': 'REQ-VERIFY-CREATE', 'status': 'passed', 'kind': 'runtime',
                                  'explanation': 'POST /notes returned 201 and GET /notes listed the note',
                                  'artifacts': [str(evidence)]})

        resource = run.state['resources'][0]
        cleanup = substitute(recipe['cleanup'][0]['argv'], variables)
        self.assertEqual(cleanup, resource['cleanup_argv'], 'recipe cleanup targets exactly the recorded process')
        native(cleanup)
        process.wait(timeout=10)
        out = run.record('cleanup', {'resource_id': resource['id'], 'exit_code': 0})
        self.assertEqual(out['result']['status'], 'removed')
        self.assertIsNotNone(process.poll(), 'the launched service is stopped')

        code, env, _ = cli('recipe-stamp', *run.args('--recipe', recipe_path, '--feature', 'F-CREATE',
                                                     '--requirement', 'REQ-VERIFY-CREATE'))
        self.assertEqual((code, env['error']['code']), (4, 'run_not_completed'))
        run.record('transition', {'to': 'ready'})
        run.record('transition', {'to': 'completed'})
        self.assertEqual(run.next()['actions'][0]['action'], 'report', 'no live resources remain')
        code, env, _ = cli('recipe-stamp', *run.args('--recipe', recipe_path, '--feature', 'F-CREATE',
                                                     '--requirement', 'REQ-VERIFY-CREATE'))
        self.assertEqual(code, 0, env)
        code, env, _ = cli('recipe-check', '--recipe', recipe_path)
        self.assertEqual((env['data']['valid'], env['data']['status']), (True, 'verified'))
        stamped = json.loads(recipe_path.read_text())['verified_run']
        self.assertEqual(stamped['run_id'], run.run_id)
        copy = recipe_dir / stamped['evidence'][0]['path']
        self.assertIn('buy milk', copy.read_text())
        stored = run.run_dir / run.state['acceptance'][-1]['artifacts'][0]['path']
        self.assertTrue(stored.is_file(), 'run evidence survives cleanup')

    def test_placeholder_or_unproven_recipe_is_never_verified(self):
        repo = self.make_repo('verify-product')
        bad = facts()
        bad['features'][0]['purpose'] = 'TODO describe this'
        code, env, _ = cli('recipe-scaffold', '--plugin-dir', PLUGIN, '--repo', repo, '--json', json.dumps(bad))
        self.assertEqual((code, env['error']['code']), (2, 'recipe_invalid'))
        code, env, _ = cli('recipe-scaffold', '--plugin-dir', PLUGIN, '--repo', repo, '--json', json.dumps(facts()))
        recipe_path = Path(env['data']['recipe'])
        run = self.init(self.plan(repo, brief={'text': 'x', 'constraints': [], 'requirements': [
            {'id': 'REQ-VERIFY-CREATE', 'kind': 'runtime', 'text': 'F-CREATE works'}]}))
        state_file = run.run_dir / 'run.json'
        state = json.loads(state_file.read_text())
        state['phase'] = 'completed'
        state_file.write_text(json.dumps(state))
        code, env, _ = cli('recipe-stamp', *run.args('--recipe', recipe_path, '--feature', 'F-CREATE',
                                                     '--requirement', 'REQ-VERIFY-CREATE'))
        self.assertEqual(code, 4)
        self.assertIn(env['error']['code'], ('recipe_unproven', 'stale_evidence'), 'no passed runtime acceptance exists')
        recipe = json.loads(recipe_path.read_text())
        recipe['status'] = 'verified'
        recipe_path.write_text(json.dumps(recipe))
        code, env, _ = cli('recipe-check', '--recipe', recipe_path)
        self.assertFalse(env['data']['valid'])
        self.assertIn('verified recipe has no recorded run evidence', env['data']['problems'])
