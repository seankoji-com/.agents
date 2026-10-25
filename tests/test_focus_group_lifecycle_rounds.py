"""Focus-group contract scenarios split to keep each module within the existing test deadline."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_focus_group_lifecycle import (  # noqa: E402
    BEFORE,
    Case,
    DELIVERED,
    TEMPLATE,
    json,
    setUpModule,
    sha,
    tearDownModule,
)


class ReviewRoundTest(Case):
    """Each scenario of the round-0 review, through the installed job helper and the source study helpers."""

    def task(self, task_id):
        return next(t for t in self.h.job_state()['tasks'] if t['task_id'] == task_id)

    def accepted_bytes(self):
        folder = self.h.root / self.h.view['study_id'] / 'focus-group' / 'accepted'
        return {p.name: p.read_bytes() for p in folder.glob('*.json')}

    def decide(self, record_sha, statement):
        """The owner's sole answer `statement`, saved outside the job, offered to accept-identity."""
        h = self.h
        h.counter += 1
        source = h.base / 'owner' / f'identity-{h.counter}.txt'
        source.parent.mkdir(exist_ok=True)
        source.write_text(f'Selected option: {statement}\n')
        return h.lc(*h.study('accept-identity'), '--input', h.write(f'id-{h.counter}.json', {
            'record_sha256': record_sha, 'message_ref': 'picker-identity', 'statement': statement,
            'source': str(source), 'source_sha256': sha(source.read_bytes())}))

    def disclosures(self):
        """Every consumer's disclosure gate: consumer -> (exit code, output)."""
        h = self.h
        return {c: h.call_evidence('disclosure', '--state-root', h.root, '--study', h.view['study_id'], '--consumer', c)
                for c in ('participant', 'analysis', 'review', 'export')}

    def cells(self):
        return {c['cell_id']: c for c in self.h.progress()['cells']}

    def test_r1_a_closed_request_whose_host_work_reopens_still_occupies_concurrency(self):
        h = self.h
        h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=1))
        run = h.first(0)
        self.assertEqual(run['code'], 0, run['out'])
        view = h.reconcile()
        self.assertEqual((next(r for r in view['requests'] if r['request_id'] == 'fi-01-r0')['ledger_state'],
                          view['quiescent']), ('terminal', True))
        # A later recorded reading of the closed request's own host task shows a pending descendant.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', run['host'], None, pending=True, kind='reconciled')[0], 0)
        charged, records = h.charged(), self.accepted_bytes()
        out = self.refused(h.admit_slot(1, 'first-impression', 'fi-02-r0'), 'concurrency_limit')
        self.assertEqual(out['data']['occupied'], ['fi-01-r0'])
        self.assertEqual(h.charged(), charged)
        slots = {s['slot']: s for s in h.resume()['slots']}
        held = slots[f'{h.cell(1)}:first-impression']
        self.assertEqual((held['state'], held['code']), ('held', 'concurrency_limit'))
        self.assertEqual(h.reconcile()['unresolved'], ['fi-01-r0'])
        # The earlier closure, its charge and the accepted record stay; only the host's own terminal reading
        # without pending runs frees the slot, and only an admitted request is then prepared.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', run['host'], None, kind='reconciled')[0], 0)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['charged']), (0, True), out)
        self.assertEqual(h.prepare('fi-02')['request_id'], 'fi-02-r0')
        self.assertEqual((h.charged(), self.accepted_bytes()), ({'first': 2}, records))

    def test_r2_a_retained_conflicting_host_task_keeps_cancellation_pending_until_its_own_terminal_reading(self):
        h = self.h
        h.start()
        run, control = h.first(0), h.first(1)
        self.assertEqual((run['code'], control['code']), (0, 0))
        # The host returns a second task for the same request: the shared job refuses it as a handle and retains
        # it as a conflict. A refused observation does not prove the returned task never ran.
        code, _ = h.observe('fi-01', kind='accepted', request_id='fi-01-r0', host_task_id='host-dup',
                            child_thread_id='thread-dup', status='running', work_state='working',
                            has_pending_child_runs=False)
        self.assertEqual(code, 2)
        self.assertEqual([c['host_task_id'] for c in self.task('fi-01')['host_conflicts']], ['host-dup'])
        view = h.reconcile()
        row = next(r for r in view['requests'] if r['request_id'] == 'fi-01-r0')
        self.assertEqual((row['state'], row['ledger_state'], view['quiescent'], view['unresolved']),
                         ('conflicting-host', 'terminal', False, ['fi-01-r0']))
        self.assertEqual(view['actions']['task_status'], [{'host_task_id': 'host-dup', 'request_id': 'fi-01-r0'}])
        charged, records = h.charged(), self.accepted_bytes()
        expected = [{'host_task_id': 'host-dup', 'request_id': 'fi-01-r0'}]
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['cancel'], cancel['task_cancel']),
                         (False, ['fi-01-r0'], expected))
        # The unrelated accepted control and the original, settled handle are never named.
        self.assertNotIn(control['host'], json.dumps(cancel))
        self.assertNotIn(run['host'], json.dumps(cancel['task_cancel']))
        wake = h.ok('wake', '--state-root', h.root, '--study', h.view['study_id'], now=BEFORE)
        self.assertEqual((wake['cancellation_confirmed'], wake['task_cancel']), (False, expected))
        # A non-terminal reading of the conflicting task is refused by the shared job and confirms nothing.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', 'host-dup', None, status='running', work_state='working',
                                    kind='reconciled')[0], 2)
        self.assertEqual(h.reconcile()['actions']['task_cancel'], expected)
        # Its own terminal reconciliation without pending runs, recorded by the shared job, confirms it.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', 'host-dup', None, status='cancelled', kind='reconciled')[0], 0)
        view = h.reconcile()
        self.assertEqual((view['cancellation_confirmed'], view['quiescent'], view['actions']['task_cancel']),
                         (True, True, []))
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['task_cancel']), (True, []))
        self.assertEqual((h.charged(), self.accepted_bytes()), (charged, records))

    def two_hosts_for_one_request(self):
        """FG3-C2: at max_concurrency 2, one request owns two unresolved host tasks, its handle and a conflict."""
        h = self.h
        h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=2))
        # Both models' pilots are accepted first, so only concurrency can hold the later cells.
        self.assertEqual((h.first(0)['code'], h.first(1)['code']), (0, 0))
        h.journey_ready(0)
        h.journey_ready(1)
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        h.prepare('fi-03')
        primary = h.launch('fi-03', 'fi-03-r0', n=2)
        conflict = dict(kind='accepted', request_id='fi-03-r0', host_task_id='host-dup', child_thread_id='thread-dup',
                        status='running', work_state='working', has_pending_child_runs=False)
        self.assertEqual(h.observe('fi-03', **conflict)[0], 2)
        # Repeated notifications of either host task are the same physical work and never inflate the count.
        self.assertEqual(h.observe('fi-03', **conflict)[0], 2)
        h.observe('fi-03', **dict(conflict, host_task_id=primary, child_thread_id=f'thread-{primary}'))
        view = h.reconcile()
        self.assertEqual(view['actions']['task_status'], [{'host_task_id': primary, 'request_id': 'fi-03-r0'},
                                                          {'host_task_id': 'host-dup', 'request_id': 'fi-03-r0'}])
        charged = h.charged()
        out = self.refused(h.admit_slot(3, 'first-impression', 'fi-04-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['occupied'], out['data']['occupied_count']), (['fi-03-r0'], 2))
        self.assertEqual(sorted(w['host_task_id'] for w in out['data']['occupied_work']), sorted([primary, 'host-dup']))
        self.assertEqual(h.charged(), charged)
        held = {s['slot']: s for s in h.resume()['slots']}[f'{h.cell(3)}:first-impression']
        self.assertEqual((held['state'], held['code']), ('held', 'concurrency_limit'))
        return primary

    def settle_one_then_both(self, first, second):
        h = self.h
        # Settling either owned host task through its own terminal reading frees exactly one slot.
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', first, None, status='cancelled', kind='reconciled')[0], 0)
        slots = {s['slot']: s for s in h.resume()['slots']}
        self.assertEqual(slots[f'{h.cell(3)}:first-impression']['state'], 'dispatchable')
        code, out = h.admit_slot(3, 'first-impression', 'fi-04-r0')
        self.assertEqual((code, out['data']['charged']), (0, True), out)
        self.assertEqual(h.prepare('fi-04')['request_id'], 'fi-04-r0')
        other = h.launch('fi-04', 'fi-04-r0', n=3)
        out = self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['occupied'], out['data']['occupied_count']), (['fi-03-r0', 'fi-04-r0'], 2))
        self.assertEqual(sorted(w['host_task_id'] for w in out['data']['occupied_work']), sorted([second, other]))
        # Settling the request's other host task frees its last slot; the request then occupies nothing.
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', second, None, status='cancelled', kind='reconciled')[0], 0)
        self.assertNotIn('fi-03-r0', h.reconcile()['unresolved'])
        self.assertEqual(h.admit_slot(0, 'journey', 'jr-01-r0')[0], 0)
        # An admitted request with no host task yet keeps its reservation.
        out = self.refused(h.admit_slot(1, 'journey', 'jr-02-r0'), 'concurrency_limit')
        self.assertEqual(out['data']['occupied'], ['fi-04-r0', 'jr-01-r0'])
        self.assertEqual(h.charged(), {'first': 5})

    def test_c2_a_conflicting_host_task_occupies_its_own_slot_until_its_terminal_reading(self):
        primary = self.two_hosts_for_one_request()
        self.settle_one_then_both('host-dup', primary)

    def test_c2_a_settled_handle_frees_its_slot_while_the_conflict_still_occupies_one(self):
        primary = self.two_hosts_for_one_request()
        self.settle_one_then_both(primary, 'host-dup')

    def test_r3_a_later_host_source_naming_another_model_withdraws_verified_use(self):
        h = self.h
        h.start()
        run = h.first(0)
        self.assertEqual(run['out']['data']['identity'], 'verified')
        records = self.accepted_bytes()
        # An authoritative reading of the same host task later names another model of that provider.
        code, _ = h.observe('fi-01', kind='reconciled', request_id='fi-01-r0', host_task_id=run['host'],
                            status='completed', work_state='result_available', has_pending_child_runs=False,
                            status_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        self.assertEqual(code, 0)
        self.assertEqual(self.task('fi-01')['handles'][0]['observed_identity']['status'], 'mismatched')
        row = {c['cell_id']: c for c in h.progress()['cells']}[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['verified_coverage'], row['accepted_identity'], row['observed']['model']),
                         ('mismatched', False, 'verified', 'alpha-deep'))
        pilots = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual((pilots[(h.cell(0), 'first-impression')]['state'],
                          pilots[(h.cell(0), 'first-impression')]['reasons']), ('failed', ['identity mismatched']))
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((coverage['cells'][0]['first_identity'], coverage['verified_identity']['first_impressions']),
                         ('mismatched', 0))
        charged = h.charged()
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(h.charged(), charged)
        # The accepted record is history and never rewritten.
        self.assertEqual(self.accepted_bytes(), records)
        # Only the owner's exact decision on the discrepancy shown now permits disclosed use, never `verified`.
        # The launch reading named the requested model and the later one another (FG3-R8): an instruction naming
        # only the later model hides that contradiction and is refused; the accepted one names every model.
        hidden = (f'Accept observed model fixture-a/alpha-deep for focus-group cell {h.cell(0)} '
                  'first-impression request fi-01-r0 (requested fixture-a/alpha-swift)')
        instruction = (f'Accept contradictory host identity for focus-group cell {h.cell(0)} first-impression request '
                       'fi-01-r0 (requested fixture-a/alpha-swift; readings fixture-a/alpha-deep, fixture-a/alpha-swift; '
                       'resolved fixture-a/alpha-deep, fixture-a/alpha-swift; now fixture-a/alpha-deep)')
        self.assertEqual(row['identity_evidence']['instruction'], instruction)
        out = self.refused(self.decide(run['out']['data']['record_sha256'], hidden), 'approval_scope_mismatch')
        self.assertEqual(out['data']['expected'], instruction)
        code, out = self.decide(run['out']['data']['record_sha256'], instruction)
        self.assertEqual(code, 0, out)
        decided = out['data']
        self.assertEqual((decided['identity'], decided['verified'], decided['decision']['recorded_identity'],
                          decided['decision']['current_identity']),
                         ('owner-accepted-discrepancy', False, 'verified', 'mismatched'))
        row = {c['cell_id']: c for c in h.progress()['cells']}[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['verified_coverage']), ('owner-accepted-discrepancy', False))
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        # It never carries into another revision.
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        entry = next(e for e in h.plan(draft)['carry_forward']['entries']
                     if e['record_sha256'] == run['out']['data']['record_sha256'])
        self.assertEqual(entry['status'], 'stale')
        self.assertIn('observed model identity is not verified against the request', entry['reasons'])

    def record(self, record_sha):
        return next(r for r in map(json.loads, self.accepted_bytes().values()) if r['record_sha256'] == record_sha)

    def withdraw(self, task, request, host, **source):
        """An authoritative terminal reading of the request's own host task naming another identity."""
        code, out = self.h.observe(task, kind='reconciled', request_id=request, host_task_id=host, status='completed',
                                   work_state='result_available', has_pending_child_runs=False, **source)
        self.assertEqual(code, 0, out)

    def test_r3_withdrawn_identity_stops_every_consumer_of_the_record_and_its_journey_until_the_owner_decides(self):
        h = self.h
        h.start()
        first, other = h.first(0), h.first(1)
        journey = h.journey(0)
        self.assertEqual((first['code'], other['code'], journey[0], journey[1]['data']['identity']),
                         (0, 0, 0, 'verified'), journey[1])
        fi, jr = first['out']['data']['record_sha256'], journey[1]['data']['record_sha256']
        self.assertEqual({c: out[0] for c, out in self.disclosures().items()}, dict.fromkeys(
            ('participant', 'analysis', 'review', 'export'), 0))
        records, charged = self.accepted_bytes(), h.charged()
        self.withdraw('fi-01', 'fi-01-r0', first['host'],
                      status_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        # Every consumer refuses the first impression and the journey built on it; the raw records stay.
        for consumer, (code, out) in self.disclosures().items():
            with self.subTest(consumer=consumer):
                self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'), out)
                self.assertEqual({(p['record_sha256'], p['code']) for p in out['data']['material']},
                                 {(fi, 'identity_unverified'), (jr, 'predecessor_unusable')})
        for command, record_sha in (('freeze-first', fi), ('accept-journey', jr)):
            code, out = h.call_evidence(command, '--state-root', h.root, '--study', h.view['study_id'], '--input',
                                        h.write(f'{command}.json', {'record_sha256': record_sha,
                                                                    'payload': self.record(record_sha)['result']}))
            self.assertEqual((code, out['error']['code']), (1, 'material_unusable'), out)
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        row = coverage['cells'][0]
        self.assertEqual((row['first_impression'], row['first_identity'], row['journey']['state'], row['journey_identity']),
                         ('identity-unverified', 'mismatched', 'predecessor-unusable', 'verified'))
        self.assertEqual((coverage['verified_identity'], coverage['journey_gaps']),
                         ({'first_impressions': 1, 'journeys': 0}, 1))
        pilots = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual(pilots[(h.cell(0), 'first-impression')]['reasons'], ['identity mismatched'])
        self.assertEqual((pilots[(h.cell(0), 'journey')]['state'], pilots[(h.cell(0), 'journey')]['reasons']),
                         ('failed', ['predecessor_unusable']))
        row = self.cells()[h.cell(0)]
        self.assertEqual((row['first-impression']['state'], row['first-impression']['problems'],
                          row['journey']['state'], row['journey']['problems'], row['journey']['identity']),
                         ('unusable', ['identity_unverified'], 'unusable', ['predecessor_unusable'], 'verified'))
        slots = {s['slot']: s['state'] for s in h.resume()['slots']}
        self.assertEqual((slots[f'{h.cell(0)}:first-impression'], slots[f'{h.cell(0)}:journey']),
                         ('accepted-unusable', 'accepted-unusable'))
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        # The other model's records are unaffected: its pilot journey is briefed, admitted and accepted.
        control = h.journey(1)
        self.assertEqual((control[0], control[1]['data']['identity']), (0, 'verified'), control[1])
        pilots = {(p['pilot_cell'], p['stage']): p['state'] for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual((pilots[(h.cell(1), 'first-impression')], pilots[(h.cell(1), 'journey')]), ('passed', 'passed'))
        after = self.accepted_bytes()
        self.assertEqual(({k: after[k] for k in records}, len(after)), (records, len(records) + 1))
        self.assertEqual(h.charged(), {'first': charged['first'] + 1})
        # The owner sees every reading and accepts exactly this discrepancy: use is permitted, visibly, never
        # as verified identity, and nothing is carried.
        found = self.cells()[h.cell(0)]['first-impression']['identity_evidence']
        self.assertEqual((found['kind'], [(r['source'], r['model']) for r in found['readings']]),
                         ('contradictory', [('status', 'alpha-swift'), ('status', 'alpha-deep')]))
        code, out = self.decide(fi, found['instruction'])
        self.assertEqual((code, out['data']['decision']['discrepancy_sha256']), (0, found['discrepancy_sha256']), out)
        for consumer, (code, out) in self.disclosures().items():
            with self.subTest(consumer=consumer, decided=True):
                self.assertEqual(code, 0, out)
                ids = {r['record_sha256']: r for r in out['data']['identities']}
                self.assertEqual((ids[fi]['identity'], ids[fi]['verified'], ids[fi]['discrepancy_sha256'],
                                  [r['model'] for r in ids[fi]['readings']]),
                                 ('owner-accepted-discrepancy', False, found['discrepancy_sha256'],
                                  ['alpha-swift', 'alpha-deep']))
                self.assertEqual((ids[jr]['identity'], ids[jr]['verified']), ('verified', True))
        coverage = h.evidence_ok('coverage', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((coverage['cells'][0]['first_identity'], coverage['cells'][0]['journey']['state']),
                         ('owner-accepted-discrepancy', 'hands-on-evidence'))
        self.assertEqual(coverage['verified_identity'], {'first_impressions': 1, 'journeys': 2})
        self.assertEqual(self.accepted_bytes(), after)
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['limits']['deadline'] = '2031-01-01T00:00:00Z'
        entries = {e['record_sha256']: e['status'] for e in h.plan(draft)['carry_forward']['entries']}
        self.assertEqual((entries[fi], entries[jr]), ('stale', 'stale'))

    def test_r3_a_journey_is_never_briefed_admitted_or_ingested_on_its_own_unusable_first(self):
        h = self.h
        h.start()
        first, other = h.first(0), h.first(1)
        # Model A's pilot journey is briefed and declared while its first impression is still verified.
        h.journey_ready(0)
        # Model B's pilot journey is admitted, prepared and launched on a then-verified first impression.
        document = h.journey_ready(1)
        self.assertEqual(h.admit_slot(1, 'journey', 'jr-02-r0')[0], 0)
        brief = h.prepare('jr-02')
        host = h.launch('jr-02', 'jr-02-r0', n=1)
        # A receipt reading of each first impression's own host task names another model of its provider.
        for task, run, provider_id, model in (('fi-01', first, 'fixture-a', 'alpha-deep'),
                                              ('fi-02', other, 'fixture-b', 'beta-two')):
            code, out = h.observe(task, kind='identity', request_id=f'{task}-r0', host_task_id=run['host'],
                                  receipt_identity={'providerInstanceId': provider_id, 'model': model})
            self.assertEqual(code, 0, out)
        charged, records = h.charged(), self.accepted_bytes()
        # Being its model's pilot is no proof of its predecessor: no new brief, and the earlier one admits nothing.
        code, out = h.call_evidence('brief', '--state-root', h.root, '--study', h.view['study_id'], '--input',
                                    h.write('rebrief.json', {'revision': h.view['revision'], 'cell_id': h.cell(0),
                                                             'stage': 'journey', 'task_id': 'jr-01'}))
        self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'), out)
        self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'predecessor_unusable')
        held = {s['slot']: s for s in h.resume()['slots']}[f'{h.cell(0)}:journey']
        self.assertEqual((held['state'], held['code']), ('held', 'predecessor_unusable'))
        # The journey already running finishes; its complete result is retained and refused, not product friction.
        context = h.bound_context(h.view, h.cell(1))
        item = h.payload_file('jr-02', h.journey_payload(h.view, h.cell(1), document['sha256'], context))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('jr-02', 'jr-02-r0', host, 'done-jr-02')[0], 0)
        self.assertEqual(h.deliver('jr-02', 'jr-02-r0', 'done-jr-02', path)[0], 0)
        ingest = dict(context={'class': 'fresh-anonymous', **context})
        code, out = h.ingest('jr-02', 'jr-02-r0', 'done-jr-02', path, **ingest)
        self.assertEqual((code, out['error']['code'], out['data']['category'], out['data']['product_friction']),
                         (1, 'predecessor_unusable', 'evidence', False), out)
        raw = h.root / h.view['study_id'] / 'focus-group' / out['data']['raw_retained']
        self.assertEqual(raw.read_bytes(), path.read_bytes())
        self.assertEqual((self.accepted_bytes(), h.charged()), (records, charged))
        # The owner accepts model B's contradiction as shown; the same retained completion is then accepted on it.
        # Model A's first impression is untouched by that decision and still admits nothing.
        found = self.cells()[h.cell(1)]['first-impression']['identity_evidence']
        self.assertEqual((found['kind'], found['reported_models']), ('contradictory', ['beta-one', 'beta-two']))
        self.assertEqual(self.decide(other['out']['data']['record_sha256'], found['instruction'])[0], 0)
        code, out = h.ingest('jr-02', 'jr-02-r0', 'done-jr-02', path, **ingest)
        self.assertEqual((code, out['data']['identity'], out['data']['predecessor_records'][0]['record_sha256']),
                         (0, 'verified', other['out']['data']['record_sha256']), out)
        self.assertEqual([r['outcome'] for r in h.session('jr-02-r0')], ['refused', 'accepted'])
        self.refused(h.admit_slot(0, 'journey', 'jr-01-r0'), 'predecessor_unusable')
        self.assertEqual(h.charged(), charged)

    def test_r3_identity_follows_the_exact_original_request_through_a_retry_and_a_new_revision(self):
        h = self.h
        h.start()
        old = h.first(0)
        self.assertEqual((old['code'], h.first(1)['code']), (0, 0))
        old_sha = old['out']['data']['record_sha256']
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['prompts']['first_impression'] += ' Note one thing that works.'
        revised = h.plan(draft)
        h.approve(revised)
        h.ok('carry', '--state-root', h.root, '--study', revised['study_id'], '--write')
        h.view = revised
        _, documents = h.revise_job()
        h.documents.update(documents)
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'fi-01', 'reason': 'protocol revision'})
        request = self.task('fi-01')['request_id']
        new = h.first(0, request=request)
        self.assertEqual((new['code'], new['out']['data']['identity']), (0, 'verified'), new['out'])
        new_sha = new['out']['data']['record_sha256']
        records = self.accepted_bytes()
        # A reading of the retired request's own host task withdraws only that execution's record.
        self.withdraw('fi-01', 'fi-01-r0', old['host'],
                      status_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        out = self.refused(self.decide(old_sha, 'Accept nothing'), 'approval_scope_mismatch')
        evidence = out['data']['evidence']
        self.assertEqual((evidence['request_id'], evidence['host_task_id'], evidence['reported_models']),
                         ('fi-01-r0', old['host'], ['alpha-deep', 'alpha-swift']))
        self.refused(self.decide(new_sha, 'Accept nothing'), 'identity_verified')
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['state'], row['observed']['model']), ('verified', 'accepted', 'alpha-swift'))
        # The old record is excluded history of this revision: private, never disclosed, never blocking.
        code, out = self.disclosures()['analysis']
        self.assertEqual((code, out['data']['selected_records'], out['data']['excluded_history_records']),
                         (0, [new_sha], 2), out)
        # A reading of the current request withdraws the current record and names only it; nothing is replaced.
        self.withdraw('fi-01', request, new['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        code, out = self.disclosures()['analysis']
        self.assertEqual((code, [(p['record_sha256'], p['code']) for p in out['data']['material']]),
                         (1, [(new_sha, 'identity_unverified')]), out)
        self.assertEqual(self.accepted_bytes(), records)
        self.assertIn('fi-01-r0', self.task('fi-01')['retired_request_ids'])

    def test_r8_contradictory_host_sources_are_shown_whole_and_bind_the_owner_decision(self):
        h = self.h
        h.start()
        run, other = h.first(0), h.first(1)
        fi, fb = run['out']['data']['record_sha256'], other['out']['data']['record_sha256']
        records = self.accepted_bytes()
        # The status source keeps the requested model; a receipt names another (the original R8 case).
        self.withdraw('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((row['identity'], row['observed']['model'], found['shared_status'], found['kind'],
                          found['observed'], found['hold']), ('mismatched', 'alpha-swift', 'mismatched', 'contradictory',
                                                              None, None))
        self.assertEqual(found['current_sources'], {'status': {'providerInstanceId': 'fixture-a', 'model': 'alpha-swift'},
                                                    'receipt': {'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'}})
        self.assertEqual([(r['source'], r['model']) for r in found['readings']],
                         [('status', 'alpha-swift'), ('receipt', 'alpha-deep')])
        # An instruction naming the request as observed, or only one of the reported models, is refused.
        for model in ('alpha-swift', 'alpha-deep'):
            out = self.refused(self.decide(fi, f'Accept observed model fixture-a/{model} for focus-group cell '
                                               f'{h.cell(0)} first-impression request fi-01-r0 '
                                               '(requested fixture-a/alpha-swift)'),
                               'approval_scope_mismatch')
            self.assertEqual((out['data']['expected'], out['data']['evidence']['discrepancy_sha256']),
                             (found['instruction'], found['discrepancy_sha256']))
        self.assertIn('readings fixture-a/alpha-deep, fixture-a/alpha-swift; resolved fixture-a/alpha-swift; '
                      'now fixture-a/alpha-swift)', found['instruction'])
        decisions = h.root / h.view['study_id'] / 'focus-group' / 'identity'
        self.assertFalse(decisions.exists() and any(decisions.iterdir()))
        charged = h.charged()
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(h.charged(), charged)
        code, out = self.decide(fi, found['instruction'])
        self.assertEqual(code, 0, out)
        decision = out['data']['decision']
        self.assertEqual((decision['observed'], decision['discrepancy_sha256'], decision['discrepancy']['readings']),
                         (None, found['discrepancy_sha256'], found['readings']))
        stored = {p.name: p.read_bytes() for p in decisions.iterdir()}
        self.assertEqual(list(stored), [f"{fi}.{found['discrepancy_sha256'][:16]}.json"])
        # A repeated equivalent reading keeps the evidence, so the decision still applies; nothing is asked again.
        self.withdraw('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['identity_evidence']['discrepancy_sha256'], row['verified_coverage']),
                         ('owner-accepted-discrepancy', found['discrepancy_sha256'], False))
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        # A configuration source naming a third model is evidence that decision never covered.
        code, out = h.observe('fi-01', kind='identity', request_id='fi-01-r0', host_task_id=run['host'],
                              configuration_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-max'})
        self.assertEqual(code, 0, out)
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['problems'], row['identity_evidence']['reported_models']),
                         ('mismatched', ['identity_unverified'], ['alpha-deep', 'alpha-max', 'alpha-swift']))
        self.assertNotEqual(row['identity_evidence']['discrepancy_sha256'], found['discrepancy_sha256'])
        self.refused(self.decide(fi, found['instruction']), 'approval_scope_mismatch')
        self.assertEqual(self.disclosures()['analysis'][1]['error']['code'], 'disclosure_blocked')
        self.assertEqual({p.name: p.read_bytes() for p in decisions.iterdir()}, stored)
        # Model B: the status source names another model and then the requested one again. The shared handle
        # keeps one row per source, now equal to the request; the earlier reading stays in the evidence.
        for model in ('beta-two', 'beta-one'):
            self.withdraw('fi-02', 'fi-02-r0', other['host'],
                          status_identity={'providerInstanceId': 'fixture-b', 'model': model})
        row = self.cells()[h.cell(1)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((found['current_sources'], row['observed']['model'], row['identity'], found['reported_models']),
                         ({'status': {'providerInstanceId': 'fixture-b', 'model': 'beta-one'}}, 'beta-one', 'mismatched',
                          ['beta-one', 'beta-two']))
        self.refused(self.decide(fb, f'Accept observed model fixture-b/beta-one for focus-group cell {h.cell(1)} '
                                     'first-impression request fi-02-r0 (requested fixture-b/beta-one)'),
                     'approval_scope_mismatch')
        self.assertEqual(self.accepted_bytes(), records)

    def identify(self, task, request, host, **sources):
        code, out = self.h.observe(task, kind='identity', request_id=request, host_task_id=host, **sources)
        self.assertEqual(code, 0, out)

    def blocked_everywhere(self, record_sha):
        """Every disclosure consumer refuses the record, the pilot fails, and the model's next cell is refused
        without a charge."""
        h = self.h
        for consumer, (code, out) in self.disclosures().items():
            with self.subTest(consumer=consumer):
                self.assertEqual((code, out['error']['code']), (1, 'disclosure_blocked'), out)
                self.assertIn((record_sha, 'identity_unverified'),
                              {(p['record_sha256'], p['code']) for p in out['data']['material']})
        pilot = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}[
            (h.cell(0), 'first-impression')]
        self.assertEqual(pilot['state'], 'failed')
        charged = h.charged()
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual(h.charged(), charged)

    def test_r8_a_new_association_or_status_provider_withdraws_the_decision_and_its_quote(self):
        h = self.h
        h.start()
        run, other = h.first(0), h.first(1)
        fi = run['out']['data']['record_sha256']
        records = self.accepted_bytes()
        decisions = h.root / h.view['study_id'] / 'focus-group' / 'identity'
        # The reviewer's sequence: verified on fixture-a/alpha-swift, then a receipt naming fixture-b/alpha-deep.
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-deep'})
        before = self.cells()[h.cell(0)]['first-impression']['identity_evidence']
        self.assertEqual((before['kind'], before['canonical'], before['resolutions']),
                         ('contradictory', {'providerInstanceId': 'fixture-a', 'model': 'alpha-swift'},
                          [{'providerInstanceId': 'fixture-a', 'model': 'alpha-swift'}]))
        old_quote = before['instruction']
        self.assertIn('readings fixture-a/alpha-swift, fixture-b/alpha-deep; resolved fixture-a/alpha-swift; '
                      'now fixture-a/alpha-swift)', old_quote)
        self.assertEqual(self.decide(fi, old_quote)[0], 0)
        self.assertEqual(self.cells()[h.cell(0)]['first-impression']['identity'], 'owner-accepted-discrepancy')
        self.assertEqual(self.disclosures()['analysis'][0], 0)
        stored = {p.name: p.read_bytes() for p in decisions.iterdir()}
        # The same provider set and model set, paired the other way, and the status provider is now fixture-b.
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((before['reported_providers'], before['reported_models']),
                         (found['reported_providers'], found['reported_models']))
        self.assertNotEqual(found['discrepancy_sha256'], before['discrepancy_sha256'])
        self.assertEqual((row['identity'], row['problems'], found['observed'], found['canonical']),
                         ('mismatched', ['identity_unverified'], None,
                          {'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'}))
        self.assertEqual([(p['providerInstanceId'], p['model']) for p in found['associations']],
                         [('fixture-a', 'alpha-deep'), ('fixture-a', 'alpha-swift'), ('fixture-b', 'alpha-deep'),
                          ('fixture-b', 'alpha-swift')])
        self.assertEqual([(r['source'], r['providerInstanceId'], r['model']) for r in found['readings']],
                         [('status', 'fixture-a', 'alpha-swift'), ('receipt', 'fixture-b', 'alpha-deep'),
                          ('receipt', 'fixture-a', 'alpha-deep'), ('status', 'fixture-b', 'alpha-swift')])
        self.blocked_everywhere(fi)
        # The old owner quote no longer matches the evidence, so it cannot authorise it again.
        out = self.refused(self.decide(fi, old_quote), 'approval_scope_mismatch')
        self.assertEqual(out['data']['expected'], found['instruction'])
        self.assertIn('resolved fixture-a/alpha-swift, fixture-b/alpha-swift; now fixture-b/alpha-swift)',
                      found['instruction'])
        self.assertEqual({p.name: p.read_bytes() for p in decisions.iterdir()}, stored)
        # An equivalent repeat changes nothing and asks nothing.
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        self.assertEqual(self.cells()[h.cell(0)]['first-impression']['identity_evidence']['discrepancy_sha256'],
                         found['discrepancy_sha256'])
        # Only a fresh decision on exactly this evidence permits disclosed use again, never as verified.
        code, out = self.decide(fi, found['instruction'])
        self.assertEqual((code, out['data']['verified'], out['data']['decision']['observed'],
                          out['data']['decision']['discrepancy']['canonical']),
                         (0, False, None, found['canonical']), out)
        self.assertEqual(self.disclosures()['analysis'][0], 0)
        charged = h.charged()
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        self.assertEqual(h.charged(), {'first': charged['first'] + 1})
        # An unrelated slot change (model B's journey slot) keeps the decision; nothing is asked again.
        h.journey_ready(1)
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        row = self.cells()[h.cell(0)]['first-impression']
        self.assertEqual((row['identity'], row['identity_evidence']['discrepancy_sha256']),
                         ('owner-accepted-discrepancy', found['discrepancy_sha256']))
        self.assertEqual(self.accepted_bytes(), records)
        self.assertEqual(other['out']['data']['identity'], 'verified')

    def test_r9_incomplete_sources_never_make_an_observed_pair(self):
        h = self.h
        h.start()
        # The reviewer's case: a status model with no provider, then a receipt provider with no model.
        run = h.first(0, identity={'model': 'alpha-deep'})
        other = h.first(1, identity={'providerInstanceId': 'fixture-b'})
        self.assertEqual((run['code'], other['code']), (0, 0), (run['out'], other['out']))
        fi, fb = run['out']['data']['record_sha256'], other['out']['data']['record_sha256']
        records = self.accepted_bytes()
        self.identify('fi-01', 'fi-01-r0', run['host'], receipt_identity={'providerInstanceId': 'fixture-b'})
        row = self.cells()[h.cell(0)]['first-impression']
        found = row['identity_evidence']
        self.assertEqual((found['observed'], found['kind'], found['hold_code'], found['missing'], found['canonical'],
                          found['instruction']),
                         (None, None, 'identity_unreported', ['providerInstanceId'],
                          {'providerInstanceId': None, 'model': 'alpha-deep'}, None))
        self.assertEqual([(r['source'], r['providerInstanceId'], r['model']) for r in found['readings']],
                         [('status', None, 'alpha-deep'), ('receipt', 'fixture-b', None)])
        self.assertEqual(row['problems'], ['identity_unverified'])
        # Neither the pair no source reported nor the requested target can be accepted as what ran.
        for observed in ('fixture-b/alpha-deep', 'fixture-a/alpha-swift'):
            out = self.refused(self.decide(fi, f'Accept observed model {observed} for focus-group cell {h.cell(0)} '
                                               'first-impression request fi-01-r0 (requested fixture-a/alpha-swift)'),
                               'identity_unreported')
            self.assertIsNone(out['data']['evidence']['observed'])
        self.blocked_everywhere(fi)
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(0)}:first-impression'],
                         'accepted-unusable')
        code, out = h.call_evidence('brief', '--state-root', h.root, '--study', h.view['study_id'], '--input',
                                    h.write('r9-brief.json', {'revision': h.view['revision'], 'cell_id': h.cell(0),
                                                              'stage': 'journey', 'task_id': 'jr-01'}))
        self.assertEqual((code, out['error']['code']), (1, 'predecessor_unusable'), out)
        # Complementary readings the canonical rules do resolve: the status provider and a receipt model.
        self.identify('fi-02', 'fi-02-r0', other['host'], receipt_identity={'model': 'beta-two'})
        found = self.cells()[h.cell(1)]['first-impression']['identity_evidence']
        self.assertEqual((found['kind'], found['observed'], found['missing']),
                         ('wrong-model', {'providerInstanceId': 'fixture-b', 'model': 'beta-two'}, []))
        self.refused(self.decide(fb, f'Accept observed model fixture-b/beta-one for focus-group cell {h.cell(1)} '
                                     'first-impression request fi-02-r0 (requested fixture-b/beta-one)'),
                     'approval_scope_mismatch')
        self.assertEqual(self.decide(fb, found['instruction'])[0], 0)
        self.assertEqual(h.admit_slot(3, 'first-impression', 'fi-04-r0')[0], 0)
        # One complete receipt reading without the status provider the canonical rules need stays a hold.
        late = h.first(3, request='fi-04-r0', identity=None, admit=False)
        self.assertEqual(late['code'], 0, late['out'])
        self.identify('fi-04', 'fi-04-r0', late['host'],
                      receipt_identity={'providerInstanceId': 'fixture-b', 'model': 'beta-two'})
        found = self.cells()[h.cell(3)]['first-impression']['identity_evidence']
        self.assertEqual((found['observed'], found['hold_code'], found['missing']),
                         (None, 'identity_unreported', ['providerInstanceId']))
        self.refused(self.decide(late['out']['data']['record_sha256'], 'Accept observed model fixture-b/beta-two for '
                                 f'focus-group cell {h.cell(3)} first-impression request fi-04-r0 '
                                 '(requested fixture-b/beta-one)'), 'identity_unreported')
        after = self.accepted_bytes()
        self.assertEqual({k: after[k] for k in records}, records)

    def r10_admitted_then_invalidated(self, before_change=None):
        """The reviewer's R10 sequence: model A's pilot is accepted on fixture-a/alpha-swift, a receipt names
        fixture-b/alpha-deep, the owner accepts that exact contradiction, and fi-03-r0 is admitted (charged). Then
        a status fixture-b/alpha-swift and receipt fixture-a/alpha-deep reading changes the evidence, so the
        decision no longer applies and the pilot fails. Returns what later checks compare against."""
        h = self.h
        h.start()
        run, other = h.first(0), h.first(1)
        fi = run['out']['data']['record_sha256']
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      receipt_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-deep'})
        old_quote = self.cells()[h.cell(0)]['first-impression']['identity_evidence']['instruction']
        self.assertEqual(self.decide(fi, old_quote)[0], 0)
        out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
        self.assertEqual((out[0], out[1]['data']['charged']), (0, True), out)
        if before_change:
            before_change()
        self.identify('fi-01', 'fi-01-r0', run['host'],
                      status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                      receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        found = self.cells()[h.cell(0)]['first-impression']['identity_evidence']
        self.refused(self.decide(fi, old_quote), 'approval_scope_mismatch')
        pilot = {(p['pilot_cell'], p['stage']): p for p in h.lc_ok(*h.study('pilots'))['pilots']}[
            (h.cell(0), 'first-impression')]
        self.assertEqual((pilot['state'], pilot['reasons']), ('failed', ['identity mismatched']))
        return {'fi': fi, 'found': found, 'run': run, 'other': other, 'charged': h.charged(),
                'records': self.accepted_bytes(), 'ledger': json.loads(h.ledger_bytes())}

    def held_without_launch(self, base, state):
        """fi-03-r0 keeps its ID, charge and reservation, but nothing offers or permits starting it."""
        h = self.h
        out = self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_failed')
        self.assertEqual((out['data']['request_id'], out['data']['charged'], out['data']['pilot']['state']),
                         ('fi-03-r0', False, 'failed'))
        # Every new request for this model's cells stays held; the other model is not affected.
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-new'), 'pilot_failed')
        view = h.reconcile()
        row = next(r for r in view['requests'] if r['request_id'] == 'fi-03-r0')
        self.assertEqual((row['state'], row['ledger_state'], row['launch_hold']['code']), (state, 'open', 'pilot_failed'))
        self.assertEqual(view['actions']['dispatch_same_request'], [])
        self.assertEqual([(a['request_id'], a['clientRequestId'], a['code']) for a in view['actions']['launch_held']],
                         [('fi-03-r0', 'fi-03-r0', 'pilot_failed')])
        self.assertIn('fi-03-r0', view['unresolved'])
        resumed = h.resume()
        slot = {s['slot']: s for s in resumed['slots']}[f'{h.cell(2)}:first-impression']
        self.assertEqual((slot['state'], slot['code'], slot['requests'], resumed['blockers']),
                         ('held', 'pilot_failed', ['fi-03-r0'], []))
        self.assertEqual(resumed['reconciliation']['actions']['dispatch_same_request'], [])
        self.assertEqual(h.charged(), base['charged'])
        self.assertEqual(json.loads(h.ledger_bytes())['requests'], base['ledger']['requests'])
        self.assertEqual(self.accepted_bytes(), base['records'])

    def test_r10_an_open_request_never_prepared_waits_for_its_pilot_and_a_fresh_exact_decision_restores_it(self):
        h = self.h
        base = self.r10_admitted_then_invalidated()
        self.assertEqual(base['charged'], {'first': 3})
        self.held_without_launch(base, 'admitted-not-prepared')
        # A fresh decision on exactly the current evidence restores the pilot and the same charged ID, uncharged.
        code, out = self.decide(base['fi'], base['found']['instruction'])
        self.assertEqual((code, out['data']['verified']), (0, False), out)
        for _ in range(2):  # an equivalent reading, then an unrelated slot change, ask nothing again
            code, out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
            self.assertEqual((code, out['data']['duplicate'], out['data']['charged'], out['data']['host_started']),
                             (0, True, False, False), out)
            self.identify('fi-01', 'fi-01-r0', base['run']['host'],
                          status_identity={'providerInstanceId': 'fixture-b', 'model': 'alpha-swift'},
                          receipt_identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        h.journey_ready(1)
        self.assertEqual(h.admit_slot(2, 'first-impression', 'fi-03-r0')[0], 0)
        self.assertEqual(h.charged(), base['charged'])
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request']), ([], []))
        self.assertEqual(h.prepare('fi-03')['request_id'], 'fi-03-r0')
        self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                         [{'task_id': 'fi-03', 'request_id': 'fi-03-r0'}])
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(2)}:first-impression'],
                         'in-flight')
        self.assertEqual((h.charged(), self.accepted_bytes()), (base['charged'], base['records']))

    def test_r10_a_prepared_request_with_a_lost_response_is_held_but_its_started_task_is_still_owned(self):
        h = self.h

        def lost_response():
            h.prepare('fi-03')
            self.assertEqual(h.observe('fi-03', kind='uncertain', request_id='fi-03-r0')[0], 0)
            # While the pilot passes, a genuine response-loss retry keeps the same ID, uncharged.
            code, out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
            self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False), out)
            self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                             [{'task_id': 'fi-03', 'request_id': 'fi-03-r0'}])

        base = self.r10_admitted_then_invalidated(lost_response)
        self.held_without_launch(base, 'dispatch-uncertain')
        # The host finds the task the lost response started: it is owned work, read and ingested as usual.
        host = h.launch('fi-03', 'fi-03-r0', n=2)
        code, out = h.admit_slot(2, 'first-impression', 'fi-03-r0')
        self.assertEqual((code, out['data']['host_started'], out['data']['charged']), (0, True, False), out)
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request'],
                          view['actions']['task_status']),
                         ([], [], [{'host_task_id': host, 'request_id': 'fi-03-r0'}]))
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(2)}:first-impression'],
                         'in-flight')
        brief = json.loads(Path(self.task('fi-03')['brief']['path']).read_text())
        item = h.payload_file('fi-03', h.first_payload(h.view, h.cell(2), h.documents['fi-03']['sha256']))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('fi-03', 'fi-03-r0', host, 'done-fi-03-r0')[0], 0)
        self.assertEqual(h.deliver('fi-03', 'fi-03-r0', 'done-fi-03-r0', path)[0], 0)
        code, out = h.ingest('fi-03', 'fi-03-r0', 'done-fi-03-r0', path)
        self.assertEqual((code, out['data']['identity']), (0, 'verified'), out)
        view = h.reconcile()
        self.assertEqual(next(r for r in view['requests'] if r['request_id'] == 'fi-03-r0')['ledger_state'], 'terminal')
        self.assertEqual(h.charged(), base['charged'])

    def r11_admitted_then_old_host_reopens(self, before_reopen=None):
        """The reviewer's R11 sequence at max_concurrency 1: fi-01 is accepted and closed, fi-02-r0 is admitted while
        capacity is free (its reservation only), then a later reading of fi-01's host shows a pending descendant."""
        h = self.h
        h.start(limits=dict(json.loads(TEMPLATE.read_text())['limits'], max_concurrency=1))
        run = h.first(0)
        self.assertEqual(run['code'], 0, run['out'])
        out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((out[0], out[1]['data']['charged']), (0, True), out)
        # Its own reservation is the only occupied unit: never counted against its own start.
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged'], out['data']['host_started']),
                         (0, True, False, False), out)
        if before_reopen:
            before_reopen()
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', run['host'], None, pending=True, kind='reconciled')[0], 0)
        self.assertEqual(h.reconcile()['unresolved'], ['fi-01-r0', 'fi-02-r0'])
        return {'run': run, 'charged': h.charged(), 'records': self.accepted_bytes(),
                'ledger': json.loads(h.ledger_bytes())}

    def held_by_capacity(self, base, state):
        """fi-02-r0 keeps its ID, charge and reservation, but nothing offers or permits starting it."""
        h = self.h
        old = {'kind': 'host', 'host_task_id': base['run']['host'], 'request_id': 'fi-01-r0'}
        own = {'kind': 'reservation', 'host_task_id': None, 'request_id': 'fi-02-r0'}
        out = self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['occupied'], out['data']['occupied_count']), (['fi-01-r0', 'fi-02-r0'], 2))
        out = self.refused(h.admit_slot(1, 'first-impression', 'fi-02-r0'), 'concurrency_limit')
        self.assertEqual((out['data']['request_id'], out['data']['charged'], out['data']['occupied'],
                          out['data']['occupied_count'], out['data']['occupied_work'], out['data']['excluded']),
                         ('fi-02-r0', False, ['fi-01-r0'], 1, [old], own))
        view = h.reconcile()
        row = next(r for r in view['requests'] if r['request_id'] == 'fi-02-r0')
        self.assertEqual((row['state'], row['ledger_state'], row['launch_hold']['code'],
                          row['launch_hold']['occupied_work']), (state, 'open', 'concurrency_limit', [old]))
        self.assertEqual(view['actions']['dispatch_same_request'], [])
        self.assertEqual([(a['request_id'], a['clientRequestId'], a['code']) for a in view['actions']['launch_held']],
                         [('fi-02-r0', 'fi-02-r0', 'concurrency_limit')])
        self.assertEqual((view['actions']['task_status'], view['actions']['task_cancel']),
                         ([{'host_task_id': base['run']['host'], 'request_id': 'fi-01-r0'}], []))
        resumed = h.resume()
        slot = {s['slot']: s for s in resumed['slots']}[f'{h.cell(1)}:first-impression']
        self.assertEqual((slot['state'], slot['code'], slot['requests'], resumed['blockers']),
                         ('held', 'concurrency_limit', ['fi-02-r0'], []))
        self.assertEqual(resumed['reconciliation']['actions']['dispatch_same_request'], [])
        self.assertEqual(h.charged(), base['charged'])
        self.assertEqual(json.loads(h.ledger_bytes())['requests'], base['ledger']['requests'])
        self.assertEqual(self.accepted_bytes(), base['records'])

    def test_r11_a_never_prepared_request_waits_while_a_reopened_host_fills_capacity_and_starts_once_it_settles(self):
        h = self.h
        base = self.r11_admitted_then_old_host_reopens()
        self.assertEqual(base['charged'], {'first': 2})
        self.held_by_capacity(base, 'admitted-not-prepared')
        # Brief preparation now reserves shared job capacity. A denied reservation
        # changes neither the job nor the study's already charged request.
        before = h.job_state()
        code, error = h.job('prepare', {'caller': h.caller, 'task_id': 'fi-02'})
        self.assertEqual(code, 2)
        self.assertIn('admission_deferred: global_worker_limit', error)
        self.assertEqual(h.job_state(), before)
        self.held_by_capacity(base, 'admitted-not-prepared')
        # Only the old host's own terminal reading without pending runs frees it: the same ID then starts, uncharged.
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', base['run']['host'], None, kind='reconciled')[0], 0)
        self.assertEqual(h.prepare('fi-02')['request_id'], 'fi-02-r0')
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged'], out['data']['host_started']),
                         (0, True, False, False), out)
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request']),
                         ([], [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}]))
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(1)}:first-impression'],
                         'in-flight')
        # A fresh ID is still refused: the open request's reservation fills the limit.
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'concurrency_limit')
        self.assertEqual((h.charged(), self.accepted_bytes()), (base['charged'], base['records']))

    def test_r11_a_prepared_request_is_held_but_a_task_it_already_started_is_owned_and_ingested(self):
        h = self.h
        base = self.r11_admitted_then_old_host_reopens(lambda: h.prepare('fi-02'))
        self.held_by_capacity(base, 'prepared-not-dispatched')
        # The host finds a task this request already started: it is owned work, even above the limit, and is read,
        # completed and ingested as usual. It is never dispatched again or cancelled because capacity changed.
        host = h.launch('fi-02', 'fi-02-r0', n=1)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['host_started'], out['data']['charged']), (0, True, False), out)
        view = h.reconcile()
        self.assertEqual((view['actions']['launch_held'], view['actions']['dispatch_same_request'],
                          view['actions']['task_cancel'], view['actions']['task_status']),
                         ([], [], [], [{'host_task_id': base['run']['host'], 'request_id': 'fi-01-r0'},
                                       {'host_task_id': host, 'request_id': 'fi-02-r0'}]))
        self.assertEqual({s['slot']: s['state'] for s in h.resume()['slots']}[f'{h.cell(1)}:first-impression'],
                         'in-flight')
        brief = json.loads(Path(self.task('fi-02')['brief']['path']).read_text())
        item = h.payload_file('fi-02', h.first_payload(h.view, h.cell(1), h.documents['fi-02']['sha256']))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('fi-02', 'fi-02-r0', host, 'done-fi-02-r0')[0], 0)
        self.assertEqual(h.deliver('fi-02', 'fi-02-r0', 'done-fi-02-r0', path)[0], 0)
        code, out = h.ingest('fi-02', 'fi-02-r0', 'done-fi-02-r0', path)
        self.assertEqual((code, out['data']['identity']), (0, 'verified'), out)
        view = h.reconcile()
        self.assertEqual(next(r for r in view['requests'] if r['request_id'] == 'fi-02-r0')['ledger_state'], 'terminal')
        self.assertEqual(view['unresolved'], ['fi-01-r0'])
        self.assertEqual(h.charged(), base['charged'])

    def test_r11_a_lost_response_retry_waits_for_capacity_then_keeps_its_request_id(self):
        h = self.h

        def lost_response():
            h.prepare('fi-02')
            self.assertEqual(h.observe('fi-02', kind='uncertain', request_id='fi-02-r0')[0], 0)
            # While capacity is free, a genuine response-loss retry keeps the same ID, uncharged.
            code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
            self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False), out)
            self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                             [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}])

        base = self.r11_admitted_then_old_host_reopens(lost_response)
        self.held_by_capacity(base, 'dispatch-uncertain')
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', base['run']['host'], None, kind='reconciled')[0], 0)
        code, out = h.admit_slot(1, 'first-impression', 'fi-02-r0')
        self.assertEqual((code, out['data']['duplicate'], out['data']['charged']), (0, True, False), out)
        self.assertEqual(h.reconcile()['actions']['dispatch_same_request'],
                         [{'task_id': 'fi-02', 'request_id': 'fi-02-r0'}])
        host = h.launch('fi-02', 'fi-02-r0', n=1)
        self.assertEqual(next(r for r in h.reconcile()['requests'] if r['request_id'] == 'fi-02-r0')['state'], 'running')
        self.assertTrue(host)
        self.assertEqual(h.charged(), base['charged'])

    def test_r4_a_revised_study_moves_the_job_before_any_launch_and_never_duplicates_old_work(self):
        h = self.h
        h.start()
        self.assertEqual(h.first(0)['code'], 0)                      # model A's pilot, accepted in the old revision
        self.assertEqual(h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)
        h.prepare('fi-02')
        h.launch('fi-02', 'fi-02-r0', n=1)                           # model B's pilot, still running
        old_brief = self.task('fi-01')['brief']
        old_bytes, records, charged = Path(old_brief['path']).read_bytes(), self.accepted_bytes(), h.charged()
        old_doc = self.task('fi-02')['document']
        # The owner approves a protocol revision; its carry mapping is written and the pilot's new brief built.
        draft = h.draft()
        draft['personas'] = draft['personas'][:2]
        draft['prompts']['first_impression'] += ' Note one thing that works.'
        revised = h.plan(draft)
        h.approve(revised)
        h.ok('carry', '--state-root', h.root, '--study', revised['study_id'], '--write')
        h.view = revised
        document = h.document(0, 'first-impression', 'fi-01')
        # Until the job follows, resume reports nothing dispatchable and admission refuses, uncharged.
        resumed = h.resume()
        self.assertEqual(resumed['blockers'][0]['code'], 'job_revision_stale')
        self.assertNotIn('dispatchable', {s['state'] for s in resumed['slots']})
        self.refused(h.admit_slot(0, 'first-impression', 'fi-01-new'), 'job_revision_stale')
        self.assertEqual(h.charged(), charged)
        # job-revision lists each slot; the live old task's slot is held, never rewritten under it.
        listed = h.lc_ok(*h.study('job-revision'))
        states = {row['task_id']: row['state'] for row in listed['slots']}
        self.assertEqual((states['fi-01'], states['fi-02']), ('needs-brief', 'held-live'))
        out = h.lc_ok(*h.study('job-revision'), '--documents', h.write('revision-docs.json', {'fi-01': document}))
        self.assertTrue(out['changed'])
        self.assertEqual(out['decision_input']['decision']['quote'], revised['approval_instruction'])
        h.job_ok('decision', out['decision_input'])
        h.job_ok('plan-revision', out['plan_revision_input'])
        job = h.job_state()
        self.assertEqual({s['validator_contract']['study_revision'] for s in job['stages']}, {revised['revision']})
        self.assertEqual((self.task('fi-01')['document'], self.task('fi-02')['document']), (document, old_doc))
        self.assertEqual(self.task('fi-02')['handles'][0]['status'], 'running')
        self.assertEqual(h.lc_ok(*h.study('job-revision'), '--documents',
                                 h.write('again.json', {'fi-01': document}))['changed'], False)
        # Resume: the pilot slot is a charged retry, the live old pilot of model B is not duplicated.
        slots = {s['slot']: s for s in h.resume()['slots']}
        self.assertEqual(slots[f'{h.cell(0)}:first-impression']['state'], 'dispatchable')
        self.assertIn('charged retry', slots[f'{h.cell(0)}:first-impression']['next'])
        self.assertEqual((slots[f'{h.cell(1)}:first-impression']['state'],
                          slots[f'{h.cell(1)}:first-impression']['code']), ('held', 'job_slot_stale'))
        h.job_ok('retry', {'caller': h.caller, 'task_id': 'fi-01', 'reason': 'protocol revision'})
        request = self.task('fi-01')['request_id']
        code, admitted = h.admit_slot(0, 'first-impression', request)
        self.assertEqual((code, admitted['data']['charged']), (0, True), admitted)
        brief = h.prepare('fi-01')
        self.assertEqual((brief['document'], brief['request_id']), (document, request))
        self.assertEqual(self.task('fi-01')['target'], {k: revised['cells'][0][k] for k in
                                                       ('providerInstanceId', 'model', 'options')})
        # The old brief, accepted record, request history and charges are kept; nothing was reset.
        self.assertEqual((Path(old_brief['path']).read_bytes(), self.accepted_bytes()), (old_bytes, records))
        self.assertIn('fi-01-r0', self.task('fi-01')['retired_request_ids'])
        self.assertEqual(h.charged(), {'first': charged['first'] + 1})

    def test_r5_direct_record_acceptance_never_stands_in_for_host_ingestion_once_a_job_exists(self):
        h = self.h
        h.start()
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        h.prepare('fi-01')
        h.launch('fi-01', 'fi-01-r0', identity={'providerInstanceId': 'fixture-a', 'model': 'alpha-deep'})
        item = h.payload_file('fi-01', h.first_payload(h.view, h.cell(0), h.documents['fi-01']['sha256']))
        record = {'revision': h.view['revision'], 'cell_id': h.cell(0), 'stage': 'first-impression', 'task_id': 'fi-01',
                  'request_id': 'fi-01-r0', 'result': {'path': str(h.root / h.view['study_id'] / item['path']),
                                                       'sha256': item['sha256']},
                  'observed': {'providerInstanceId': 'fixture-a', 'model': 'alpha-swift', 'source': 'a supplied claim'},
                  'predecessors': [], 'context': None, 'image_delivery': DELIVERED}
        h.refused('host_ingest_required', 'record-acceptance', '--state-root', h.root, '--study', h.view['study_id'],
                  '--input', h.write('direct.json', record))
        self.assertEqual(self.accepted_bytes(), {})
        pilots = {(p['pilot_cell'], p['stage']): p['state'] for p in h.lc_ok(*h.study('pilots'))['pilots']}
        self.assertEqual(pilots[(h.cell(0), 'first-impression')], 'running')
        self.refused(h.admit_slot(2, 'first-impression', 'fi-03-r0'), 'pilot_pending')

    def test_r6_a_delayed_completion_offered_with_an_aged_catalog_is_retained_logged_and_later_accepted(self):
        h = self.h
        h.start()
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        brief = h.prepare('fi-01')
        host = h.launch('fi-01', 'fi-01-r0')
        item = h.payload_file('fi-01', h.first_payload(h.view, h.cell(0), h.documents['fi-01']['sha256']))
        path = h.transport(h.worker_result(brief, [item]))
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, 'late')[0], 0)
        self.assertEqual(h.deliver('fi-01', 'fi-01-r0', 'late', path)[0], 0)
        late = '2029-06-01T00:30:00Z'                                # the catalog saved at BEFORE is now too old
        code, out = h.ingest('fi-01', 'fi-01-r0', 'late', path, now=late, catalog=h.catalog(BEFORE))
        self.assertEqual((code, out['error']['code'], out['data']['category'], out['data']['product_friction']),
                         (1, 'stale_observation', 'lifecycle', False))
        raw = h.root / h.view['study_id'] / 'focus-group' / out['data']['raw_retained']
        self.assertEqual(raw.read_bytes(), path.read_bytes())
        self.assertEqual([(r['outcome'], r['code']) for r in h.session('fi-01-r0')], [('refused', 'stale_observation')])
        self.assertEqual(self.accepted_bytes(), {})
        # The same retained completion is ingested once a fresh observation is saved.
        code, out = h.ingest('fi-01', 'fi-01-r0', 'late', path, now=late, catalog=h.catalog(late))
        self.assertEqual((code, out['data']['identity']), (0, 'verified'), out)
        self.assertEqual([r['outcome'] for r in h.session('fi-01-r0')], ['refused', 'accepted'])

    def test_n1_cancel_without_a_recorded_host_handle_names_the_request_and_never_invents_its_end(self):
        h = self.h
        h.start()
        self.assertEqual(h.admit_slot(0, 'first-impression', 'fi-01-r0')[0], 0)
        h.prepare('fi-01')                                           # prepared: a lost response may have started it
        self.assertEqual(h.admit_slot(1, 'first-impression', 'fi-02-r0')[0], 0)   # admitted, never prepared
        charged = h.charged()
        cancel = h.ok('cancel', '--state-root', h.root, '--study', h.view['study_id'])
        self.assertEqual((cancel['cancellation_confirmed'], cancel['cancel'], cancel['task_cancel']),
                         (False, ['fi-01-r0'], []))
        self.assertEqual([{k: r[k] for k in ('task_id', 'request_id', 'clientRequestId', 'state')}
                          for r in cancel['rediscover']],
                         [{'task_id': 'fi-01', 'request_id': 'fi-01-r0', 'clientRequestId': 'fi-01-r0',
                           'state': 'prepared-not-dispatched'}])
        ledger = json.loads(h.ledger_bytes())['requests']
        self.assertEqual((ledger['fi-02-r0']['state'], ledger['fi-02-r0']['terminal_kind']), ('terminal', 'never-prepared'))
        self.assertEqual(ledger['fi-01-r0']['state'], 'cancel-requested')
        view = h.reconcile()
        self.assertEqual((view['actions']['dispatch_same_request'], view['unresolved']), ([], ['fi-01-r0']))
        self.assertEqual(h.status(h.view)['cancel_pending_confirmation'], ['fi-01-r0'])
        # The host finds the task by its clientRequestId: the existing accepted observation records it.
        host = h.launch('fi-01', 'fi-01-r0')
        view = h.reconcile()
        self.assertEqual((view['actions']['task_cancel'], view['actions']['rediscover']),
                         ([{'host_task_id': host, 'request_id': 'fi-01-r0'}], []))
        self.assertEqual(h.complete('fi-01', 'fi-01-r0', host, None, status='cancelled', kind='reconciled')[0], 0)
        self.assertTrue(h.reconcile()['cancellation_confirmed'])
        # A brief prepared later for the closed request reopens it: the closure never hides recorded work.
        h.prepare('fi-02')
        view = h.reconcile()
        self.assertEqual((view['cancellation_confirmed'], view['unresolved'],
                          [r['request_id'] for r in view['actions']['rediscover']]), (False, ['fi-02-r0'], ['fi-02-r0']))
        self.assertEqual(h.charged(), charged)



if __name__ == '__main__':
    unittest.main()


def load_tests(loader, tests, pattern):
    from tests.module_partition import partition
    return partition(loader, ReviewRoundTest, 0)
