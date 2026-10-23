"""Actual upstream-bound request/receipt paths. Every host observation is synthetic."""
import copy
import unittest

from tests import test_bug_report as fixtures

ledger = fixtures.ledger


class UpstreamReporting(unittest.TestCase):
    setUp = fixtures.Reporting.setUp
    call = fixtures.Reporting.call
    search = fixtures.Reporting.search
    prepared = fixtures.Reporting.prepared
    finish = fixtures.Reporting.finish
    dispatch = fixtures.Reporting.dispatch
    launch = fixtures.Reporting.launch

    def upstream(self, method='github', destination='https://github.com/example/parser'):
        p = fixtures.problem(outcome='upstream-defect')
        p.update(upstream_name='Fixture parser', reporting_route={
            'method': method, 'destination': destination,
            'documentation': 'https://example.invalid/contributing',
            'ownership_evidence': 'fixture:observed-package-origin'})
        self.call('problem', p)
        if method == 'github':
            self.search()
        else:
            self.search(queries=[], channels_complete=True, channels=[{'channel': 'documented intake',
                        'status': 'not-applicable', 'evidence': 'fixture:no-public-duplicate-search'}])
        self.launch()
        return p

    def generic_prepare(self, p, **changes):
        route = p['reporting_route']
        data = {'kind': 'issue', 'problem': 'p1', 'actor_thread': 'reporter',
                'privacy_reviewed': True, 'destination_refreshed': True,
                'transport': 'github-rest' if route['method'] == 'github' else 'documented',
                'destination_observation': {'write_access': True, 'templates_read': True,
                    'repository_url': route['destination'], 'reporting_destination': route['destination'],
                    'method_documentation': route['documentation']},
                'payload': {'title': 'Observed upstream defect', 'body': 'PRIVATE_TRANSCRIPT_SENTINEL evidence'}}
        data.update(changes)
        return self.call('prepare', data)

    def test_another_github_upstream_binds_generated_request_and_receipt(self):
        p = self.upstream()
        op = self.generic_prepare(p)
        self.assertEqual(op['request']['endpoint'], 'repos/example/parser/issues')
        self.assertEqual(op['request']['input']['body'], '[redacted] evidence')
        self.dispatch(op)
        with self.assertRaises(ledger.Held):
            self.finish(op, url=fixtures.URL, created_at=self.now,
                        payload_sha256=ledger.digest(op['payload']))
        self.finish(op, url='https://github.com/example/parser/issues/42', created_at=self.now,
                    payload_sha256=ledger.digest(op['payload']))
        self.assertEqual(self.store.status('case')['deadline'], self.now + 1800)

    def test_documented_web_intake_requires_actual_same_origin_receipt(self):
        p = self.upstream('web', 'https://tracker.example.invalid/new')
        op = self.generic_prepare(p)
        self.assertEqual(op['request']['destination'], p['reporting_route']['destination'])
        self.dispatch(op)
        for url, reference in [('https://wrong.example.invalid/42', 'ticket:42'),
                               ('https://tracker.example.invalid/42', None)]:
            with self.assertRaises(ledger.Held):
                self.finish(op, url=url, receipt_reference=reference, created_at=self.now,
                            payload_sha256=ledger.digest(op['payload']))
        self.finish(op, url='https://tracker.example.invalid/42', receipt_reference='ticket:42',
                    created_at=self.now, payload_sha256=ledger.digest(op['payload']))
        self.assertEqual(self.store.status('case')['receipts'][0]['reference'], 'ticket:42')

    def test_documented_email_requires_sent_message_receipt_and_exact_recipient(self):
        p = self.upstream('email', 'mailto:bugs@example.invalid')
        op = self.generic_prepare(p)
        self.dispatch(op)
        with self.assertRaises(ledger.Held):
            self.finish(op, url='mailto:someone@example.invalid', receipt_reference='message:42',
                        created_at=self.now, payload_sha256=ledger.digest(op['payload']))
        self.finish(op, url='mailto:bugs@example.invalid', receipt_reference='message:42',
                    created_at=self.now, payload_sha256=ledger.digest(op['payload']))
        self.assertEqual(self.store.status('case')['receipts'][0]['reference'], 'message:42')
        comments = {'target': 'mailto:bugs@example.invalid', 'pages_complete': True,
                    'actor': 'fixture-author', 'items': [
                        {'id': 'reply:42', 'author': 'maintainer', 'body': 'Which release?'}]}
        with self.assertRaises(ledger.Held):
            self.call('comments', comments)
        comments['receipt_reference'] = 'message:42'
        self.assertEqual(len(self.call('comments', comments)['comments']), 1)

    def test_unknown_or_tampered_method_cannot_admit_publication(self):
        p = fixtures.problem(outcome='upstream-defect')
        with self.assertRaises(ledger.Held):
            self.call('problem', p)
        for method, destination in [('unknown', 'https://tracker.example.invalid/new'),
                                    ('github', 'https://github.com/./..'),
                                    ('web', 'https://user:password@tracker.example.invalid/new'),
                                    ('email', 'mailto:bugs@example.invalid?bcc=extra@example.invalid')]:
            invalid = fixtures.problem(outcome='upstream-defect')
            invalid.update(upstream_name='Fixture parser', reporting_route={'method': method,
                'destination': destination, 'documentation': 'https://example.invalid/reporting',
                'ownership_evidence': 'fixture:package-origin'})
            with self.subTest(method=method), self.assertRaises(ledger.Held):
                self.call('problem', invalid)
        p = self.upstream()
        op = self.generic_prepare(p)
        changed = copy.deepcopy(p)
        changed['reporting_route']['destination'] = 'https://github.com/example/other'
        self.call('problem', changed)
        self.search()
        with self.assertRaises(ledger.Held):
            self.dispatch(op)

    def test_failed_or_unsupported_duplicate_search_keeps_the_report_private(self):
        p = self.upstream('web', 'https://tracker.example.invalid/new')
        for status in ('failed', 'unsupported', 'searched'):
            self.search(queries=[], channels_complete=True, channels=[
                {'channel': 'tracker', 'status': status, 'evidence': 'fixture:observed-search-result'}])
            with self.subTest(status=status), self.assertRaises(ledger.Held):
                self.generic_prepare(p)


if __name__ == '__main__':
    unittest.main()
