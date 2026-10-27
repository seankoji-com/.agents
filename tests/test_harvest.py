"""Harvest approval and destination completion use fakes, never live GitHub."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
from harvest import check_approval, prepare, screen, verify_for_publication
from learning_store import Store, Unavailable

VERSION = '0.1.0+content.' + 'a' * 12


class HarvestTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.project = self.base / 'private-project'
        self.project.mkdir()
        self.env = dict(os.environ, HOME=str(self.base / 'home'), XDG_STATE_HOME=str(self.base / 'state'),
                        XDG_CONFIG_HOME=str(self.base / 'config'))
        self.store = Store(self.project, 'imps', VERSION, self.env)
        self.loaded = self.store.operate('write', {'entry': {'id': 'lesson', 'summary': 'Retain task handles',
                                                          'failure': 'A lost handle prevented cancellation'}})
        self.drafts = [dict(entry_id='lesson', destination=destination, title='Retain task handles',
                            body='Retain delegated task handles until cancellation is confirmed.')
                       for destination in ('upstream', 'agents')]

    def proposal(self, prepared, receipts):
        return {'expected': self.store.operate()['revision'], 'draft': prepared['draft'],
                'shown_digest': prepared['shown_digest'], 'owner_reply': 'approve ' + prepared['shown_digest'],
                'project_slug': 'public/example', 'receipts': receipts}

    def test_identifier_screen_positive_and_negative_fixtures(self):
        blocked = [
            'Read /var/private/config', 'Use C:\\Users\\owner\\config', 'Use D:/owner/file',
            'Read \\\\server\\share\\file', 'Use //server/share/file',
            'Host internal.example.invalid', 'Address 192.0.2.11', 'Address 2001:db8::1',
            'Address [::1]', 'Address fe80::1%eth0', 'Address ::ffff:192.0.2.1',
            'Write owner@example.invalid', 'Clone git@github.com:public/example.git',
            'Clone ssh://owner@host.invalid/project', 'Clone owner@server:repo',
            'Clone server:repo', 'See http://internalbox/page',
            'Clone https://github.com/public/example.git', 'Clone public/example',
            'private-project', 'the-project-key', 'hostname: internalbox', 'localhost',
        ]
        for value in blocked:
            self.assertTrue(screen(value, 'the-project-key', 'private-project'), value)
        permitted = ['Keep task handles.', 'Use seankoji-com/.agents',
                     'See https://github.com/seankoji-com/.agents',
                     'See docs.example.invalid for public instructions.', 'Keep one lesson per stable ID.',
                     'Note: keep handles', 'Impact: retries stalled']
        for value in permitted:
            self.assertEqual(screen(value, 'the-project-key', 'private-project', 'docs.example.invalid'), [], value)
        self.assertTrue(screen('docs.example.invalid', 'key', 'label'))
        self.assertTrue(screen('github.com.evil.invalid', 'key', 'label', 'docs.example.invalid'))

    def test_blocked_drafts_are_not_returned_for_display(self):
        self.drafts[0]['body'] = 'Stored at /private/location'
        result = prepare(self.loaded, self.drafts, project_slug='public/example')
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn('draft', result)
        self.assertNotIn('/private/location', json.dumps(result))

    def test_no_publication_without_exact_explicit_owner_approval(self):
        prepared = prepare(self.loaded, self.drafts, project_slug='public/example')
        issue, pr = mock.Mock(), mock.Mock()
        def publish(reply):
            approved = verify_for_publication(self.loaded, prepared['draft'], prepared['shown_digest'], reply)
            for draft in approved:
                (issue if draft['destination'] == 'upstream' else pr)(draft['title'], draft['body'])
        for reply in ('yes', '', 'approve wrong', json.dumps({'approved': True})):
            with self.assertRaises(Unavailable):
                publish(reply)
        issue.assert_not_called()
        pr.assert_not_called()
        publish('approve ' + prepared['shown_digest'])
        issue.assert_called_once_with(self.drafts[0]['title'], self.drafts[0]['body'])
        pr.assert_called_once_with(self.drafts[1]['title'], self.drafts[1]['body'])
        amended = json.loads(json.dumps(prepared['draft']))
        amended['drafts'][0]['body'] += ' More text.'
        with self.assertRaises(Unavailable):
            check_approval(amended, prepared['shown_digest'], 'approve ' + prepared['shown_digest'])

    def test_fakes_publish_exact_drafts_and_remove_only_after_all_destinations_have_urls(self):
        prepared = prepare(self.loaded, self.drafts, project_slug='public/example')
        issue = mock.Mock(return_value='https://github.com/seankoji-com/.agents/issues/42')
        pr = mock.Mock(side_effect=OSError('publication unavailable'))
        approved = verify_for_publication(self.loaded, prepared['draft'], prepared['shown_digest'],
                                         'approve ' + prepared['shown_digest'])
        receipts = []
        for draft in approved:
            try:
                url = (issue if draft['destination'] == 'upstream' else pr)(draft['title'], draft['body'])
                receipts.append(dict(entry_id=draft['entry_id'], destination=draft['destination'], url=url))
            except OSError:
                pass
        issue.assert_called_once_with(self.drafts[0]['title'], self.drafts[0]['body'])
        partial = self.store.operate('harvest', self.proposal(prepared, receipts))
        self.assertEqual(partial['status'], 'available', partial)
        entry = partial['data']['entries'][0]
        self.assertEqual(entry['destinations'], {'upstream': issue.return_value, 'agents': None})
        partial = self.store.operate('write', {'entry': {
            'id': 'lesson', 'summary': entry['summary'], 'failure': entry['failure']}})
        self.assertEqual(partial['data']['entries'][0]['destinations'], entry['destinations'])
        # The successful issue is never posted again. Fresh approval covers the remaining PR.
        prepared = prepare(partial, [self.drafts[1]], project_slug='public/example')
        pr = mock.Mock(return_value='https://github.com/public/example/pull/7')
        verify_for_publication(partial, prepared['draft'], prepared['shown_digest'], 'approve ' + prepared['shown_digest'])
        url = pr(self.drafts[1]['title'], self.drafts[1]['body'])
        result = self.store.operate('harvest', self.proposal(prepared, [
            dict(entry_id='lesson', destination='agents', url=url)]))
        self.assertEqual(result['status'], 'available', result)
        self.assertEqual(result['data']['entries'], [])
        issue.assert_called_once()

    def test_pre_198_upstream_receipt_still_reconciles(self):
        prepared = prepare(self.loaded, self.drafts[:1], project_slug='public/example')
        lookalike = self.proposal(prepared, [dict(entry_id='lesson', destination='upstream',
                                                  url='https://github.com/seankoji-com/t3-plugins-fork/issues/42')])
        self.assertEqual(self.store.operate('harvest', lookalike)['status'], 'unavailable')
        old = 'https://github.com/seankoji-com/t3-plugins/issues/42'
        result = self.store.operate('harvest', self.proposal(prepared, [
            dict(entry_id='lesson', destination='upstream', url=old)]))
        self.assertEqual(result['status'], 'available', result)
        self.assertEqual(result['data']['entries'], [])  # its only approved destination is published

    def test_changed_source_and_unapproved_destinations_cannot_delete_entries(self):
        prepared = prepare(self.loaded, self.drafts, project_slug='public/example')
        proposal = self.proposal(prepared, [dict(entry_id='lesson', destination='upstream',
                                               url='https://github.com/elsewhere/repo/issues/1')])
        self.assertEqual(self.store.operate('harvest', proposal)['status'], 'unavailable')
        proposal['receipts'] = [dict(entry_id='lesson', destination='other', url='https://github.com/public/example/pull/7')]
        self.assertEqual(self.store.operate('harvest', proposal)['status'], 'unavailable')
        self.store.operate('write', {'entry': {'id': 'lesson', 'summary': 'Changed', 'failure': 'Observed again'}})
        with self.assertRaises(Unavailable):
            verify_for_publication(self.store.operate(), prepared['draft'], prepared['shown_digest'], proposal['owner_reply'])
        proposal['expected'] = self.store.operate()['revision']
        proposal['receipts'] = []
        self.assertEqual(self.store.operate('harvest', proposal)['status'], 'unavailable')
        self.assertEqual(len(self.store.operate()['data']['entries']), 1)

    def test_project_pr_slug_is_part_of_exact_approval(self):
        prepared = prepare(self.loaded, self.drafts, project_slug='public/example')
        changed = json.loads(json.dumps(prepared['draft']))
        changed['project_slug'] = 'elsewhere/repo'
        with self.assertRaises(Unavailable):
            verify_for_publication(self.loaded, changed, prepared['shown_digest'],
                                   'approve ' + prepared['shown_digest'])
        proposal = self.proposal(prepared, [dict(entry_id='lesson', destination='agents',
                                               url='https://github.com/elsewhere/repo/pull/7')])
        proposal['project_slug'] = 'elsewhere/repo'
        self.assertEqual(self.store.operate('harvest', proposal)['status'], 'unavailable')

    def test_normal_writes_cannot_forge_publication_receipts(self):
        before = self.store.operate()
        for entry_id in ('lesson', 'new'):
            for destinations in ({}, {'upstream': 'https://github.com/seankoji-com/.agents/issues/42',
                                     'agents': 'https://github.com/public/example/pull/7'}):
                result = self.store.operate('write', {'entry': {
                    'id': entry_id, 'summary': 'Retain handles', 'failure': 'Observed failure',
                    'destinations': destinations}})
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(self.store.operate()['revision'], before['revision'])
        prepared = prepare(before, self.drafts, project_slug='public/example')
        result = self.store.operate('harvest', self.proposal(prepared, []))
        self.assertEqual(len(result['data']['entries']), 1)
        self.assertEqual(result['data']['entries'][0]['destinations'], {'upstream': None, 'agents': None})


if __name__ == '__main__':
    unittest.main()
