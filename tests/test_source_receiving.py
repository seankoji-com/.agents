"""Receiver updates and crash recovery use local Git objects, never the network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from source_runtime import cli, discovery, pins, transaction
from source_runtime.io import Paths, SourceError, canonical, git, load, read, source_lock, tracked_clean, write_json


class ReceivingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.box = Path(temporary.name).resolve()
        self.home = self.box/'home'
        self.home.mkdir()
        environment = patch.dict(os.environ,{'HOME':str(self.home),'PATH':os.environ.get('PATH',os.defpath)},clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.paths = Paths(self.home)
        self.source = self.home/'.agents'
        self.source.mkdir()
        git(self.source,'init','-q','-b','main')
        self.put('.agents-source.json',canonical({'schema_version':1,'repository_id':'1411719736',
            'bootstrap_protocol':1,'required_skills':['demo']}))
        self.body = ('---\nname: demo\ndescription: Fixture\nmetadata:\n  agents-bootstrap: "1"\n---\n'
            '"$HOME/.local/bin/agents" start demo\nRead pinned SKILL.md before substantive work. Version one.\n')
        self.put('skills/demo/SKILL.md',self.body)
        self.put('skills/demo/helper.py','print("one")\n')
        self.put('discovery.json',canonical({'schema_version':1,'providers':[
            {'id':'fixture','registration':'link','root':'.fixture/skills'}]}))
        self.put('scripts/agents_bootstrap.py',(ROOT/'scripts/agents_bootstrap.py').read_bytes())
        shutil.copytree(ROOT/'scripts/source_runtime',self.source/'scripts/source_runtime',
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        self.old = self.commit('old')
        git(self.source,'remote','add','origin','https://github.com/seankoji-com/.agents.git')
        git(self.source,'update-ref','refs/remotes/origin/main',self.old)
        write_json(self.paths.control/'profile.json',{'schema_version':1,'profile':'receiver',
            'source_root':str(self.source),'origin':'https://github.com/seankoji-com/.agents.git',
            'branch':'main','receive_enabled':False})
        selected = pins.capture_receiver(self.paths,self.source,self.old)
        self.old_active = {'schema_version':1,'commit':self.old,'pin':selected['pin']}
        write_json(self.paths.control/'active.json',self.old_active)
        write_json(self.paths.control/'validated-pins.json',{selected['pin']:self.old_active})
        discovery.apply(self.paths,discovery.plan(self.paths,self.source,self.source))
        self.put('skills/demo/SKILL.md',self.body.replace('Version one','Version two'))
        self.put('skills/demo/helper.py','print("two")\n')
        self.put('skills/demo/new.txt','new asset\n')
        self.new = self.commit('new')
        # Test fixture setup only. Production updater never checks out/resets.
        git(self.source,'checkout','-q',self.old,'--','.')
        git(self.source,'update-ref','refs/heads/main',self.old,self.new)
        git(self.source,'read-tree',self.old)
        extra = self.source/'skills/demo/new.txt'
        if extra.exists():
            extra.unlink()

    def put(self,name,value):
        file = self.source/name
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(value if isinstance(value,bytes) else value.encode())
        return file

    def commit(self,message):
        git(self.source,'add','.')
        git(self.source,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm',message)
        return transaction.oid(self.source,'HEAD')

    def fetch(self,root):
        git(root,'update-ref','refs/remotes/origin/main',self.new)

    def run_sync(self,**kwargs):
        return transaction.execute(self.paths,'sync',fetcher=self.fetch,**kwargs)

    def interrupt(self,target):
        def hook(phase):
            if phase == target:
                raise RuntimeError('simulated crash at '+target)
        with self.assertRaisesRegex(RuntimeError,'simulated crash'):
            self.run_sync(hook=hook)

    def test_exact_commit_success_preserves_foreign_untracked_skill_and_old_pin(self):
        foreign = self.put('skills/foreign/SKILL.md','Owner prose without portable metadata\n')
        result = self.run_sync()
        self.assertEqual(result['active']['commit'],self.new)
        self.assertEqual(foreign.read_text(),'Owner prose without portable metadata\n')
        self.assertEqual(git(self.source,'diff','HEAD','--').stdout,b'')
        self.assertEqual(transaction.index_tree(self.source),transaction.oid(self.source,self.new+'^{tree}'))
        self.assertIn('Version two',Path(cli.start(self.paths,'demo')['skill_file']).read_text())
        self.assertIn('Version one',Path(cli.start(self.paths,'demo',pin=self.old_active['pin'])['skill_file']).read_text())

    def test_tracked_clean_sees_bytes_mode_deletion_and_links_like_git_diff(self):
        helper = self.source/'skills/demo/helper.py'
        original = helper.read_bytes()
        self.assertTrue(tracked_clean(self.source))
        def link():
            helper.unlink()
            helper.symlink_to('helper.txt')
        for change in (lambda: helper.chmod(0o755), helper.unlink, link, lambda: helper.write_bytes(b'print("one")\r\n')):
            change()
            self.assertFalse(tracked_clean(self.source))
            helper.unlink(missing_ok=True)
            helper.write_bytes(original)
            helper.chmod(0o644)
            self.assertTrue(tracked_clean(self.source))
        demo = self.source/'skills/demo'
        demo.rename(self.box/'moved')
        demo.symlink_to(self.box/'moved',target_is_directory=True)
        self.assertFalse(tracked_clean(self.source))

    def test_dirty_and_staged_source_refuse_without_fetch(self):
        self.put('skills/demo/helper.py','owner edit\n')
        with patch.object(transaction,'prepare') as prepared:
            with self.assertRaisesRegex(SourceError,'dirty'):
                self.run_sync()
            prepared.assert_not_called()
        git(self.source,'add','.')
        with self.assertRaisesRegex(SourceError,'staged'):
            self.run_sync()
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)

    def test_empty_intent_to_add_entry_refuses_and_keeps_its_index_entry(self):
        # Its index blob is the empty blob, so the raw-byte check alone accepts it.
        self.put('skills/demo/owner-empty.txt','')
        git(self.source,'add','-N','skills/demo/owner-empty.txt')
        self.assertTrue(tracked_clean(self.source))
        with self.assertRaisesRegex(SourceError,'staged'):
            self.run_sync()
        self.assertIn(b'skills/demo/owner-empty.txt',git(self.source,'ls-files','-z').stdout)
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)

    def test_candidate_untracked_collision_and_alias_collision_preserve_both(self):
        collision = self.put('skills/demo/new.txt','owner file\n')
        with self.assertRaisesRegex(SourceError,'collision'):
            self.run_sync()
        self.assertEqual(collision.read_text(),'owner file\n')
        collision.unlink()
        link = self.home/'.fixture/skills/demo'
        link.unlink()
        link.mkdir()
        (link/'custom.txt').write_text('owner native skill')
        with self.assertRaisesRegex(SourceError,'collision'):
            self.run_sync()
        self.assertEqual((link/'custom.txt').read_text(),'owner native skill')
        self.assertEqual(transaction.oid(self.source,'HEAD'),self.old)

    def test_crash_at_each_publication_phase_recovers_exactly(self):
        phases = ['prepared','applying','file:0','files','index','ref','links','active']
        # Every iteration constructs a separate home; no recovery is inferred.
        for phase in phases:
            with self.subTest(phase=phase):
                if phase != phases[0]:
                    self.doCleanups()
                    self.setUp()
                self.interrupt(phase)
                with self.assertRaisesRegex(SourceError,'pending recovery'):
                    cli.start(self.paths,'demo')
                self.assertIn('Version one',Path(cli.start(self.paths,'demo',pin=self.old_active['pin'])['skill_file']).read_text())
                result = transaction.execute(self.paths,'recover')
                self.assertEqual(result['active']['commit'],self.new)
                self.assertFalse(transaction.pending(self.paths))
                self.assertIn('Version two',Path(cli.start(self.paths,'demo')['skill_file']).read_text())

    def test_recovery_stops_on_owner_edit_and_preserves_every_other_path(self):
        self.interrupt('files')
        file = self.put('skills/demo/helper.py','owner edit after crash\n')
        before = {p:read(p) for p in (self.source/'skills/demo').rglob('*') if p.is_file()}
        with self.assertRaisesRegex(SourceError,'owner edit'):
            transaction.execute(self.paths,'recover')
        self.assertEqual(before,{p:read(p) for p in before})
        self.assertEqual(file.read_text(),'owner edit after crash\n')
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)

    def test_recorded_restore_restores_only_exact_transaction_bytes(self):
        self.interrupt('ref')
        result = transaction.execute(self.paths,'recover',restore=True)
        self.assertEqual(result['status'],'restored')
        self.assertEqual(transaction.oid(self.source,'HEAD'),self.old)
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)
        self.assertFalse((self.source/'skills/demo/new.txt').exists())
        self.assertEqual(git(self.source,'diff','HEAD','--').stdout,b'')

    def test_manual_rollback_stays_selected_until_explicit_follow_source(self):
        self.run_sync()
        transaction.execute(self.paths,'rollback',self.old_active['pin'])
        self.assertEqual(self.run_sync()['status'],'held')
        self.assertEqual(transaction.oid(self.source,'HEAD'),self.new)
        self.assertIn('Version one',Path(cli.start(self.paths,'demo')['skill_file']).read_text())
        transaction.execute(self.paths,'rollback','follow-source')
        # Same source HEAD deliberately revalidates/reactivates after a hold.
        self.assertEqual(self.run_sync()['active']['commit'],self.new)

    def test_offline_auth_and_timeout_leave_source_runtime_unchanged(self):
        for message in ('offline','authentication failed','bounded fetch timeout'):
            with self.subTest(message=message):
                def failure(root):
                    raise SourceError(message)
                with self.assertRaisesRegex(SourceError,message):
                    transaction.execute(self.paths,'sync',fetcher=failure)
                self.assertEqual(transaction.oid(self.source,'HEAD'),self.old)
                self.assertEqual(load(self.paths.control/'active.json'),self.old_active)
                self.assertFalse(transaction.pending(self.paths))

    def test_failed_candidate_updater_preserves_active_updater_and_source(self):
        before = {p:read(p) for p in self.paths.control.glob('*.json')}
        with patch.object(transaction.bootstrap,'prepare',side_effect=SourceError('successor self-test failed')):
            with self.assertRaisesRegex(SourceError,'successor self-test'):
                self.run_sync()
        for file,data in before.items():
            self.assertEqual(read(file),data)
        self.assertEqual(transaction.oid(self.source,'HEAD'),self.old)

    def test_wrong_origin_unsupported_git_and_lock_contention_refuse(self):
        git(self.source,'remote','set-url','origin','https://example.invalid/other.git')
        with self.assertRaisesRegex(SourceError,'origin differs'):
            self.run_sync()
        git(self.source,'remote','set-url','origin','https://github.com/seankoji-com/.agents.git')
        git(self.source,'config','core.autocrlf','true')
        with self.assertRaisesRegex(SourceError,'unsupported Git'):
            self.run_sync()
        with source_lock(self.paths):
            with self.assertRaisesRegex(SourceError,'update in progress'):
                with source_lock(self.paths,timeout=0.05):
                    self.fail('second lock acquired')

    def test_selected_filters_never_run_during_receiving(self):
        # git-lfs installs filter.lfs.* globally. Names that read like inactive attribute
        # states and a path only the incoming commit adds must stay inert as well.
        marker = self.box/'filter-ran'
        command = 'sh -c "echo %f >> ' + str(marker) + '; cat"'
        for name in ('lfs','unset','unspecified','probe'):
            git(self.source,'config','--global','filter.'+name+'.clean',command)
            git(self.source,'config','--global','filter.'+name+'.smudge',command)
        attributes = self.home/'.config/git/attributes'
        attributes.parent.mkdir(parents=True)
        attributes.write_text('*.json filter=lfs\n*.py filter=unset\n*.md filter=unspecified\n'
                              'skills/demo/new.txt filter=probe\n')
        self.assertEqual(self.run_sync()['active']['commit'],self.new)
        self.assertFalse(marker.exists())
        # The fixture is live: an ordinary worktree diff on the unstat'd index runs them.
        git(self.source,'read-tree',self.new)
        git(self.source,'diff','--quiet',check=False)
        self.assertIn('skills/demo/new.txt',marker.read_text())

    def test_index_flags_and_executable_checkout_hooks_are_refused_without_disabling_them(self):
        file = 'skills/demo/helper.py'
        git(self.source,'update-index','--assume-unchanged',file)
        with self.assertRaisesRegex(SourceError,'index flags'):
            self.run_sync()
        git(self.source,'update-index','--no-assume-unchanged',file)
        hook = self.source/'.git/hooks/reference-transaction'
        hook.write_text('#!/bin/sh\nprintf executed > "'+str(self.home/'hook-executed')+'"\n')
        hook.chmod(0o755)
        with self.assertRaisesRegex(SourceError,'executable Git hook'):
            self.run_sync()
        self.assertFalse((self.home/'hook-executed').exists())
        self.assertTrue(hook.stat().st_mode & 0o111)
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)

    def test_ahead_diverged_and_rewritten_upstream_are_not_applied(self):
        self.put('owner.txt','local commit\n')
        local = self.commit('local divergent work')
        with self.assertRaisesRegex(SourceError,'ahead or diverged'):
            self.run_sync()
        self.assertEqual(transaction.oid(self.source,'HEAD'),local)
        # A fetch that rewinds an already observed upstream is rejected.
        git(self.source,'update-ref','refs/heads/main',self.old,local)
        git(self.source,'checkout','-q',self.old,'--','.')
        git(self.source,'read-tree',self.old)
        (self.source/'owner.txt').unlink()
        git(self.source,'update-ref','refs/remotes/origin/main',self.new)
        def rewrite(root):
            git(root,'update-ref','refs/remotes/origin/main',self.old)
        with self.assertRaisesRegex(SourceError,'rewritten'):
            transaction.execute(self.paths,'sync',fetcher=rewrite)
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)

    def test_source_change_during_fetch_or_apply_never_overwrites_owner_bytes(self):
        def edit_during_fetch(root):
            self.fetch(root)
            self.put('skills/demo/helper.py','fetch-time owner edit\n')
        with self.assertRaisesRegex(SourceError,'dirty'):
            transaction.execute(self.paths,'sync',fetcher=edit_during_fetch)
        self.assertEqual((self.source/'skills/demo/helper.py').read_text(),'fetch-time owner edit\n')
        self.put('skills/demo/helper.py','print("one")\n')
        def edit_during_apply(phase):
            if phase == 'applying':
                self.put('skills/demo/helper.py','apply-time owner edit\n')
        with self.assertRaisesRegex(SourceError,'source changed during apply'):
            self.run_sync(hook=edit_during_apply)
        self.assertEqual((self.source/'skills/demo/helper.py').read_text(),'apply-time owner edit\n')
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)

    def test_start_waits_for_apply_and_loads_one_complete_revision(self):
        entered, release, finished = threading.Event(),threading.Event(),threading.Event()
        results, errors = [],[]
        def hook(phase):
            if phase == 'files':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test did not release updater')
        def update():
            try:
                self.run_sync(hook=hook)
            except Exception as exc:
                errors.append(exc)
        def start():
            try:
                results.append(cli.start(self.paths,'demo'))
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()
        updater = threading.Thread(target=update)
        updater.start()
        reader = None
        try:
            self.assertTrue(entered.wait(5))
            reader = threading.Thread(target=start)
            reader.start()
            self.assertFalse(finished.wait(0.1))
        finally:
            release.set()
            updater.join(5)
            if reader is not None:
                reader.join(5)
        self.assertFalse(updater.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(errors,[])
        self.assertEqual(len(results),1)
        package = Path(results[0]['package_root'])
        self.assertIn('Version two',(package/'SKILL.md').read_text())
        self.assertEqual((package/'helper.py').read_text(),'print("two")\n')

    def test_new_removed_aliases_and_custom_picker_files_are_preserved(self):
        staged = pins.verify(self.paths,self.old_active['pin'])
        original = self.home/'.fixture/skills/demo'
        self.assertTrue(original.is_symlink())
        # Registry ownership permits removing a link only while it is exact.
        next_source = self.box/'candidate'
        shutil.copytree(staged,next_source)
        next_source.chmod(0o755)
        file = next_source/'skills/demo/SKILL.md'
        file.chmod(0o644)
        (next_source/'skills').chmod(0o755)
        moved = next_source/'skills/renamed'
        (next_source/'skills/demo').rename(moved)
        (moved/'SKILL.md').write_text(self.body.replace('demo','renamed'))
        identity = load(next_source/'.agents-source.json')
        identity['required_skills'] = ['renamed']
        (next_source/'.agents-source.json').chmod(0o644)
        write_json(next_source/'.agents-source.json',identity)
        prepared = discovery.plan(self.paths,next_source,self.source)
        discovery.apply(self.paths,prepared)
        self.assertFalse(original.is_symlink())
        self.assertEqual(os.readlink(self.home/'.fixture/skills/renamed'),str(self.source/'skills/renamed'))
        self.assertFalse((self.source/'skills/demo/agents/openai.yaml').exists())

    def test_incompatible_or_malformed_candidate_preserves_source_and_runtime(self):
        self.put('.agents-source.json',b'{"schema_version":1,"bootstrap_protocol":99}\n')
        self.new = self.commit('incompatible candidate')
        git(self.source,'checkout','-q',self.old,'--','.')
        git(self.source,'update-ref','refs/heads/main',self.old,self.new)
        git(self.source,'read-tree',self.old)
        extra = self.source/'skills/demo/new.txt'
        if extra.exists():
            extra.unlink()
        with self.assertRaisesRegex(SourceError,'bootstrap protocol'):
            self.run_sync()
        self.assertEqual(transaction.oid(self.source,'HEAD'),self.old)
        self.assertEqual(load(self.paths.control/'active.json'),self.old_active)
        self.assertFalse(transaction.pending(self.paths))


if __name__ == '__main__':
    unittest.main()
