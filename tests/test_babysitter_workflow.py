"""Babysitter coordinator adapter (issue #28 Stage 4).

Behavioural checks for the rebuilt entry, playbook, job-plan reference and the two
worker definitions, plus synthetic jobs driven only through the installed
job_cli.py / job_acceptance_cli.py helpers and the pinned validate_pr.py. Isolated
HOME/XDG roots, synthetic host observations and worker results; no live model and
no GitHub call.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs.store import canonical  # noqa: E402

PLUGIN = ROOT / 'plugins' / 'babysitter'
WORKHORSE = {'providerInstanceId': 'fixture-workhorse', 'model': 'fixture-small', 'lineage': 'lineage-a'}
REVIEWER = {'providerInstanceId': 'fixture-reviewer', 'model': 'fixture-review', 'lineage': 'lineage-b'}
PR12, PR13 = 'https://github.com/fixture/widgets/pull/12', 'https://github.com/fixture/widgets/pull/13'
H1, H2, H3 = '1' * 40, '2' * 40, '3' * 40


def norm(value):
    return ' '.join(value.split())


def text(rel):
    return norm((PLUGIN / rel).read_text())


def sections(rel):
    """Map each '## ' heading of a Markdown file to its whitespace-normalised body."""
    found, current = {}, None
    for line in (PLUGIN / rel).read_text().splitlines():
        if line.startswith('## '):
            current = line[3:].strip()
            found[current] = []
        elif current:
            found[current].append(line)
    return {key: norm('\n'.join(value)) for key, value in found.items()}


def steps(rel):
    """Numbered top-level steps of a playbook, whitespace-normalised."""
    raw = (PLUGIN / rel).read_text()
    parts = re.split(r'\n(\d+)\. ', '\n' + raw)
    return {int(number): norm(body) for number, body in zip(parts[1::2], parts[2::2])}


class EntryRoutingTest(unittest.TestCase):
    def test_every_operation_keeps_its_name_meaning_and_route(self):
        meta = json.loads((PLUGIN / 'plugin.json').read_text())
        self.assertEqual(meta['operations'], ['doctor', 'pr', 'repo', 'org'])
        ops = (PLUGIN / 'entry.md').read_text().split('## Operations')[1].split('\n## ')[0]
        bullets = {re.match(r'`([^`]+)`', b).group(1): norm(b) for b in ops.split('\n- ')[1:]}
        self.assertEqual(set(bullets), {'doctor', 'pr <URL>', 'repo <owner/name>', 'org <owner>'})
        for op, meaning in (('doctor', 'GitHub authentication'), ('pr <URL>', 'one pull request'),
                            ('repo <owner/name>', 'eligible open PRs in one repository'),
                            ('org <owner>', 'eligible open PRs across an organization')):
            self.assertIn(meaning, bullets[op])
        route = sections('entry.md')['Operations']
        self.assertIn('For `pr`, `repo`, and `org`, read `PKG/playbooks/maintain.md`', route)
        # Every PKG file named by the entry, playbook or reference exists in the source tree.
        named = set(re.findall(r'`PKG/([\w./-]+)`', text('entry.md') + text('playbooks/maintain.md')
                               + text('references/job-plan.md')))
        self.assertIn('references/job-plan.md', named)
        for name in named - {'shared/job-coordination.md'}:  # written by the shared Stage 4 owner
            self.assertTrue((PLUGIN / name).exists() or (ROOT / name).exists(), name)

    def test_entry_references_coordination_protocol_without_duplicating_it(self):
        entry = text('entry.md')
        for required in ('PKG/shared/job-coordination.md', 'PKG/shared/t3-runtime.md',
                         'PKG/shared/delegation.md', 'PKG/shared/learnings.md'):
            self.assertIn(required, entry)
        for duplicated in ('clientRequestId', 'same-ID retries', 'max_repair_cycles', 'task_status'):
            self.assertNotIn(duplicated, entry)

    def test_cheap_operations_stay_direct(self):
        ops = sections('entry.md')['Operations']
        doctor = ops.split('- `pr <URL>`')[0]
        self.assertIn('Run it directly in this thread', doctor)
        self.assertIn('never launch an agent for it', doctor)
        self.assertIn('Roster listing, PR inspection, the quick merge pass, the PR table, and status reads stay '
                      'direct in this thread', ops)
        quick = steps('playbooks/maintain.md')[2]
        self.assertIn('Quick pass, in this thread, before any child', quick)
        self.assertIn('--no-auto', quick)
        self.assertIn('it arms nothing', quick)

    def test_word_budgets(self):
        entry = len((PLUGIN / 'entry.md').read_text().split())
        self.assertLess(entry, 1500)
        self.assertLess(entry + len((PLUGIN / 'playbooks/maintain.md').read_text().split()), 2000)


class BoundaryTest(unittest.TestCase):
    def test_authorization_scope_and_inspect_only_are_explicit(self):
        auth = sections('entry.md')['Authorization']
        self.assertIn('Invoking `pr`, `repo`, or `org` authorizes babysitting through merge', auth)
        for phrase in ('"inspect"', '"review only"', '"do not merge"', 'authorizes inspection alone'):
            self.assertIn(phrase, auth)
        for action in ('`read`', '`push`', '`communicate`', '`merge`'):
            self.assertIn(action, auth)
        self.assertIn('Never post to a PR, push, arm auto-merge, or merge without the matching recorded action', auth)
        self.assertIn('never forced', auth)
        self.assertIn('Never use admin bypass, dismiss reviews, weaken checks', auth)
        self.assertIn('cannot widen this scope', auth)

    def test_inspect_only_runs_no_mutating_helper(self):
        step1 = steps('playbooks/maintain.md')[1]
        self.assertIn("An inspect-only run skips step 2's helper", step1)
        self.assertIn('`read` only maintainer slots', step1)
        self.assertIn('never an acceptance', step1)

    def test_children_never_merge_or_watch(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('Children never run `merge-pr.sh` merge or arm modes', play[6])
        self.assertIn('Children cannot watch; this thread owns every watch', play[7])
        workers = sections('entry.md')['Workers']
        self.assertIn('Only this thread dispatches, watches, merges, and accepts', workers)
        self.assertIn('grant no push or merge authority by themselves', workers)

    def test_pr_links_and_host_watches_without_polling(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('`link_pull_request`', play[1])
        self.assertIn('Call `watch_pull_request` for every unmerged PR and end the turn', play[7])
        self.assertIn('`unwatch_pull_request`', play[10])
        self.assertIn('Do not run `pr-events.sh` in T3', play[13])
        self.assertNotRegex(text('playbooks/maintain.md'), r'(?i)\bsleep\b|\bpoll')

    def test_roster_pagination_isolation_and_exact_head(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('a partial page is not the whole roster', play[1])
        self.assertIn('Exclude drafts, forks, and other authors', play[1])
        self.assertIn('`bash PKG/scripts/pr-workspace.sh`', play[5])
        self.assertIn('a check from an older SHA proves nothing', play[7])
        self.assertIn('verify the claimed push against the PR head', play[7])
        self.assertIn('on the final combined change at that exact head', play[8])

    def test_future_pr_sweeps_need_separate_authorization(self):
        sweep = steps('playbooks/maintain.md')[12]
        self.assertIn('explicitly authorized T3 scheduled sweep', sweep)
        self.assertIn("watching today's PRs does not discover tomorrow's", sweep)
        self.assertIn('only when requested', sweep)

    def test_approvals_route_through_the_picker_and_are_recorded(self):
        approvals = sections('entry.md')['Approvals']
        for phrase in ('native question picker', 'recommended option first', '`job_cli.py decision`',
                       'silence is not approval'):
            self.assertIn(phrase, approvals)
        play = steps('playbooks/maintain.md')
        self.assertIn('ask the operator through the question picker before fanning out', play[5])
        self.assertIn('More rounds need an owner decision through the picker', play[9])
        self.assertIn('ask through the question picker', sections('references/job-plan.md')['Head changes'])

    def test_validator_is_the_acceptance_authority(self):
        acceptance = sections('entry.md')['Acceptance']
        self.assertIn('`PKG/scripts/validate_pr.py` is the authority', acceptance)
        for claim in ('terminal task', 'older-head check', 'queued auto-merge'):
            self.assertIn(claim, acceptance)
        stages = sections('references/job-plan.md')['Stages']
        for field in ('pr', 'head_sha', 'required_contexts', 'optional_contexts',
                      'allow_empty_required_contexts', 'authorized_endstate'):
            self.assertIn(f'`{field}`', stages)
        self.assertIn('never from a worker result', sections('references/job-plan.md')['Acceptance input'])

    def test_missing_reviewer_and_fallback_stay_visible(self):
        fallback = steps('playbooks/maintain.md')[11]
        self.assertIn('visible fallback marker', fallback)
        self.assertIn('A missing independent reviewer stays a blocker', fallback)

    def test_master_quick_pass_table_and_fixers_survive(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('| PR | Description | Not merged because |', play[3])
        self.assertIn('Post the whole table again each time a PR merges', play[3])
        self.assertIn('`t3-plugins resolve workhorse --capabilities FILE --repo <that worktree>`', play[5])
        self.assertIn('cheapest configured tier', play[5])
        self.assertIn('`needs human:`', play[9])
        self.assertIn('`automerge=preexisting`', play[2])
        self.assertIn("For a PR that is not review-gated, rerun step 2's helper first", play[7])


class WorkerDefinitionTest(unittest.TestCase):
    def test_definitions_satisfy_the_worker_contract(self):
        meta = json.loads((PLUGIN / 'plugin.json').read_text())
        self.assertEqual({w['id'] for w in meta['workers']}, {'babysitter/pr-maintainer', 'babysitter/pr-reviewer'})
        for worker in meta['workers']:
            raw = (PLUGIN / worker['path']).read_text()
            body = norm(raw)
            with self.subTest(worker=worker['id']):
                self.assertTrue(raw.startswith(f'---\nworker_id: {worker["id"]}\n'))
                for phrase in ('brief path', 'SHA-256', 'Do not dispatch children', 'accept your own work',
                               'exactly one JSON object', 'worker-result.schema.json', '`ready-for-acceptance`',
                               '`needs-followup`', '`blocked`', '`failed`', '`severity`', '`source_evidence`',
                               'Redact', 'never look for another copy or installation'):
                    self.assertIn(phrase, body)
                self.assertNotRegex(body, r'(?i)\b(claude|gpt|gemini|opus|sonnet|haiku|luna)[-\w.]*\d')
                self.assertRegex(body, r'(?i)never push')

    def test_maintainer_is_scoped_and_read_only_triage_may_block(self):
        body = text('agents/pr-maintainer.md')
        for phrase in ('one PR, in its isolated worktree', 'exact head', 'Read-only triage may finish `blocked` with '
                       'named blockers', 'Never force-push', 'Without `push` you never push',
                       'Never merge, arm or disable auto-merge', '`review_verdict` is `null`'):
            self.assertIn(phrase, body)

    def test_reviewer_is_independent_and_read_only(self):
        body = text('agents/pr-reviewer.md')
        for phrase in ('final combined changes', 'independently of the maintainer', '`approve`', '`adverse`',
                       'any blocker or major finding forces `adverse`',
                       'Do not edit, commit, push, post, resolve threads, or merge'):
            self.assertIn(phrase, body)


def documented_plan(head12=H1, head13=H3, installation_id='fixture-installation'):
    """The example job plan from references/job-plan.md, with its placeholders filled."""
    raw = (PLUGIN / 'references/job-plan.md').read_text().split('```json\n', 1)[1].split('\n```', 1)[0]
    for placeholder, value in (('"<workhorse-target>"', json.dumps(WORKHORSE)), ('"<reviewer-target>"', json.dumps(REVIEWER)),
                               ('<job-id>', 'bs-1'), ('<installation-id>', installation_id),
                               ('<pr-12-url>', PR12), ('<pr-13-url>', PR13), ('<decision-id>', 'owner-invocation'),
                               ('<head-12-short>', head12[:12]), ('<head-13-short>', head13[:12]),
                               ('<head-12>', head12), ('<head-13>', head13)):
        raw = raw.replace(placeholder, value)
    if '<' in raw:
        raise AssertionError('unfilled placeholder in the documented plan: ' + re.search(r'<[^>]*>', raw).group(0))
    return json.loads(raw)


def merge_gate_violations(plan):
    """Every way a plan lets a merge-capable stage run before its PR's review stage is accepted.

    A stage holding a review slot is a review stage. It must not request `merged`, and every stage
    of the same PR that requests `merged` must depend on it (transitively). A PR whose fixer slot
    may push needs a review slot, so every such PR is review-gated.
    """
    stages = {s['id']: s for s in plan['stages']}
    def ancestors(stage_id, seen=None):
        seen = set() if seen is None else seen
        for dep in stages[stage_id].get('depends_on', []):
            if dep not in seen:
                seen.add(dep)
                ancestors(dep, seen)
        return seen
    pr_of = {sid: s['validator_contract']['pr'] for sid, s in stages.items()}
    requested = {sid: s['validator_contract']['authorized_endstate']['requested'] for sid, s in stages.items()}
    review_stages = {t['stage_id'] for t in plan['tasks'] if t.get('role') == 'review'}
    violations = []
    for task in plan['tasks']:
        pr = pr_of[task['stage_id']]
        if (task.get('role', 'worker') == 'worker' and 'push' in plan['authorization']['prs'].get(pr, [])
                and not task.get('review_task_ids')):
            violations.append(f'{task["task_id"]}: a push-authorized fixer has no independent review slot')
    for review in sorted(review_stages):
        if requested[review] == 'merged':
            violations.append(f'{review}: a review stage requests merged, so it merges before its own acceptance')
        for sid in sorted(stages):
            if sid != review and pr_of[sid] == pr_of[review] and requested[sid] == 'merged' and review not in ancestors(sid):
                violations.append(f'{sid}: merges {pr_of[sid]} without depending on review stage {review}')
    return violations


class MergeGatePlanTest(unittest.TestCase):
    def test_documented_plan_merges_only_after_review(self):
        self.assertEqual(merge_gate_violations(documented_plan()), [])

    def test_gate_checker_rejects_every_early_merge_shape(self):
        mutations = {
            'land stage without the review dependency': lambda p: p['stages'][1].update(depends_on=[]),
            'review stage requesting merged': lambda p: p['stages'][0]['validator_contract']['authorized_endstate'].update(
                requested='merged', observed='merged'),
            'fixer without a review slot': lambda p: p['tasks'][0].pop('review_task_ids'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                plan = documented_plan()
                mutate(plan)
                self.assertNotEqual(merge_gate_violations(plan), [])

    def test_gate_is_stated_where_the_coordinator_reads_it(self):
        gate = sections('entry.md')['Review gate']
        self.assertIn('no merge-capable call happens until its review stage is accepted by `validate_pr.py` at the '
                      'exact current head', gate)
        self.assertIn('`--no-auto` (it still merges a CLEAN PR)', gate)
        self.assertIn('never dispatched while the PR has an auto-merge request', gate)
        self.assertIn('A review-gated PR gets no helper run on a wake until its review stage is accepted',
                      steps('playbooks/maintain.md')[7])
        self.assertIn('Only after a review stage is accepted', steps('playbooks/maintain.md')[10])
        self.assertIn('No stage that holds a `review` slot may request `merged`', sections('references/job-plan.md')['Stages'])


class SyntheticJobTest(unittest.TestCase):
    """The documented plan driven through the installed helpers: fixer, review gate, land, final acceptance."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.base = Path(self.tmp.name)
        (base / 'home').mkdir()
        self.env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_CONFIG_HOME': str(base / 'config'),
                    'XDG_STATE_HOME': str(base / 'xdg-state')}
        self.prefix, self.agents, self.state = base / 'prefix', base / 'agents', base / 'state'
        proc = subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'), '--plugin', 'babysitter',
                               '--prefix', str(self.prefix), '--agents-root', str(self.agents)],
                              capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.version = Path(json.loads(proc.stdout)['data']['version_dir'])
        manifest = json.loads((self.version / 'install-manifest.json').read_text())
        self.caller = {'installation_id': manifest['installation_id'], 'workflow': 'babysitter/repo',
                       'package_digest': manifest['package_digest'], 'actor': 'coordinator'}
        # The operator's verbatim request, saved outside the job directory and every worktree.
        (base / 'owner').mkdir()
        self.request = base / 'owner' / 'request.txt'
        self.request.write_text('/t3-babysitter repo fixture/widgets\n')
        self.counter = 0

    # -- helpers -----------------------------------------------------------------------------
    def plan(self, head12=H1):
        return documented_plan(head12=head12, installation_id=self.caller['installation_id'])

    def run_cli(self, script, command, payload=None, ok=True):
        argv = [sys.executable, str(self.version / 'shared' / script), command,
                '--state-root', str(self.state), '--job', 'bs-1']
        if command == 'create':
            argv += ['--prefix', str(self.prefix), '--agents-root', str(self.agents),
                     '--config', str(self.base / 'config/workers.json')]
        if payload is not None:
            self.counter += 1
            path = self.base / f'input-{self.counter}.json'
            path.write_text(json.dumps(payload))
            argv += ['--input', str(path)]
        proc = subprocess.run(argv, capture_output=True, text=True, env=self.env, timeout=120)
        if ok:
            self.assertEqual(proc.returncode, 0, f'{command}: {proc.stdout}{proc.stderr}')
            return json.loads(proc.stdout)
        return proc

    def job(self, command, payload=None, ok=True):
        return self.run_cli('job_cli.py', command, payload, ok)

    def observe(self, task_id, kind, request, host):
        event = {'kind': kind, 'request_id': request, 'host_task_id': host, 'child_thread_id': 'thread-' + host,
                 'status': 'running', 'work_state': 'working', 'has_pending_child_runs': False}
        if kind == 'completion':
            event.update(status='completed', work_state='result_available', completion_id=host + '-done')
        return self.job('task-observation', {'caller': self.caller, 'task_id': task_id, 'event': event})

    def dispatch(self, task_id, *, status='ready-for-acceptance', verdict=None, findings=(), changes=()):
        """prepare -> (synthetic delegate_task) -> accepted handle -> result -> completion, via the CLI."""
        self.counter += 1
        host = f'host-{task_id}-{self.counter}'
        ref = self.job('prepare', {'caller': self.caller, 'task_id': task_id, 'target_reason': 'cheapest suitable tier'})
        self.assertLessEqual({'path', 'sha256', 'bytes'}, set(ref))
        raw = Path(ref['path']).read_bytes()
        self.assertEqual((hashlib.sha256(raw).hexdigest(), len(raw)), (ref['sha256'], ref['bytes']))
        brief = json.loads(raw)
        self.observe(task_id, 'accepted', brief['request_id'], host)
        failed = status != 'ready-for-acceptance'
        result = {'schema_version': 1, **{k: brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id',
                                                                 'worker_id', 'effective_brief_sha256', 'revision')},
                  'status': status, 'conclusion': 'synthetic fixture result',
                  'requirements': [{'id': r['id'], 'status': 'failed' if failed else 'passed',
                                    'evidence': ['fixture evidence']} for r in brief['requirements']],
                  'review_verdict': verdict, 'findings': list(findings), 'gaps': [], 'uncertainties': [],
                  'changes': list(changes), 'commands': [], 'artifacts': [], 'binding': brief['snapshot'],
                  'extra_work_requests': [], 'metrics': {}}
        self.job('result', {'caller': self.caller, 'task_id': task_id, 'request_id': brief['request_id'],
                            'completion_id': host + '-done', 'result': {'json': json.dumps(result)}})
        self.observe(task_id, 'completion', brief['request_id'], host)
        return brief

    def stage_contract(self, stage_id):
        return next(s for s in self.job('overview')['stages'] if s['id'] == stage_id)['validator_contract']

    def publish(self, stage_id, *, head=None, check_head=None, conclusion='success', endstate=None):
        """A coordinator host read of the PR, content-bound as validate_pr.py requires."""
        contract = self.stage_contract(stage_id)
        head = head or contract['head_sha']
        data = {**contract, 'head_sha': head,
                'required_checks': [{'context': 'ci', 'conclusion': conclusion, 'head_sha': check_head or head}],
                'review_threads': [{'resolved': True, 'head_sha': head}]}
        data['authorized_endstate'] = dict(data['authorized_endstate'],
                                           observed=endstate or data['authorized_endstate']['requested'])
        content = {k: data[k] for k in ('pr', 'head_sha', 'required_contexts', 'required_checks', 'review_threads',
                                        'authorized_endstate', 'allow_empty_required_contexts', 'optional_contexts')}
        data['host_observations'] = [{'observer': 'coordinator', 'kind': 'pr-state', 'source': 'fixture host read',
                                      'content': content, 'sha256': hashlib.sha256(canonical(content)).hexdigest()}]
        self.counter += 1
        path = self.base / f'{stage_id}-observation-{self.counter}.json'
        path.write_text(json.dumps(data))
        return self.job('observation', {'caller': self.caller, 'stage_id': stage_id, 'input_file': str(path)})['path']

    def accept(self, stage_id, **observed):
        published = self.publish(stage_id, **observed)
        argv = [str(self.version / 'scripts' / 'validate_pr.py'), '--input', published]
        revision = next(s for s in self.job('overview')['stages'] if s['id'] == stage_id).get('revision')
        proc = self.run_cli('job_acceptance_cli.py', 'accept-stage', {
            'caller': self.caller, 'stage_id': stage_id, 'validator_argv': argv,
            'input_file': published, 'revision': revision}, ok=False)
        return proc, argv, published

    def rebind_head(self, revision_id, head):
        """A verified push inside recorded authority moves the head: owner-sourced plan revision."""
        self.job('decision', {'caller': self.caller, 'decision': {
            'id': 'owner-' + revision_id, 'quote': self.request.read_text().strip(), 'source': str(self.request),
            'source_sha256': hashlib.sha256(self.request.read_bytes()).hexdigest(), 'scope': 'plan:' + revision_id}})
        return self.job('plan-revision', {'caller': self.caller, 'new_plan': {'stages': [{k: v for k, v in stage.items() if k != 'status'}
                                                                  for stage in self.plan(head)['stages']]},
                                          'revision': {'id': revision_id, 'owner_decision_id': 'owner-' + revision_id}})

    def statuses(self):
        overview = self.job('overview')
        return ({s['id']: s['status'] for s in overview['stages']},
                {h['task_id']: h['status'] for h in overview['handles']})

    def merge_allowed(self, stage_id):
        """The land stage's merge-capable step may run only once its review dependency holds current acceptance."""
        stages = {s['id']: s for s in self.job('overview')['stages']}
        return all(stages[dep]['status'] == 'accepted-at-snapshot' for dep in stages[stage_id]['depends_on'])

    # -- scenarios ---------------------------------------------------------------------------
    def test_fix_review_gate_land_and_final_acceptance_at_exact_heads(self):
        self.job('create', self.plan())
        self.assertEqual(set(self.statuses()[0].values()), {'pending'})
        self.assertFalse(self.merge_allowed('pr-12-land'))

        # A merge observed before the review stage is accepted can never land the stage.
        early, *_ = self.accept('pr-12-land')
        self.assertNotEqual(early.returncode, 0)
        self.assertIn('dependency lacks current authoritative acceptance', early.stderr + early.stdout)

        # The reviewer cannot be prepared before the maintainer's execution exists.
        self.assertNotEqual(self.job('prepare', {'caller': self.caller, 'task_id': 'pr-12-review'}, ok=False).returncode, 0)

        # Pass 0: the maintainer fixes the failing check and pushes H2. Its brief carries the recorded actions.
        brief = self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H2}])
        self.assertEqual(brief['authorization']['prs'][PR12], ['read', 'push', 'communicate', 'merge'])
        self.assertIn('worker_id: babysitter/pr-maintainer', json.dumps(brief['effective_definition']))

        # The worker's claim is not acceptance: the stage still binds H1, so an H2 read is refused.
        self.assertNotEqual(self.accept('pr-12', head=H2)[0].returncode, 0)

        # The coordinator verified the push, rebinds review and land stages, and reruns the maintainer (pass 1).
        self.rebind_head('head-h2', H2)
        self.assertEqual(self.statuses()[0]['pr-12'], 'stale')
        self.assertEqual(self.stage_contract('pr-12-land')['head_sha'], H2)
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'head moved to the pushed fix'})
        self.dispatch('pr-12-maintain')

        # An adverse independent review blocks the review stage, so the land stage still cannot merge.
        finding = {'id': 'R1', 'severity': 'major', 'scenario': 'the fix drops input validation',
                   'source_evidence': ['src/widget.py at ' + H2]}
        self.dispatch('pr-12-review', verdict='adverse', findings=[finding])
        self.assertNotEqual(self.accept('pr-12')[0].returncode, 0)
        self.assertFalse(self.merge_allowed('pr-12-land'))
        self.assertNotEqual(self.accept('pr-12-land')[0].returncode, 0)
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'review finding R1'})
        self.dispatch('pr-12-maintain')
        evidence = self.base / 'owner' / 'r1-fixed.txt'
        evidence.write_text('validation restored; fixture test passes at ' + H2 + '\n')
        self.job('finding-disposition', {'caller': self.caller, 'task_id': 'pr-12-review', 'finding_id': 'R1',
                                         'disposition': 'fixed', 'evidence': {
                                             'path': str(evidence), 'bytes': evidence.stat().st_size,
                                             'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}})
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-review', 'reason': 'fresh review round',
                           'category': 'review'})
        self.dispatch('pr-12-review', verdict='approve')

        # A check from the older head proves nothing; the refused pass stays charged.
        refused, *_ = self.accept('pr-12', check_head=H1)
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertNotEqual(self.accept('pr-12')[0].returncode, 0)  # next pass needs a charged repair
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'checks rerun at head'})
        self.dispatch('pr-12-maintain')
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-review', 'reason': 'review the final head',
                           'category': 'review'})
        self.dispatch('pr-12-review', verdict='approve')

        # The review stage is accepted as mergeable (not merged) at H2; only now may the land stage merge.
        reviewed, argv12, input12 = self.accept('pr-12')
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        self.assertTrue(self.merge_allowed('pr-12-land'))
        landed, argv12l, input12l = self.accept('pr-12-land')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)

        # The quick-pass merge of PR 13 (no babysitter change, not review-gated) is accepted directly.
        direct, argv13, input13 = self.accept('pr-13')
        self.assertEqual(direct.returncode, 0, direct.stdout + direct.stderr)

        # The initial plan's final acceptance covers every requirement at fresh observations.
        final = self.run_cli('job_acceptance_cli.py', 'validate-final', {
            'caller': self.caller,
            'validator_argv_by_stage': {'pr-12': argv12, 'pr-12-land': argv12l, 'pr-13': argv13},
            'input_file_by_stage': {'pr-12': input12, 'pr-12-land': input12l, 'pr-13': input13}}, ok=False)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertTrue(json.loads(final.stdout)['accepted'])
        self.assertEqual(set(self.statuses()[0].values()), {'accepted-at-snapshot'})

        # The stage repair budget (initial pass plus three) is now spent; no fifth pass.
        refused = self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'one more'}, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('budget exhausted', refused.stderr)

    def test_head_moving_after_review_reopens_the_gate(self):
        self.job('create', self.plan())
        self.dispatch('pr-12-maintain')
        self.dispatch('pr-12-review', verdict='approve')
        self.assertEqual(self.accept('pr-12')[0].returncode, 0)
        self.assertTrue(self.merge_allowed('pr-12-land'))
        # The author pushes H2 after the review: rebinding stales the review stage and closes the gate again.
        self.rebind_head('author-push', H2)
        self.assertFalse(self.merge_allowed('pr-12-land'))
        self.assertNotEqual(self.accept('pr-12-land')[0].returncode, 0)

    def test_failed_rounds_exhaust_the_budget_and_cannot_reset(self):
        self.job('create', self.plan())
        failure = {'id': 'F1', 'severity': 'blocker', 'scenario': 'ci still fails', 'source_evidence': ['ci log']}
        self.dispatch('pr-12-maintain', status='failed', verdict='adverse', findings=[failure])
        for repair in range(3):
            self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': f'repair {repair + 1}'})
            self.dispatch('pr-12-maintain', status='failed', verdict='adverse', findings=[failure])
        refused = self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'escalate'}, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('budget exhausted', refused.stderr)
        self.assertEqual(self.statuses()[1]['pr-12-maintain'], 'failed')
        self.assertFalse(self.merge_allowed('pr-12-land'))

    def test_reviewer_on_the_maintainers_lineage_is_refused(self):
        plan = self.plan()
        plan['tasks'][1]['target'] = dict(WORKHORSE, providerInstanceId='fixture-other', model='fixture-other')
        self.job('create', plan)
        self.dispatch('pr-12-maintain')
        refused = self.job('prepare', {'caller': self.caller, 'task_id': 'pr-12-review'}, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('lineage', refused.stderr)

    def test_read_only_triage_ends_with_named_blockers_not_acceptance(self):
        plan = self.plan()
        plan['authorization'] = {'actions': ['read'], 'prs': {PR12: ['read'], PR13: ['read']}}
        for stage in plan['stages']:
            stage['validator_contract']['authorized_endstate'] = {
                'requested': 'open', 'observed': 'open', 'authorization_ref': 'owner-invocation'}
        self.job('create', plan)
        blocker = {'id': 'F1', 'severity': 'blocker', 'scenario': 'required check ci fails at ' + H1,
                   'source_evidence': ['ci run at ' + H1]}
        brief = self.dispatch('pr-12-maintain', status='blocked', verdict='adverse', findings=[blocker])
        self.assertEqual(brief['authorization']['prs'][PR12], ['read'])
        self.assertEqual(self.statuses()[1]['pr-12-maintain'], 'blocked')
        proc, *_ = self.accept('pr-12', conclusion='failure')
        self.assertNotEqual(proc.returncode, 0)
        self.assertNotEqual(self.statuses()[0]['pr-12'], 'accepted-at-snapshot')

    def test_scope_widening_head_rebind_needs_recorded_owner_evidence(self):
        self.job('create', self.plan())
        refused = self.job('plan-revision', {'caller': self.caller, 'revision': {'id': 'no-owner'},
                                             'new_plan': {'stages': [{k: v for k, v in stage.items() if k != 'status'}
                                                                          for stage in self.plan(H2)['stages']]}}, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('undeclared_expansion', refused.stderr)

    def test_worker_cannot_use_coordinator_commands(self):
        self.job('create', self.plan())
        worker = {**self.caller, 'actor': 'worker', 'task_id': 'pr-12-maintain', 'stage_id': 'pr-12'}
        decision = {'id': 'x', 'quote': '/t3-babysitter', 'source': str(self.request),
                    'source_sha256': hashlib.sha256(self.request.read_bytes()).hexdigest(), 'scope': 'plan:x'}
        for command, payload in (('prepare', {'caller': worker, 'task_id': 'pr-12-maintain'}),
                                 ('decision', {'caller': worker, 'decision': decision}),
                                 ('retry', {'caller': worker, 'task_id': 'pr-12-maintain', 'reason': 'self'})):
            with self.subTest(command=command):
                self.assertNotEqual(self.job(command, payload, ok=False).returncode, 0)


if __name__ == '__main__':
    unittest.main()
