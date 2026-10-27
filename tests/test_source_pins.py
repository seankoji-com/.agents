"""Local source coherence, installed resolver integrity and dirty-edit behavior."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from source_runtime import bootstrap, cli, layout, pins
from source_runtime.io import Paths, SourceError, canonical, git, load, read, write_json


def body(name='demo', exempt=False):
    metadata = '  agents-bootstrap-exempt: "true"' if exempt else '  agents-bootstrap: "1"'
    return ('---\nname: ' + name + '\ndescription: "Fixture skill"\nmetadata:\n' + metadata +
            '\n---\nRead the pinned SKILL.md and manifest after running only:\n'
            '"$HOME/.local/bin/agents" start ' + name + '\nFixture body v1.\n')


class SourcePinsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.box = Path(self.temp.name).resolve()
        self.home = self.box / 'home'
        self.home.mkdir()
        env = patch.dict(os.environ, {'HOME': str(self.home), 'PATH': os.environ.get('PATH', os.defpath)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.paths = Paths(self.home)
        self.source = self.home / '.agents'
        self.source.mkdir()
        git(self.source, 'init', '-q')
        self.put('.agents-source.json', canonical({'schema_version':1,'repository_id':'1411719736',
            'bootstrap_protocol':1,'required_skills':['demo','unslop'],'legacy_only_plugins':['elephant-goldfish']}))
        self.put('skills/demo/SKILL.md', body())
        self.put('skills/demo/scripts/helper.py', 'print("helper v1")\n')
        self.put('skills/unslop/SKILL.md', body('unslop', exempt=True))
        self.put('discovery.json',canonical({'schema_version':1,'providers':[
            {'id':'fixture','registration':'link','root':'.fixture/skills'}]}))
        git(self.source, 'add', '.')
        git(self.source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture')
        write_json(self.paths.control / 'profile.json', {'schema_version':1,'profile':'author',
            'source_root':str(self.source),'branch':'main','receive_enabled':False})

    def put(self, relative, value):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode())
        return path

    def test_dirty_body_helper_and_new_assets_change_next_run_but_not_old_pin(self):
        first = cli.start(self.paths, 'demo')
        old = Path(first['package_root'])
        self.put('skills/demo/SKILL.md', body().replace('body v1', 'body v2'))
        self.put('skills/demo/scripts/helper.py', 'print("helper v2")\n')
        self.put('skills/demo/assets/new.bin', b'new uncommitted asset')
        second = cli.start(self.paths, 'demo')
        self.assertNotEqual(first['pin'], second['pin'])
        self.assertIn('body v1', (old / 'SKILL.md').read_text())
        self.assertIn('helper v1', (old / 'scripts/helper.py').read_text())
        self.assertIn('body v2', Path(second['skill_file']).read_text())
        self.assertEqual((Path(second['package_root']) / 'assets/new.bin').read_bytes(), b'new uncommitted asset')
        resumed = cli.start(self.paths, 'demo', pin=first['pin'])
        self.assertEqual(resumed['package_root'], first['package_root'])
        self.assertEqual(resumed['pin'], first['pin'])

    def test_capture_rejects_unstable_bytes_without_publishing_any_pin(self):
        with self.assertRaisesRegex(SourceError, 'changed during capture'):
            pins.capture_author(self.paths, self.source,
                after_read=lambda: self.put('skills/demo/scripts/helper.py', 'print("raced")\n'))
        self.assertFalse(self.paths.snapshots.exists())

    def test_dirty_new_renamed_deleted_skill_discovery_and_old_pin_resume(self):
        def reconcile(*arguments):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main([*arguments,'discovery'],home=self.home),0)
            return json.loads(output.getvalue())
        self.put('skills/new-skill/SKILL.md',body('new-skill'))
        before = git(self.source,'status','--porcelain=v1').stdout
        reconcile()
        link = self.home/'.fixture/skills/new-skill'
        self.assertTrue(link.is_symlink())
        self.assertEqual(git(self.source,'status','--porcelain=v1').stdout,before)
        first = cli.start(self.paths,'new-skill')
        (self.source/'skills/new-skill').rename(self.source/'skills/renamed-skill')
        self.put('skills/renamed-skill/SKILL.md',body('renamed-skill'))
        reconcile()
        self.assertFalse(link.is_symlink())
        renamed = self.home/'.fixture/skills/renamed-skill'
        self.assertTrue(renamed.is_symlink())
        (self.source/'skills/renamed-skill/SKILL.md').unlink()
        (self.source/'skills/renamed-skill').rmdir()
        reconcile()
        self.assertFalse(renamed.is_symlink())
        resumed = cli.start(self.paths,'new-skill',pin=first['pin'])
        self.assertEqual(resumed['skill_file'],first['skill_file'])
        self.assertIn('name: new-skill',Path(resumed['skill_file']).read_text())

    def test_worktree_discovery_cannot_take_over_production_names(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--source',str(ROOT),'discovery'],home=self.home),2)
        self.assertFalse((self.paths.control/'discovery.json').exists())

    def test_same_content_deduplicates_and_operations_never_write_source(self):
        before = {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*')
                  if p.is_file() and '.git' not in p.relative_to(self.source).parts}
        a = cli.start(self.paths, 'demo')
        b = cli.start(self.paths, 'demo')
        self.assertEqual(a['pin'], b['pin'])
        after = {p.relative_to(self.source).as_posix(): p.read_bytes() for p in self.source.rglob('*')
                 if p.is_file() and '.git' not in p.relative_to(self.source).parts}
        self.assertEqual(before, after)
        self.assertEqual(git(self.source, 'status', '--porcelain').stdout, b'')

    def test_single_file_exemption_has_no_snapshot_or_start_receipt(self):
        result = cli.start(self.paths, 'unslop')
        self.assertTrue(result['bootstrap_exempt'])
        self.assertFalse(self.paths.snapshots.exists())
        self.assertFalse((self.paths.jobs / 'starts').exists())
        self.put('skills/unslop/helper.py', 'print("unexpected")\n')
        with self.assertRaisesRegex(SourceError, 'exactly one prose'):
            cli.start(self.paths, 'unslop')

    def test_job_path_correlates_every_recorded_package_identity(self):
        package = self.paths.packages / ('a' * 64) / 'imps' / '1.0.0'
        receipt = {'package_digest': 'p' * 64, 'installation_id': 'install-1',
                   'bundle_dir': str(self.box / 'bundle'), 'bundle_digest': 'b' * 64}
        write_json(package / 'install-manifest.json', receipt)
        job = self.box / 'job.json'
        materialized = {'package_root': str(package)}
        dependency = {'key': 'workflow', 'plugin': 'imps'}
        pin = {**receipt, 'package_dir': str(package)}
        envelopes = {'unsupported job schema_version': {'schema_version': 999},
                     'duplicate job dependency key': {'dependencies': [dependency, dependency]},
                     'pins are missing': {'dependencies': [dependency, {'key': 'other', 'plugin': 'plan'}]}}
        with patch.object(pins, 'materialize', return_value=materialized):
            for reason, change in envelopes.items():
                with self.subTest(envelope=reason):
                    write_json(job, {'schema_version': 1, 'dependencies': [dependency], 'pins': {'workflow': pin},
                                     **change})
                    with self.assertRaisesRegex(SourceError, reason):
                        cli.job_path(self.paths, job, 'imps')
            for field in (None, *receipt):
                with self.subTest(field=field):
                    pin = {**receipt, 'package_dir': str(package)}
                    if field:
                        pin[field] = 'wrong'
                    write_json(job, {'schema_version': 1, 'dependencies': [dependency],
                                     'pins': {'workflow': pin}})
                    if field is None:
                        self.assertEqual(cli.job_path(self.paths, job, 'imps'), materialized)
                    else:
                        with self.assertRaisesRegex(SourceError, 'job ' + field + ' differs'):
                            cli.job_path(self.paths, job, 'imps')

    def test_receiver_export_uses_git_objects_not_dirty_worktree(self):
        commit = git(self.source, 'rev-parse', 'HEAD').stdout.decode().strip()
        self.put('skills/demo/scripts/helper.py', 'print("partial checkout")\n')
        selected = pins.capture_receiver(self.paths, self.source, commit)
        pinned = pins.verify(self.paths, selected['pin'])
        self.assertIn('helper v1', (pinned / 'skills/demo/scripts/helper.py').read_text())
        self.assertEqual(selected['selected_commit'], commit)
        with self.assertRaisesRegex(SourceError, 'exact full commit'):
            pins.capture_receiver(self.paths, self.source, 'HEAD')

    def test_receiver_start_and_resume_keep_old_runtime_during_dirty_source(self):
        commit = git(self.source, 'rev-parse', 'HEAD').stdout.decode().strip()
        selected = pins.capture_receiver(self.paths, self.source, commit)
        config = load(self.paths.control / 'profile.json')
        write_json(self.paths.control / 'profile.json', {**config,'profile':'receiver'})
        write_json(self.paths.control / 'active.json', {'commit':commit,'pin':selected['pin']})
        self.put('skills/demo/SKILL.md', body().replace('body v1', 'partial source'))
        result = cli.start(self.paths, 'demo')
        self.assertIn('body v1', Path(result['skill_file']).read_text())
        write_json(self.paths.control / 'journal.json', {'phase':'applying'})
        with self.assertRaisesRegex(SourceError, 'pending recovery'):
            cli.start(self.paths, 'demo')
        resumed = cli.start(self.paths, 'demo', pin=selected['pin'])
        self.assertEqual(result['skill_file'], resumed['skill_file'])

    def test_pin_tampering_and_unexpected_bytecode_are_detected(self):
        selected = pins.capture_author(self.paths, self.source)
        source = pins.verify(self.paths, selected['pin'])
        helper = source / 'skills/demo/scripts/helper.py'
        helper.chmod(0o644)
        helper.write_text('print("tampered")\n')
        with self.assertRaisesRegex(SourceError, 'integrity failure'):
            pins.verify(self.paths, selected['pin'])
        helper.write_text('print("helper v1")\n')
        folder = helper.parent
        folder.chmod(0o755)
        (folder/'injected.pyc').write_bytes(b'unexpected executable input')
        with self.assertRaisesRegex(SourceError, 'integrity failure'):
            pins.verify(self.paths, selected['pin'])

    def test_noncolliding_foreign_skill_is_reported_but_never_captured(self):
        self.put('skills/foreign/SKILL.md','Owner skill with a different format\n')
        self.put('skills/foreign/.env','OWNER_FIXTURE=private\n')
        selected = pins.capture_author(self.paths,self.source)
        snapshot = pins.verify(self.paths,selected['pin'])
        self.assertFalse((snapshot/'skills/foreign').exists())
        self.assertIn('foreign',layout.validate(self.source)['foreign_skills'])
        self.assertEqual((self.source/'skills/foreign/.env').read_text(),'OWNER_FIXTURE=private\n')

    def test_source_symlinks_and_secret_named_assets_fail_closed(self):
        foreign = self.box / 'foreign.py'
        foreign.write_text('print("outside source")\n')
        link = self.source / 'skills/demo/scripts/linked.py'
        link.symlink_to(foreign)
        with self.assertRaisesRegex(SourceError, 'symlink'):
            pins.capture_author(self.paths, self.source)
        link.unlink()
        self.put('skills/demo/.env', 'FIXTURE_VALUE=not-a-secret\n')
        with self.assertRaisesRegex(SourceError, 'credential/runtime'):
            pins.capture_author(self.paths, self.source)

    def test_unknown_protocol_does_not_publish_a_pin(self):
        identity = load(self.source / '.agents-source.json')
        self.put('.agents-source.json', canonical({**identity,'bootstrap_protocol':99}))
        with self.assertRaisesRegex(SourceError, 'bootstrap protocol'):
            pins.capture_author(self.paths, self.source)
        self.assertEqual(list(self.paths.snapshots.glob('[0-9a-f]' * 64)), [])

    def test_manifest_and_pure_prose_metadata_constraints(self):
        with self.assertRaisesRegex(SourceError, 'duplicate frontmatter'):
            layout.frontmatter(b'---\nname: a\nname: b\ndescription: x\n---\nbody')
        with self.assertRaisesRegex(SourceError, 'name and description'):
            layout.frontmatter(b'---\nname: t3 Bad\ndescription: x\n---\nbody')
        with patch.dict(os.environ, {'XDG_STATE_HOME':'relative'}):
            with self.assertRaisesRegex(SourceError, 'absolute'):
                Paths(self.home)

    def test_real_workflow_materializes_exact_body_helpers_and_worker_definitions(self):
        selected = pins.capture_author(self.paths, ROOT)
        artifact = pins.materialize(self.paths, selected['pin'], 'imps')
        package = Path(artifact['package_root'])
        self.assertEqual((package / 'SKILL.md').read_bytes(), (ROOT / 'skills/imps/SKILL.md').read_bytes())
        self.assertEqual((package / 'entry.md').read_bytes(), (package / 'SKILL.md').read_bytes())
        self.assertEqual((package / 'shared/job_coordinator.py').read_bytes(), (ROOT / 'shared/job_coordinator.py').read_bytes())
        receipt = load(package / 'install-manifest.json')
        self.assertEqual((Path(receipt['bundle_dir']) / 'workers/reviewer.md').read_bytes(),
                         (ROOT / 'plugins/imps/agents/reviewer.md').read_bytes())
        body_file = package / 'SKILL.md'
        body_file.chmod(0o644)
        body_file.write_text('altered package')
        with self.assertRaises((SourceError, ValueError)):
            pins.materialize(self.paths, selected['pin'], 'imps')

    def test_installed_launcher_is_independent_and_rejects_runtime_corruption(self):
        installed = bootstrap.self_install(ROOT, self.paths, source=self.source)
        self.assertEqual(installed['profile'], 'author')
        self.assertFalse(installed['receive_enabled'])
        self.assertTrue(read(self.paths.launcher).startswith(('#!' + str(Path(sys.executable).resolve())).encode()))
        result = subprocess.run([str(self.paths.launcher), 'start', 'demo'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = load(self.paths.control / 'bootstrap-active.json')
        module = Path(active['installation']) / 'scripts/source_runtime/cli.py'
        module.chmod(0o644)
        module.write_text('raise RuntimeError("must never execute")\n')
        refused = subprocess.run([str(self.paths.launcher), 'status'], capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('integrity failure', refused.stderr)
        self.assertNotIn('must never execute', refused.stderr)

    def test_launcher_keeps_paths_that_contain_placeholder_words(self):
        home = self.box / 'HOME-CONTROL-INTERPRETER'
        home.mkdir()
        text = bootstrap.launcher_bytes(Paths(home), str(Path(sys.executable).resolve())).decode()
        compile(text, 'launcher', 'exec')
        self.assertIn(repr(str(home)), text)
        self.assertIn(repr(str(Paths(home).control / 'bootstrap-active.json')), text)

    def test_snapshot_with_a_special_file_is_refused(self):
        pin = cli.start(self.paths, 'demo')['pin']
        folder = self.paths.snapshots / pin / 'source' / 'skills/demo'
        folder.chmod(0o755)
        os.mkfifo(folder / 'unlisted.fifo')
        with self.assertRaisesRegex(SourceError, 'linked or special file'):
            pins.verify(self.paths, pin)

    def test_installed_launcher_refuses_a_linked_directory_before_importing(self):
        bootstrap.self_install(ROOT, self.paths, source=self.source)
        scripts = Path(load(self.paths.control / 'bootstrap-active.json')['installation']) / 'scripts'
        payload = self.box / 'payload'
        payload.mkdir()
        (payload / '__init__.py').write_text('raise SystemExit("UNVERIFIED_DIRECTORY_EXECUTED")\n')
        scripts.chmod(0o755)
        # `subprocess` shadows a standard module the runtime imports first.
        (scripts / 'subprocess').symlink_to(payload, target_is_directory=True)
        refused = subprocess.run([str(self.paths.launcher), 'status'], capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('linked or special bootstrap input', refused.stderr)
        self.assertNotIn('UNVERIFIED_DIRECTORY_EXECUTED', refused.stdout + refused.stderr)
        with self.assertRaisesRegex(SourceError, 'linked or special file'):
            bootstrap.prepare(self.paths, {name: value for name, value in pins.read_author(ROOT).items()})

    def test_failed_successor_self_test_preserves_previous_launcher_and_pointer(self):
        bootstrap.self_install(ROOT, self.paths, source=self.source)
        before = {file:read(file) for file in (self.paths.launcher,self.paths.control/'bootstrap-active.json',
                                             self.paths.control/'profile.json',self.paths.control/'launcher.json')}
        failure = subprocess.CompletedProcess([], 1, '', 'synthetic self-test failure')
        original = bootstrap.subprocess.run
        def candidate(argv, *args, **kwargs):
            return failure if argv[-1:] == ['self-test'] else original(argv, *args, **kwargs)
        with patch.object(bootstrap.subprocess, 'run', side_effect=candidate):
            with self.assertRaisesRegex(SourceError, 'previous installation retained'):
                bootstrap.self_install(ROOT, self.paths, source=self.source)
        self.assertEqual(before, {file:read(file) for file in before})

    def test_unrelated_launcher_is_never_overwritten(self):
        self.paths.launcher.parent.mkdir(parents=True)
        self.paths.launcher.write_text('operator executable\n')
        with self.assertRaisesRegex(SourceError, 'unrelated or modified'):
            bootstrap.self_install(ROOT, self.paths, source=self.source)
        self.assertEqual(self.paths.launcher.read_text(), 'operator executable\n')


if __name__ == '__main__':
    unittest.main()
