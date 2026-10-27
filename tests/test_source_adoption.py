"""Populated-directory adoption, ownership and interrupted restart fixtures."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from source_runtime import adoption, cli, transaction
from source_runtime.io import SourceError, digest, git, load, read, write_json
import test_source_receiving as fixtures


class AdoptionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReceivingTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.paths = self.fixture.paths
        self.root = self.fixture.source
        self.donor = self.fixture.box/'reviewed-source'
        self.root.rename(self.donor)
        self.fixture.source = self.donor
        registry = load(self.donor/'discovery.json')
        registry['legacy_roots'] = ['.fixture/skills']
        write_json(self.donor/'discovery.json',registry)
        self.commit = self.fixture.commit('adoption registry')
        self.root.mkdir()
        legacy = self.root/'skills/t3-demo'
        legacy.mkdir(parents=True)
        body = b'Old generated adapter\n'
        (legacy/'SKILL.md').write_bytes(body)
        write_json(legacy/'.dotfiles-skill.json',{'schema_version':1,'name':'t3-demo','files':{'SKILL.md':digest(body)}})
        (self.paths.home/'.fixture/skills/t3-demo').symlink_to(legacy)
        (self.root/'agents/t3-plugins').mkdir(parents=True)
        (self.root/'agents/t3-plugins/legacy-registry.json').write_text('legacy runtime state\n')
        foreign = self.root/'skills/foreign'
        foreign.mkdir()
        (foreign/'SKILL.md').write_text('Foreign skill with its own format\n')
        config = load(self.paths.control/'profile.json')
        write_json(self.paths.control/'profile.json',{**config,'profile':'author','receive_enabled':False})

    def test_populated_adoption_preserves_foreign_and_exact_legacy_runtime(self):
        result = adoption.adopt(self.paths,self.donor)
        self.assertEqual(result['status'],'adopted')
        self.assertEqual(result['profile'],'author')
        self.assertFalse(result['receive_enabled'])
        self.assertEqual(transaction.oid(self.root,'HEAD'),self.commit)
        self.assertEqual(git(self.root,'diff','HEAD','--').stdout,b'')
        self.assertFalse((self.root/'skills/t3-demo').exists())
        self.assertFalse((self.paths.home/'.fixture/skills/t3-demo').is_symlink())
        self.assertTrue((self.paths.home/'.fixture/skills/demo').is_symlink())
        self.assertEqual((self.root/'skills/foreign/SKILL.md').read_text(),'Foreign skill with its own format\n')
        self.assertEqual((self.root/'agents/t3-plugins/legacy-registry.json').read_text(),'legacy runtime state\n')
        self.assertEqual(load(self.paths.control/'cutover.json')['phase'],'active')
        backup = Path(result['backup'])
        self.assertEqual((backup/'files/.agents/skills/t3-demo/SKILL.md').read_bytes(),b'Old generated adapter\n')
        self.assertTrue((backup/'restore-map.json').is_file())
        self.assertIn('Version one',Path(cli.start(self.paths,'demo')['skill_file']).read_text())

    def test_modified_or_custom_old_picker_stops_before_any_live_mutation(self):
        custom = self.root/'skills/t3-demo/agents/openai.yaml'
        custom.parent.mkdir()
        custom.write_text('owner custom picker\n')
        with self.assertRaisesRegex(SourceError,'custom old picker'):
            adoption.adopt(self.paths,self.donor)
        self.assertFalse((self.root/'.git').exists())
        self.assertFalse((self.paths.control/'cutover.json').exists())
        self.assertEqual(custom.read_text(),'owner custom picker\n')
        self.assertTrue((self.paths.home/'.fixture/skills/t3-demo').is_symlink())

    def test_owner_source_collision_stops_without_initializing_git(self):
        conflict = self.root/'scripts/agents_bootstrap.py'
        conflict.parent.mkdir()
        conflict.write_text('owner tool\n')
        with self.assertRaisesRegex(SourceError,'collision'):
            adoption.adopt(self.paths,self.donor)
        self.assertFalse((self.root/'.git').exists())
        self.assertEqual(conflict.read_text(),'owner tool\n')

    def test_custom_picker_in_exempt_skill_is_preserved_before_any_cutover(self):
        identity = load(self.donor/'.agents-source.json')
        identity['required_skills'].append('unslop')
        write_json(self.donor/'.agents-source.json',identity)
        source = self.donor/'skills/unslop/SKILL.md'
        source.parent.mkdir()
        source.write_text('---\nname: unslop\ndescription: Prose\nmetadata:\n  agents-bootstrap-exempt: "true"\n---\nProse.\n')
        self.fixture.commit('single-file prose source')
        custom = self.root/'skills/unslop/agents/openai.yaml'
        custom.parent.mkdir(parents=True)
        custom.write_text('owner picker\n')
        (custom.parent.parent/'SKILL.md').write_text('owner prose\n')
        with self.assertRaisesRegex(SourceError,'custom picker/helper'):
            adoption.adopt(self.paths,self.donor)
        self.assertEqual(custom.read_text(),'owner picker\n')
        self.assertFalse((self.root/'.git').exists())
        self.assertFalse((self.paths.control/'cutover.json').exists())

    def test_interrupted_adoption_is_pending_and_can_resume_exactly(self):
        def crash(phase):
            if phase == 'files':
                raise RuntimeError('simulated adoption crash')
        with self.assertRaisesRegex(RuntimeError,'adoption crash'):
            adoption.adopt(self.paths,self.donor,hook=crash)
        self.assertEqual(load(self.paths.control/'cutover.json')['phase'],'pending')
        with self.assertRaisesRegex(SourceError,'pending recovery'):
            cli.start(self.paths,'demo')
        result = adoption.adopt(self.paths)
        self.assertEqual(result['commit'],self.commit)
        self.assertEqual(load(self.paths.control/'cutover.json')['phase'],'active')
        self.assertFalse(transaction.pending(self.paths))

    def test_owner_staged_index_change_after_interruption_blocks_recovery(self):
        def crash(phase):
            if phase == 'ref':
                raise RuntimeError('simulated crash after ref publication')
        with self.assertRaises(RuntimeError):
            adoption.adopt(self.paths,self.donor,hook=crash)
        # Index-only owner work: staged content with no worktree file.
        blob = git(self.root,'hash-object','-w','--stdin',input=b'owner note\n').stdout.decode().strip()
        git(self.root,'update-index','--add','--cacheinfo','100644,'+blob+',owner-note.txt')
        with self.assertRaisesRegex(SourceError,'index holds owner changes'):
            adoption.adopt(self.paths)
        self.assertIn(b'owner-note.txt',git(self.root,'diff','--cached','--name-only').stdout)
        self.assertEqual(load(self.paths.control/'cutover.json')['phase'],'pending')
        git(self.root,'update-index','--force-remove','owner-note.txt')
        self.assertEqual(adoption.adopt(self.paths)['status'],'adopted')

    def test_owner_branch_switch_after_interruption_blocks_recovery(self):
        def crash(phase):
            if phase == 'ref':
                raise RuntimeError('simulated crash after ref publication')
        with self.assertRaises(RuntimeError):
            adoption.adopt(self.paths,self.donor,hook=crash)
        git(self.root,'symbolic-ref','HEAD','refs/heads/owner-work')
        with self.assertRaisesRegex(SourceError,'HEAD moved'):
            adoption.adopt(self.paths)
        self.assertEqual(git(self.root,'symbolic-ref','HEAD').stdout.strip(),b'refs/heads/owner-work')

    def test_owner_edit_after_interruption_is_preserved_and_blocks_recovery(self):
        def crash(phase):
            if phase == 'files':
                raise RuntimeError('simulated crash')
        with self.assertRaises(RuntimeError):
            adoption.adopt(self.paths,self.donor,hook=crash)
        helper = self.root/'skills/demo/helper.py'
        helper.write_text('owner recovery edit\n')
        with self.assertRaisesRegex(SourceError,'owner edit'):
            adoption.adopt(self.paths)
        self.assertEqual(helper.read_text(),'owner recovery edit\n')
        self.assertEqual(load(self.paths.control/'cutover.json')['phase'],'pending')


if __name__ == '__main__':
    unittest.main()
