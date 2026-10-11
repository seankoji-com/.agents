"""Regression tests for the helper-script findings fixed in the portfolio review.

Each test names the behavior a reviewer could reproduce before the fix:
a sqlite path with `?` opening the wrong database, a JSON-RPC array crashing the
sidecar loop, a transform writing into `.git/`, `process.py` failing under `python3 -I`, and the Codex TOML audit hiding
its Python 3.11 requirement behind a generic receipt.
"""
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDECAR = ROOT / 'plugins/offload-sidecar/scripts/offload_sidecar.py'
PROCESS = ROOT / 'plugins/offload-sidecar/scripts/process.py'
AUDIT = ROOT / 'plugins/agent-tuneup/scripts/audit.py'


def load_sidecar():
    spec = importlib.util.spec_from_file_location('offload_sidecar_hardening', SIDECAR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sidecar = load_sidecar()


def sidecar_env(tmp, **extra):
    env = {
        'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
        'OLLAMA_HOST': 'http://127.0.0.1:1',
        'OLLAMA_STATUS_TIMEOUT': '1',
        'OLLAMA_TIMEOUT': '1',
        'AGY_BIN': '/nonexistent/agy',
        'AGY_QUOTA_STATE': os.path.join(tmp, 'quota.json'),
    }
    env.update(extra)
    return env


class SqlitePathTest(unittest.TestCase):
    def test_question_mark_in_path_opens_the_real_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'a?b.db')
            conn = sqlite3.connect(db)
            conn.execute('create table t (x integer)')
            conn.execute('insert into t values (1)')
            conn.commit()
            conn.close()
            out = sidecar._det_sqlite_dump_to_json(db, {}, '', 'out.json')
            self.assertEqual(json.loads(out)['t'], [{'x': 1}])
            self.assertFalse(os.path.exists(os.path.join(tmp, 'a')), 'a stray truncated database was created')

    def test_empty_database_is_not_a_silent_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'notes.txt')
            Path(path).write_text('not a database')
            with self.assertRaises(sidecar.SidecarError):
                sidecar._det_sqlite_dump_to_json(path, {}, '', 'out.json')


class VcsMetadataGuardTest(unittest.TestCase):
    def test_output_inside_git_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)  # the sidecar's root is always realpath'd; macOS tmp is a symlink
            os.makedirs(os.path.join(tmp, '.git', 'hooks'))
            os.makedirs(os.path.join(tmp, '.GIT'), exist_ok=True)  # the same directory as .git on macOS
            for target in ('.git/hooks/pre-commit', '.git/config', 'sub/.hg/hgrc', '.svn/entries', '.GIT/config'):
                with self.assertRaises(sidecar.SidecarError, msg=target):
                    sidecar.resolve_output_path(tmp, target)
            os.makedirs(os.path.join(tmp, 'notes'))
            self.assertTrue(sidecar.resolve_output_path(tmp, 'notes/out.txt').endswith('out.txt'))


class JsonRpcLoopTest(unittest.TestCase):
    def test_array_line_gets_invalid_request_and_the_loop_survives(self):
        lines = [
            json.dumps([{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}]),
            json.dumps('just a string'),
            json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(SIDECAR)], input='\n'.join(lines) + '\n',
                                  capture_output=True, text=True, env=sidecar_env(tmp), timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual([r.get('id') for r in responses], [None, None, 2])
        self.assertEqual(responses[0]['error']['code'], -32600)
        self.assertEqual(responses[2]['result'], {})


class ProcessIsolatedModeTest(unittest.TestCase):
    def test_doctor_runs_under_python_isolated_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, '-I', str(PROCESS), '--doctor'], capture_output=True,
                                  text=True, env=sidecar_env(tmp), timeout=30, cwd=tmp)
        self.assertNotIn('ModuleNotFoundError', proc.stderr)
        self.assertIn('{', proc.stdout)


class CodexTomlRequirementTest(unittest.TestCase):
    def test_missing_tomllib_is_reported_as_the_python_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            shadow = Path(tmp) / 'shadow'
            shadow.mkdir()
            (shadow / 'tomllib.py').write_text('raise ImportError("simulated Python 3.10")\n')
            settings = Path(tmp) / 'config.toml'
            settings.write_text('[sandbox]\nmode = "workspace-write"\n')
            env = {**os.environ, 'PYTHONPATH': str(shadow)}
            proc = subprocess.run([sys.executable, str(AUDIT), '--provider', 'codex', '--settings', str(settings)],
                                  capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        receipt = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(receipt['error'], 'python_3_11_required')
        self.assertNotIn('settings_unreadable_or_invalid', proc.stdout)


if __name__ == '__main__':
    unittest.main()
