"""Installed plan publication uses fake gh only; no live GitHub or provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from shared import execution_agreement as agreements, model_selection as models
from tests.test_plan_workflow import PlanFixture
from tests.test_plan_review_installed_matrix import relocate
from tests.thinking_plan_review_fixtures import upfront_selection


class PlanPublication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = PlanFixture(Path(self.temp.name) / 'fixture')
        self.f.install()
        self.f.package, self.f.manifest = relocate(self.f.box,
            {'plan': (self.f.package, self.f.manifest)})['plan']
        self.scripts = self.f.package / 'scripts'
        self.root = self.f.box.private / 'plans'
        fakebin = self.f.box.base / 'fakebin'
        fakebin.mkdir()
        self.log = self.f.box.base / 'fake-gh.log'
        fake = fakebin / 'gh'
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['PLAN_FAKE_GH_LOG']).open('a') as out:
    out.write(json.dumps(args) + '\\n')
query = next((arg for arg in args if arg.startswith('query=')), '')
if 'createDiscussion' in query:
    result = {'data': {'createDiscussion': {'discussion': {'id': 'D12', 'number': 12,
        'url': 'https://github.com/example/project/discussions/12'}}}}
elif 'addDiscussionComment' in query:
    result = {'data': {'addDiscussionComment': {'comment': {
        'url': 'https://github.com/example/project/discussions/12#discussioncomment-1'}}}}
elif query:
    result = {'data': {'repository': {'id': 'R1', 'discussionCategories': {'nodes': [
        {'id': 'category-fixture', 'name': 'Ideas'}]}}}}
else:
    result = None
print(json.dumps(result) if result else 'https://github.com/example/project/issues/12')
''')
        fake.chmod(0o755)
        self.f.box.env.update(PATH=str(fakebin) + os.pathsep + self.f.box.env['PATH'],
                              PLAN_FAKE_GH_LOG=str(self.log))

    def topic(self, slug, actions, *, paths=None, category='category-fixture'):
        selected = deepcopy(upfront_selection(slug, plugin='plan', operation='plan', output_root='plans'))
        selected['agreement']['authority'][0]['actions'] = ['inspect', 'edit', 'test', 'dispatch', *actions]
        selected['agreement']['scope']['paths'] = paths or ['plans/' + slug + '/']
        selected['agreement']['destinations']['category_id'] = category
        selected['agreement'] = agreements.freeze(selected['agreement'], selected)
        selected = models.freeze(selected)
        self.f.command(self.scripts, self.root, slug, 'init', '--output-type', 'implementation',
            '--selection', self.f.box.payload(selected), '--request-reference', 'fixture:request:' + slug)
        (self.root / slug / 'handoff.md').write_text('Synthetic reviewed fixture brief.\n')
        (self.root / slug / 'discovery.md').write_text('Synthetic fixture discovery.\n')
        return self.root / slug / 'meta.json'

    def publish(self, *args, ok=True):
        result = self.f.box.run([sys.executable, self.scripts / 'gh_publish.py', '--root', self.root,
                                 *args], check=False)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        return result

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_issue_creation_and_post_need_the_stored_action_grant(self):
        meta = self.topic('no-grant', [])
        self.publish('ensure', 'no-grant', '--mode', 'issue', '--repo', 'example/project', ok=False)
        self.assertEqual(self.calls(), [])
        value = json.loads(meta.read_text())
        value['github'] = {'mode': 'issue', 'repo': 'example/project', 'number': 12,
                           'url': 'https://github.com/example/project/issues/12'}
        meta.write_text(json.dumps(value))
        self.publish('post', 'no-grant', 'handoff.md', ok=False)
        self.assertEqual(self.calls(), [])
        # Preparing a dry-run remains independent work and sends nothing.
        self.publish('post', 'no-grant', 'handoff.md', '--dry-run')
        self.assertEqual(self.calls(), [])

    def test_repository_and_content_scope_are_checked_before_writes(self):
        meta = self.topic('scoped', ['publish-issues'], paths=['plans/scoped/handoff.md'])
        self.publish('ensure', 'scoped', '--mode', 'issue', '--repo', 'other/project', ok=False)
        self.assertEqual(self.calls(), [])
        self.publish('ensure', 'scoped', '--mode', 'issue', '--repo', 'example/project')
        self.assertEqual(len(self.calls()), 1)
        before = meta.read_bytes()
        self.publish('post', 'scoped', 'discovery.md', ok=False)
        self.assertEqual(meta.read_bytes(), before)
        self.assertEqual(len(self.calls()), 1)
        self.publish('post', 'scoped', 'handoff.md')
        self.assertEqual(len(self.calls()), 2)
        self.publish('post', 'scoped', 'handoff.md')
        self.assertEqual(len(self.calls()), 2)  # unchanged continuation sends no duplicate

    def test_discussion_grant_and_exact_category_are_independent_obligations(self):
        self.topic('issue-only', ['publish-issues'])
        self.publish('ensure', 'issue-only', '--mode', 'discussion', '--repo', 'example/project', ok=False)
        self.assertEqual(self.calls(), [])
        self.topic('wrong-category', ['publish-discussion'], category='category-other')
        self.publish('ensure', 'wrong-category', '--mode', 'discussion', '--repo', 'example/project', ok=False)
        self.assertEqual(len(self.calls()), 1)
        self.assertFalse(any('mutation(' in arg for call in self.calls() for arg in call))
        self.topic('discussion', ['publish-discussion'])
        self.publish('ensure', 'discussion', '--mode', 'discussion', '--repo', 'example/project')
        self.publish('post', 'discussion', 'handoff.md')
        self.assertEqual(len(self.calls()), 4)

    def test_changed_or_legacy_admission_cannot_publish(self):
        meta = self.topic('tampered', ['publish-issues'])
        value = json.loads(meta.read_text())
        value['model_admission']['selection']['agreement']['target']['label'] = 'Unapproved change'
        meta.write_text(json.dumps(value))
        self.publish('ensure', 'tampered', '--mode', 'issue', '--repo', 'example/project', ok=False)
        self.assertEqual(self.calls(), [])
        value['model_admission'].pop('selection')
        meta.write_text(json.dumps(value))
        self.publish('ensure', 'tampered', '--mode', 'issue', '--repo', 'example/project', ok=False)
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
