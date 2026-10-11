"""The frozen benchmark harness in bench/: dataset, Task A checks, token parser, audit."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / 'bench'
for sub in ('checks', 'tools'):
    sys.path.insert(0, str(BENCH / sub))

import audit  # noqa: E402
import prepare_workspace  # noqa: E402
import task_a  # noqa: E402
import tokens  # noqa: E402

DATA = BENCH / 'fixtures' / 'task_a' / 'workspace' / 'data'
TRANSCRIPTS = BENCH / 'tools' / 'fixtures'


def reference_output(out: Path) -> dict:
    """A minimal output that meets the Task A contract, built from the expected answer."""
    want = task_a.expected(DATA)
    records = json.loads((DATA / 'prices.json').read_text())['records']
    geo = {s['id']: s for s in json.loads((DATA / 'stations.json').read_text())['stations']}
    stations = []
    for sid in want['in_radius']:
        history = sorted(({'recorded_at': r['recorded_at'], 'price_cpl': r['price_cpl']} for r in records
                          if r['station_id'] == sid and r['fuel'] == 'E10'), key=lambda r: r['recorded_at'])
        stations.append({'id': sid, 'name': geo[sid]['name'], 'lat': geo[sid]['lat'], 'lon': geo[sid]['lon'],
                         'distance_km': want['distance_km'][sid], 'listed_price_cpl': want['listed_price_cpl'][sid],
                         'history': history})
    data = {'recommendation': {'station_id': want['cheapest']}, 'stations': stations,
            'overall_history': want['overall_history']}
    shutil.copytree(DATA.parent / 'vendor' / 'leaflet', out / 'vendor' / 'leaflet')
    (out / 'data.json').write_text(json.dumps(data))
    (out / 'data.js').write_text('window.DATA = ' + json.dumps(data) + ';\n')
    (out / 'index.html').write_text(
        '<link rel="stylesheet" href="vendor/leaflet/leaflet.css">\n'
        '<script src="data.js"></script>\n'
        '<script src="./vendor/leaflet/leaflet.js"></script>\n'
        f'<p data-recommended-station="{want["cheapest"]}">Buy here</p>\n'
        "<script>L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', "
        "{attribution: '&copy; OpenStreetMap contributors'});</script>\n")
    return data


class DatasetTest(unittest.TestCase):
    def test_generator_reproduces_committed_data(self):
        result = subprocess.run([sys.executable, str(BENCH / 'fixtures/task_a/generate.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dataset_meets_the_frozen_shape(self):
        want = task_a.expected(DATA)
        self.assertEqual(want, json.loads((BENCH / 'fixtures/task_a/expected.json').read_text()))
        self.assertTrue(18 <= len(want['in_radius']) <= 22)
        self.assertGreaterEqual(len(want['out_of_radius']), 3)
        near_edge = [sid for sid, km in want['distance_km'].items() if abs(km - task_a.RADIUS_KM) <= 0.05]
        self.assertEqual(len(near_edge), 1)
        prices = sorted(want['listed_price_cpl'].values())
        self.assertLess(prices[0], prices[1], 'the cheapest in-radius station must be unique')
        # Traps: an out-of-radius station and a non-E10 record are cheaper than the answer.
        records = json.loads((DATA / 'prices.json').read_text())['records']
        winner = want['listed_price_cpl'][want['cheapest']]
        self.assertTrue(any(r['station_id'] in want['out_of_radius'] and r['price_cpl'] < winner for r in records))
        self.assertTrue(any(r['fuel'] != 'E10' and r['price_cpl'] < winner for r in records))


class TaskACheckTest(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out)
        self.data = reference_output(self.out)

    def failing(self):
        return {r['check'] for r in task_a.check(self.out, DATA) if r['required'] and not r['ok']}

    def test_reference_output_passes_every_check(self):
        results = task_a.check(self.out, DATA)
        self.assertEqual([r for r in results if not r['ok']], [])

    def test_cdn_leaflet_fails(self):
        page = self.out / 'index.html'
        page.write_text(page.read_text().replace('./vendor/leaflet/leaflet.js',
                                                 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'))
        self.assertEqual(self.failing(), {'leaflet_vendored'})

    def test_modified_vendored_leaflet_fails(self):
        (self.out / 'vendor/leaflet/leaflet.js').write_text('// not leaflet')
        self.assertEqual(self.failing(), {'leaflet_vendored'})

    def test_out_of_radius_id_anywhere_fails(self):
        (self.out / 'extra.js').write_text('// excluded: STN-0901')
        self.assertEqual(self.failing(), {'station_ids'})

    def test_missing_station_fails_ids_and_series(self):
        self.data['stations'].pop()
        (self.out / 'data.json').write_text(json.dumps(self.data))
        self.assertEqual(self.failing(), {'station_ids', 'price_series'})

    def test_missing_overall_history_fails(self):
        del self.data['overall_history']
        (self.out / 'data.json').write_text(json.dumps(self.data))
        self.assertEqual(self.failing(), {'price_series'})

    def test_station_ids_must_reach_the_page(self):
        (self.out / 'data.js').unlink()
        self.assertEqual(self.failing(), {'station_ids'})

    def test_missing_leaflet_assets_fail(self):
        (self.out / 'vendor/leaflet/LICENSE').unlink()
        shutil.rmtree(self.out / 'vendor/leaflet/images')
        self.assertEqual(self.failing(), {'leaflet_vendored'})

    def test_malformed_data_json_fails_without_raising(self):
        for stations in (None, 'x', [None, 3]):
            with self.subTest(stations=stations):
                self.data['stations'] = stations
                (self.out / 'data.json').write_text(json.dumps(self.data))
                self.assertEqual(self.failing(), {'station_ids', 'price_series'})

    def test_wrong_recommendation_fails(self):
        self.data['recommendation']['station_id'] = 'STN-0021'
        (self.out / 'data.json').write_text(json.dumps(self.data))
        self.assertEqual(self.failing(), {'recommendation'})

    def test_page_marker_must_agree(self):
        page = self.out / 'index.html'
        page.write_text(page.read_text() + '<li data-recommended-station="STN-0021"></li>')
        self.assertEqual(self.failing(), {'recommendation'})

    def test_cli_exit_status(self):
        script = str(BENCH / 'checks/task_a.py')
        self.assertEqual(subprocess.run([sys.executable, script, str(self.out)], capture_output=True).returncode, 0)
        (self.out / 'data.json').unlink()
        self.assertEqual(subprocess.run([sys.executable, script, str(self.out)], capture_output=True).returncode, 1)


class TokenParserTest(unittest.TestCase):
    def test_counts_each_message_once_and_keeps_cache_read_apart(self):
        result = tokens.parse_session(TRANSCRIPTS / 'transcript_complete.jsonl')
        opus = result['by_model']['claude-opus-5-5']
        self.assertEqual(opus['messages'], 3)
        self.assertEqual((opus['input_tokens'], opus['output_tokens'], opus['cache_creation_input_tokens']),
                         (15, 102, 1200))
        self.assertEqual(opus['counted'], 1317)
        self.assertEqual(opus['cache_read'], 1500)
        self.assertEqual(result['by_model']['claude-haiku-5-5']['counted'], 3)
        self.assertNotIn('<synthetic>', result['by_model'])
        self.assertTrue(result['first_prompt_prefix'].startswith(tokens.PARENT_PROMPT_PREFIX))
        self.assertEqual(tokens.wallclock_seconds(result['started_at'], result['ended_at']), 60.0)

    def test_missing_usage_is_unknown_not_zero(self):
        opus = tokens.parse_session(TRANSCRIPTS / 'transcript_missing_usage.jsonl')['by_model']['claude-opus-5-5']
        self.assertIsNone(opus['cache_creation_input_tokens'])
        self.assertIsNone(opus['counted'])
        self.assertEqual(opus['cache_read'], 9)

    def test_run_attributes_parent_and_descendants_by_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / 'ws.a-1'
            project = Path(tmp) / 'projects' / tokens.encode_project(workspace)
            (project / 'child-session' / 'subagents').mkdir(parents=True)
            shutil.copy(TRANSCRIPTS / 'transcript_complete.jsonl', project / 'parent.jsonl')
            child = project / 'child.jsonl'
            child.write_text((TRANSCRIPTS / 'transcript_complete.jsonl').read_text().replace(
                'Follow the installed imps entry at', 'You are a delegated worker; see'))
            shutil.copy(child, project / 'child-session' / 'subagents' / 'agent-1.jsonl')
            result = tokens.parse_run(workspace, Path(tmp) / 'projects')
            self.assertEqual(result['parent']['file'], 'parent.jsonl')
            self.assertEqual(result['parent_opus'], {'counted': 1317, 'cache_read': 1500,
                                                     'other_models_in_parent': ['claude-haiku-5-5']})
            self.assertEqual(sorted(d['kind'] for d in result['descendants']), ['claude-session', 'claude-subagent'])
            missing = tokens.parse_run(Path(tmp) / 'other', Path(tmp) / 'projects')
            self.assertFalse(missing['project_dir_found'])


class AuditTest(unittest.TestCase):
    def test_flags_tool_call_paths_and_upstream_but_not_tool_results(self):
        findings = audit.audit_file(TRANSCRIPTS / 'transcript_complete.jsonl', 'b',
                                    ['/bench/workspace', '/bench/package'], '/bench/harness', '/bench/home')
        void = [f.get('path') or f.get('reason') for f in findings if f['level'] == 'void']
        self.assertIn('/outside/dir', void)
        self.assertIn('upstream repository reference', void)
        self.assertNotIn('/bench/workspace', void)
        self.assertFalse(any('/elsewhere' in str(f) for f in findings))
        with tempfile.TemporaryDirectory() as tmp:
            codex = Path(tmp) / 'rollout.jsonl'
            codex.write_text(json.dumps({'type': 'response_item', 'payload': {
                'type': 'function_call', 'name': 'exec_command',
                'arguments': json.dumps({'cmd': 'cat ../outside && cat /etc/hosts'})}}) + '\n')
            levels = {(f['level'], f.get('path') or f.get('reason')) for f in
                      audit.audit_file(codex, 'a', ['/bench/workspace'], '/bench/harness', '/bench/home')}
            self.assertIn(('review', 'relative parent path in command'), levels)
            self.assertIn(('review', '/etc/hosts'), levels)
            missing = audit.audit(Path(tmp) / 'ws', Path(tmp) / 'pkg', 'a', Path(tmp) / 'projects', None)
            self.assertEqual(missing['void'], 1)
        task_a_findings = audit.audit_file(TRANSCRIPTS / 'transcript_complete.jsonl', 'a',
                                           ['/bench/workspace'], '/bench/harness', '/bench/home')
        self.assertFalse(any(f.get('reason', '').startswith('upstream') for f in task_a_findings))


class RecordingTest(unittest.TestCase):
    def test_prepared_task_a_workspace_is_reproducible_and_summarised(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            first = prepare_workspace.prepare('a', tmp / 'ws1', ROOT)
            second = prepare_workspace.prepare('a', tmp / 'ws2', ROOT)
            self.assertEqual(first['head'], second['head'])
            workspace = tmp / 'ws1'
            (workspace / '.bench-state').mkdir()
            (workspace / '.bench-state' / 'run.json').write_text('{}')
            reference_output(workspace / 'out')
            (workspace / 'out' / 'data.js').write_text(f'// built in {workspace}\n' +
                                                       (workspace / 'out' / 'data.js').read_text())
            subprocess.run(['git', 'add', 'out'], cwd=workspace, check=True)
            subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'out'],
                           cwd=workspace, check=True)
            self.assertEqual(subprocess.run(['git', 'status', '--porcelain'], cwd=workspace, capture_output=True,
                                            text=True).stdout, '')
            project = tmp / 'projects' / tokens.encode_project(workspace)
            project.mkdir(parents=True)
            shutil.copy(TRANSCRIPTS / 'transcript_complete.jsonl', project / 'parent.jsonl')
            thread = tmp / 'thread.json'
            thread.write_text(json.dumps({'outcome': 'completed', 'started_at': '2026-10-11T00:00:00Z',
                                          'ended_at': '2026-10-11T00:10:00Z',
                                          'final_message': f'Done in {workspace}/out'}))
            result = subprocess.run([sys.executable, str(BENCH / 'tools/summarise.py'), '--version', 'old',
                                     '--slot', 'a1', '--attempt', '1', '--workspace', str(workspace),
                                     '--package', str(tmp / 'pkg'), '--thread-id', 'T', '--thread-json', str(thread),
                                     '--private', str(tmp / 'private'), '--runs-dir', str(tmp / 'runs'),
                                     '--projects-dir', str(tmp / 'projects'), '--codex-dir', str(tmp / 'codex')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((tmp / 'runs/old/a1/summary.json').read_text())
            self.assertEqual(summary['parent_opus_tokens']['counted'], 1317)
            self.assertEqual(summary['wallclock_seconds']['thread'], 600.0)
            self.assertTrue(all(r['ok'] for r in summary['result']['task_a_checks']))
            self.assertIn('parent.jsonl', summary['raw_sha256'])
            self.assertTrue((tmp / 'runs/old/a1/output/out/index.html').is_file())
            self.assertEqual((tmp / 'runs/old/a1/report.md').read_text(), 'Done in <workspace>/out\n')
            self.assertTrue((tmp / 'private/runs/old/a1/attempt-1/transcripts/parent.jsonl').is_file())
            self.assertNotIn(str(tmp), (tmp / 'runs/old/a1/summary.json').read_text())
            self.assertNotIn(str(tmp), (tmp / 'runs/old/a1/output/out/data.js').read_text())


if __name__ == '__main__':
    unittest.main()
