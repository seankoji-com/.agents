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
        self.assertIn('`--arm-always` under **enable**', quick)

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
        self.assertIn('`--force-with-lease=<branch>:<observed sha>`', auth)
        self.assertIn('never a plain or unpinned force', auth)
        self.assertIn('force-push a base or shared branch', auth)
        self.assertIn('Never use admin bypass, dismiss reviews, weaken checks', auth)
        self.assertIn('cannot widen this scope', auth)

    def test_auto_merge_posture_defaults_without_a_picker_answer(self):
        posture = sections('entry.md')['Auto-merge posture']
        for option in ('**enable auto-merge on all PRs**', '**leave auto-merge as set**',
                       '**ignore PRs with auto-merge**'):
            self.assertIn(option, posture)
        self.assertIn('`job_cli.py decision`', posture)
        self.assertIn('without a question', posture)
        self.assertIn('citing the original request and this default', posture)
        self.assertIn('never invent a picker answer', posture)
        self.assertIn('Inspect-only runs arm nothing', posture)
        self.assertIn('Enable and leave accept that GitHub may land a fixer push', posture)
        self.assertIn('An armed request never withholds a fixer push', posture)
        self.assertIn('Armed auto-merge is not progress while `blockers=` names threads', posture)
        play = steps('playbooks/maintain.md')
        self.assertIn("Apply the entry's auto-merge default or explicit override without a question", play[1])
        self.assertIn('`job_cli.py decision`', play[1])
        self.assertIn('under **ignore**, exclude PRs with an armed request', play[1])
        self.assertIn('`--arm-always` under **enable**', play[2])
        self.assertIn('`automerge=preexisting`', play[2])

    def test_inspect_only_runs_no_mutating_helper(self):
        step1 = steps('playbooks/maintain.md')[1]
        self.assertIn("An inspect-only run skips step 2's helper", step1)
        self.assertIn('`read` only maintainer slots', step1)
        self.assertIn('never an acceptance', step1)

    def test_children_never_merge_or_watch(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('Children never run `merge-pr.sh` merge, arm, or resolve modes', play[6])
        self.assertIn('Children cannot watch; this thread owns every watch', play[8])
        workers = sections('entry.md')['Workers']
        self.assertIn('Only this thread dispatches, watches, merges, and accepts', workers)
        self.assertIn('grant no push or merge authority by themselves', workers)

    def test_pr_links_and_host_watches_without_polling(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('`link_pull_request`', play[1])
        self.assertIn('Call `watch_pull_request` for every unmerged PR', play[8])
        self.assertIn('Then post the table and end the turn', play[9])
        self.assertIn('`unwatch_pull_request`', play[10])
        self.assertIn('Do not run `pr-events.sh` in T3', play[13])
        self.assertNotRegex(text('playbooks/maintain.md'), r'(?i)\bsleep\b|\bpoll')

    def test_roster_pagination_isolation_and_exact_head(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('a partial page is not the whole roster', play[1])
        self.assertIn('`bash PKG/scripts/list-prs.sh --all-authors', play[1])
        self.assertIn('include all authors and bots; exclude drafts and forks unless included by the operator', play[1])
        self.assertIn('`bash PKG/scripts/pr-workspace.sh`', play[5])
        self.assertIn('a check from an older SHA proves nothing', play[8])
        self.assertIn('verify the claimed push against the PR head', play[8])

    def test_active_discovery_needs_no_schedule_but_persistent_discovery_does(self):
        sweep = steps('playbooks/maintain.md')[12]
        self.assertIn('at entry, every wake/completion, and before yielding or handing off', sweep)
        self.assertIn('Admit new matches without asking', sweep)
        self.assertIn('Persistent scheduled discovery uses the host scheduler', sweep)
        self.assertIn('only when requested', sweep)
        scope = text('references/scope.md')
        self.assertIn('Native PR watches wake for linked PR changes, not new PR discovery', scope)
        self.assertIn('Active-run discovery never needs that extra authorization', scope)

    def test_scope_refresh_never_runs_a_merge_helper_over_an_active_fixer(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('for each unowned PR with no fixer in flight run', play[2])
        self.assertIn('then return to the caller', play[12])
        self.assertIn('Never re-enter step 8 from discovery', play[12])
        self.assertIn("under step 2's skip rules (in-flight fixer, review-gated)", play[12])
        self.assertIn('step 4 for newly admitted PRs with child work or requested review before yielding', play[12])
        self.assertIn('Every merge-helper invocation skips a PR with a fixer in flight', text('references/scope.md'))

    def test_retry_usage_is_owned_by_the_coordinator_and_delivered_each_round(self):
        scope = text('references/scope.md')
        worker = text('agents/pr-maintainer.md')
        self.assertIn('The coordinator owns cross-round accounting', scope)
        self.assertIn('Include that current `retry_usage` in each round\'s dispatch task text', scope)
        self.assertIn('recover missing history from prior results instead of resetting it', scope)
        self.assertIn('`retry_usage`', steps('playbooks/maintain.md')[6])
        self.assertIn('use only the supplied remaining allowance', worker)
        self.assertIn('The coordinator carries counters across rounds', worker)
        self.assertIn('before repeating an unchanged failure', worker)

    def test_approvals_route_through_the_picker_and_are_recorded(self):
        approvals = sections('entry.md')['Approvals']
        for phrase in ('native question picker', 'recommended option first', '`job_cli.py decision`',
                       'silence is not approval'):
            self.assertIn(phrase, approvals)
        play = steps('playbooks/maintain.md')
        # Model choice is upfront; fan-out, setup and repair authority remain intact.
        self.assertIn('upfront selected work target/options', play[5])
        self.assertIn('Never infer an answer', play[5])
        self.assertIn('no concurrency cap and no question', play[4])
        self.assertIn('finite `max_repair_cycles` allowance', play[8])
        self.assertIn('Fan-out, repair rounds, branch rewrites, and a', approvals)
        self.assertIn("roster PR's tests and regressions with the setup they need are decided: never ask, always yes", approvals)
        self.assertIn('ask through the question picker', sections('references/job-plan.md')['Merge and acceptance'])

    def test_validator_is_the_acceptance_authority(self):
        acceptance = sections('entry.md')['Acceptance']
        self.assertIn('`PKG/scripts/validate_pr.py` is the authority', acceptance)
        for claim in ('terminal task', 'older-head check', 'queued auto-merge'):
            self.assertIn(claim, acceptance)
        stages = sections('references/job-plan.md')['Stage']
        for field in ('pr', 'head_sha', 'required_contexts', 'optional_contexts',
                      'allow_empty_required_contexts', 'authorized_endstate'):
            self.assertIn(f'`{field}`', stages)
        self.assertIn('never from a worker result', sections('references/job-plan.md')['Acceptance input'])
        self.assertIn('`review_thread_count`', sections('references/job-plan.md')['Acceptance input'])
        self.assertIn('a complete list of resolved threads', acceptance)

    def test_missing_reviewer_and_fallback_stay_visible(self):
        fallback = steps('playbooks/maintain.md')[11]
        self.assertIn('visible fallback marker', fallback)
        self.assertIn('A failed candidate alone grants no target substitution', fallback)

    def test_master_quick_pass_table_and_fixers_survive(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('| PR | Description | Not merged because |', play[3])
        self.assertIn('Post it after the quick pass and at the end of every turn', play[3])
        self.assertIn('Show live-catalog choices without routing', play[5])
        self.assertIn('cheapest suitable tier', play[5])
        self.assertIn('`needs human:`', play[9])
        self.assertIn('`automerge=preexisting`', play[2])
        self.assertIn("Rerun step 2's helper for that PR unless its fixer is in flight", play[8])


class RelentlessLandingTest(unittest.TestCase):
    """Failures from the 16-17 Oct 2026 org run: masked thread blockers, silent waits, timid dispatch."""

    def test_every_blocker_is_read_not_just_the_first(self):
        play = steps('playbooks/maintain.md')
        self.assertIn("whole `blockers=` list, not just `reason=`", play[2])
        self.assertIn('the complete `blockers=` list, every unresolved thread\'s ID and comments', play[6])
        self.assertIn('every listed blocker cleared at a pushed head', play[6])

    def test_coordinator_owns_thread_resolution_over_curl(self):
        threads = sections('entry.md')['Threads']
        for phrase in ('outdated ones included', '`merge-pr.sh --resolve-thread`', 'uses curl',
                       'ask only when the remaining action needs a human'):
            self.assertIn(phrase, threads)
        play = steps('playbooks/maintain.md')
        self.assertIn('--resolve-thread <ID> --verified-head <head> --reply-file <file>', play[7])
        self.assertIn('Actionable minor findings need fixes too', play[7])
        body = text('agents/pr-maintainer.md')
        self.assertIn('`thread:<thread ID>`', body)
        self.assertIn('The coordinator owns merge, replies, thread resolution', body)

    def test_operator_review_still_skips_every_merge_capable_helper(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('If the operator asked for review before landing, every PR is review-gated: skip this helper', play[2])
        self.assertIn('give every unmerged PR a job (step 4) even without repair work', play[2])
        self.assertIn("a review-gated PR merges only through its land stage's pinned command", play[8])
        review = sections('references/job-plan.md')['Operator-requested review']
        self.assertIn('never pass a review-gated PR to the quick-pass helper', review)
        self.assertIn('A PR with no repair work keeps the `maintain` slot as a verification round that pushes nothing',
                      review)
        self.assertIn('never apply the post-merge rebind above to a review job', review)
        self.assertIn('For a job without operator-requested review', sections('references/job-plan.md')['Merge and acceptance'])

    def test_a_new_matching_pr_is_not_a_scope_expansion(self):
        self.assertIn('Automatically admit new matching PRs under the original request',
                      sections('entry.md')['Authorization'])
        self.assertIn('New matching PRs are already authorized by org/repo scope and get separate jobs',
                      sections('references/job-plan.md')['Merge and acceptance'])
        self.assertIn('fresh complete discovery has no untreated eligible PRs', steps('playbooks/maintain.md')[13])

    def test_needs_followup_has_a_path_forward(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('(`needs-followup` follows `PKG/references/job-plan.md`)', play[8])
        # An unfinished `failed` round is retried, not escalated; escalation needs blocked, malformed or a repeat.
        self.assertIn('does not authorise escalation: use only the approved work chain or obtain a new choice',
                      play[8])
        self.assertIn('A required human review with nothing left to fix is `needs human:`', play[4])
        self.assertIn('moves the slot\'s `target` to another candidate', sections('references/job-plan.md')['Stage'])
        self.assertIn('never `needs-followup`', text('agents/pr-maintainer.md'))

    def test_no_dead_end_turns(self):
        play = steps('playbooks/maintain.md')
        self.assertIn('Never end a turn on "auto-merge armed" alone', play[9])
        self.assertIn('Anything else is acted on now', play[9])
        self.assertIn('reconcile every child through `task_status` and refill', play[8])

    def test_jobs_are_per_pr_and_never_rebind_between_rounds(self):
        plan = sections('references/job-plan.md')
        self.assertIn('One job per PR that needs a child', plan['Shape'])
        self.assertIn('In a job without operator-requested review, never rebind the head between rounds', plan['Stage'])
        self.assertIn('A review-gated job rebinds both stages to each pushed head', plan['Stage'])
        self.assertIn('removes the settled `maintain` slot', plan['Merge and acceptance'])

    def test_maintainer_keeps_going_and_may_rebase_with_a_pinned_lease(self):
        body = text('agents/pr-maintainer.md')
        self.assertIn('fetch it, integrate it into your work, and carry on at the new head', body)
        self.assertIn('`git push --force-with-lease=<branch>:<sha you last fetched> origin HEAD:<branch>`', body)
        self.assertNotIn('stop and return `needs-followup`', body)

    def test_completed_fixer_dispositions_are_resolved_before_merge_or_watch(self):
        play = steps('playbooks/maintain.md')
        wake = play[8]
        self.assertLess(wake.index('`job_cli.py result`'), wake.index('perform step 7'))
        self.assertLess(wake.index('perform step 7'), wake.index("Rerun step 2's helper"))
        self.assertLess(wake.index('perform step 7'), wake.index('Call `watch_pull_request`'))
        for phrase in ('every unresolved thread at the current head', 'including all pages',
                       'Verify fixes there or establish why no change applies',
                       'Re-read to confirm resolution', 'severity alone never justifies an answer'):
            self.assertIn(phrase, play[7])
        cycle = sections('references/job-plan.md')['Repair cycle']
        for phrase in ('A missing disposition or a newly arrived thread needs inspection now',
                       'Never mark resolution complete from a reply alone',
                       'Resolve addressed threads even while CI is red or a new review is required'):
            self.assertIn(phrase, cycle)

    def test_conflicts_and_failed_checks_have_explicit_repair_requirements(self):
        worker = text('agents/pr-maintainer.md')
        for phrase in ('Fetch the current base and head before repairing merge conflicts',
                       'resolve each conflicted path', 'testing the combined result'):
            # The cycle and worker together bind dispatch to the required repair work.
            self.assertIn(phrase, worker + ' ' + sections('references/job-plan.md')['Repair cycle'])
        for phrase in ('read the current-head failed job logs', 'reproduce the failure where possible',
                       'fix its cause and run focused regressions',
                       'A rerun alone does not repair a repeatable failure',
                       'Report pending hosted checks separately from local passes'):
            self.assertIn(phrase, worker)
        self.assertIn('each PR with child work and no child in flight gets its next round now',
                      steps('playbooks/maintain.md')[8])

    def test_health_and_ledger_errors_stop_supported_writes_without_bypass(self):
        cycle = sections('references/job-plan.md')['Repair cycle']
        for phrase in ('`t3-plugins doctor babysitter`', '`t3-plugins agents list babysitter`',
                       '`job_cli.py overview`', 'integrity failure stops writes for that PR',
                       'exact command, exit code and error', 'Never edit the ledger by hand',
                       'create a replacement job to evade it',
                       'Direct fallback applies only to unavailable delegation'):
            self.assertIn(phrase, cycle)
        for rel in ('entry.md', 'agents/pr-maintainer.md'):
            self.assertIn('stop writes', text(rel))
        self.assertIn('repair cycle before writes', text('entry.md'))

    def test_review_state_checks_threads_and_mergeability_remain_separate(self):
        cycle = sections('references/job-plan.md')['Repair cycle']
        self.assertIn('four independent landing gates at the current head', cycle)
        self.assertIn('A resolved thread does not clear `CHANGES_REQUESTED`', cycle)
        self.assertIn("request the reviewer's re-review", cycle)
        self.assertIn('without dismissing their review', cycle)
        self.assertIn('Never land with an actionable blocking thread open', cycle)
        worker = text('agents/pr-maintainer.md')
        self.assertIn('Actionable minor findings need fixes too', worker)
        self.assertIn('Neither means the GitHub thread is resolved', worker)


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
                       'named blockers', 'Never a plain or unpinned force', 'Without `push` you never push',
                       'Never merge, arm or disable auto-merge', '`review_verdict` is `null`',
                       'is never an approval question', 'is never that approval'):
            self.assertIn(phrase, body)

    def test_reviewer_is_independent_and_read_only(self):
        body = text('agents/pr-reviewer.md')
        for phrase in ('final combined changes', 'independently of the maintainer', '`approve`', '`adverse`',
                       'any blocker or major finding forces `adverse`',
                       'Do not edit, commit, push, post, resolve threads, or merge'):
            self.assertIn(phrase, body)


def documented_plan(head12=H1, installation_id='fixture-installation'):
    """The example job plan from references/job-plan.md, with its placeholders filled."""
    raw = (PLUGIN / 'references/job-plan.md').read_text().split('```json\n', 1)[1].split('\n```', 1)[0]
    for placeholder, value in (('"<workhorse-target>"', json.dumps(WORKHORSE)), ('<job-id>', 'bs-1'),
                               ('<installation-id>', installation_id), ('<pr-12-url>', PR12),
                               ('<decision-id>', 'owner-invocation'), ('<head-12-short>', head12[:12]),
                               ('<head-12>', head12)):
        raw = raw.replace(placeholder, value)
    if '<' in raw:
        raise AssertionError('unfilled placeholder in the documented plan: ' + re.search(r'<[^>]*>', raw).group(0))
    return json.loads(raw)


def review_gated_plan(head12=H1, installation_id='fixture-installation'):
    """The "Operator-requested review" shape from references/job-plan.md, built on the documented plan."""
    plan = documented_plan(head12, installation_id)
    review, maintain = plan['stages'][0], plan['tasks'][0]
    review['requirements'] = ['PR-12-REVIEW']
    review['validator_contract']['authorized_endstate'].update(requested='mergeable', observed='mergeable')
    plan['requirements']['PR-12-REVIEW'] = 'an independent review approved owner/repo#12 at the head that lands'
    land = json.loads(json.dumps(review))
    land.update(id='pr-12-land', depends_on=['pr-12'], requirements=['PR-12'], execution_mode='direct',
                revision='pr-12-land@' + head12[:12])
    land['validator_contract']['authorized_endstate'].update(requested='merged', observed='merged')
    plan['stages'].append(land)
    maintain.update(review_required=True, review_task_ids=['pr-12-review'])
    plan['tasks'].append({'task_id': 'pr-12-review', 'stage_id': 'pr-12', 'logical_slot_id': 'review',
                          'request_id': 'bs-1-pr-12-review', 'worker_id': 'babysitter/pr-reviewer',
                          'dependency_key': 'babysitter', 'target': REVIEWER,
                          'write_scope': {'mode': 'worker-evidence', 'path': 'artifacts/tasks/pr-12-review'},
                          'role': 'review', 'reviewed_task_ids': ['pr-12-maintain']})
    return plan


def merge_gate_violations(plan):
    """Every way a review-gated plan lets a merge-capable stage run before its PR's review stage is accepted.

    A stage holding a review slot is a review stage. It must not request `merged`, and every stage
    of the same PR that requests `merged` must depend on it (transitively). A plan without review
    slots has no babysitter gate: GitHub's own requirements, read by validate_pr.py, decide.
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
    for review in sorted(review_stages):
        if requested[review] == 'merged':
            violations.append(f'{review}: a review stage requests merged, so it merges before its own acceptance')
        for sid in sorted(stages):
            if sid != review and pr_of[sid] == pr_of[review] and requested[sid] == 'merged' and review not in ancestors(sid):
                violations.append(f'{sid}: merges {pr_of[sid]} without depending on review stage {review}')
    return violations


class MergeGatePlanTest(unittest.TestCase):
    def test_documented_plans_satisfy_the_gate(self):
        self.assertEqual(merge_gate_violations(documented_plan()), [])
        self.assertEqual(merge_gate_violations(review_gated_plan()), [])
        # The default plan is one PR, one stage, one fixer slot, no reviewer.
        plan = documented_plan()
        self.assertEqual([s['id'] for s in plan['stages']], ['pr-12'])
        self.assertEqual([t['worker_id'] for t in plan['tasks']], ['babysitter/pr-maintainer'])
        self.assertNotIn('review_required', plan['tasks'][0])
        self.assertEqual(plan['stages'][0]['validator_contract']['authorized_endstate']['requested'], 'merged')

    def test_gate_checker_rejects_every_early_merge_shape(self):
        mutations = {
            'land stage without the review dependency': lambda p: p['stages'][1].update(depends_on=[]),
            'review stage requesting merged': lambda p: p['stages'][0]['validator_contract']['authorized_endstate'].update(
                requested='merged', observed='merged'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                plan = review_gated_plan()
                mutate(plan)
                self.assertNotEqual(merge_gate_violations(plan), [])

    def test_gate_is_stated_where_the_coordinator_reads_it(self):
        gate = sections('entry.md')['Landing gate']
        self.assertIn('Thread resolution, latest review state, required checks and mergeability are separate gates', gate)
        self.assertIn('unless the operator asks for review before landing', gate)
        self.assertIn('UNSTABLE PRs whose every required check succeeded at the head', gate)
        self.assertNotIn('never dispatched while the PR has an auto-merge request', text('entry.md'))
        self.assertIn('An armed request never withholds a fixer push', sections('entry.md')['Auto-merge posture'])
        review = sections('references/job-plan.md')['Operator-requested review']
        self.assertIn('`merge-pr.sh --no-auto --expected-head <head_sha>`', review)
        self.assertIn('No stage that holds a `review` slot may request `merged`', review)


class SyntheticJobTest(unittest.TestCase):
    """The documented plan driven through the installed helpers: fixer rounds, merge, one rebind, acceptance."""

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

    def test_installed_instructions_cover_scope_and_the_avoidable_decisions(self):
        # Exercise the delivered package, not a reference that disappears on install.
        files = ('entry.md', 'playbooks/maintain.md', 'references/job-plan.md',
                 'references/scope.md', 'agents/pr-maintainer.md', 'shared/t3-runtime.md')
        delivered = {rel: norm((self.version / rel).read_text()) for rel in files}
        scope = delivered['references/scope.md']
        for scenario, rule in {
            'new PR on a wake': 'A new matching PR needs no renewed authorization',
            'complete final sweep': 'A denied or incomplete read is a named discovery gap',
            'moving branch, no writer': 'A new commit alone proves no active writer',
            'download failures': 'repeated DNS/TLS or download failures alone do not require human input',
            'auto-merge default': 'without a question',
        }.items():
            with self.subTest(scenario=scenario):
                self.assertIn(rule, scope + ' ' + delivered['references/job-plan.md'] + ' ' + delivered['entry.md'])
        self.assertIn('record its per-PR actions from the saved request before mutations', scope)
        self.assertIn("Never rewrite an existing job's PR identity", scope)
        self.assertIn('Drafts and forks stay excluded unless explicitly included', scope)
        self.assertIn('Such rows are read-only: skip the merge helper, fixer dispatch, replies/resolutions and watches', scope)
        self.assertIn('skip merge, fixer, reply and watch actions on it', delivered['shared/t3-runtime.md'])
        self.assertIn('use at most 3 attempts or 5 minutes', scope)
        self.assertIn('Include that current `retry_usage` in each round\'s dispatch task text', scope)
        self.assertIn('use only the supplied remaining allowance', delivered['agents/pr-maintainer.md'])
        for rel, body in delivered.items():
            if rel.startswith('shared/'):
                continue
            with self.subTest(file=rel):
                for obsolete in ('A PR outside the frozen roster gets no action', 'Freeze the roster',
                                 'otherwise ask once through the picker',
                                 'watching today\'s PRs does not discover tomorrow\'s'):
                    self.assertNotIn(obsolete, body)

    # -- helpers -----------------------------------------------------------------------------
    def plan(self, head12=H1, max_repair_cycles=None, gated=False):
        build = review_gated_plan if gated else documented_plan
        plan = build(head12=head12, installation_id=self.caller['installation_id'])
        if max_repair_cycles is not None:
            plan['policy']['max_repair_cycles'] = max_repair_cycles
        return plan

    def run_cli(self, script, command, payload=None, ok=True):
        if command == 'create' and payload is not None:
            from tests.model_selection_fixtures import attach_selection
            attach_selection(payload)
        if command == 'plan-revision' and payload is not None:
            from tests.model_selection_fixtures import attach_revision
            attach_revision(payload, json.loads((self.state/'bs-1/job.json').read_text()))
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
        if kind == 'accepted':
            task = next(t for t in json.loads((self.state / 'bs-1' / 'job.json').read_text())['tasks']
                        if t['task_id'] == task_id)
            event['status_identity'] = {'providerInstanceId': task['target']['providerInstanceId'],
                                        'model': task['target']['model']}
        if kind == 'completion':
            event.update(status='completed', work_state='result_available', completion_id=host + '-done')
        return self.job('task-observation', {'caller': self.caller, 'task_id': task_id, 'event': event})

    def dispatch(self, task_id, *, status='ready-for-acceptance', verdict=None, findings=(), changes=()):
        """prepare -> (synthetic delegate_task) -> accepted handle -> result -> completion, via the CLI."""
        self.counter += 1
        host = self.last_host = f'host-{task_id}-{self.counter}'
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

    def publish(self, stage_id, *, head=None, check_head=None, conclusion='success', endstate=None,
                threads=None, thread_count=None):
        """A coordinator host read of the PR, content-bound as validate_pr.py requires."""
        contract = self.stage_contract(stage_id)
        head = head or contract['head_sha']
        data = {**contract, 'head_sha': head,
                'required_checks': [{'context': 'ci', 'conclusion': conclusion, 'head_sha': check_head or head}],
                'review_threads': threads if threads is not None else [{'id': 'T1', 'resolved': True, 'head_sha': head}]}
        data['review_thread_count'] = len(data['review_threads']) if thread_count is None else thread_count
        data['authorized_endstate'] = dict(data['authorized_endstate'],
                                           observed=endstate or data['authorized_endstate']['requested'])
        content = {k: data[k] for k in ('pr', 'head_sha', 'required_contexts', 'required_checks', 'review_threads',
                                        'review_thread_count', 'authorized_endstate', 'allow_empty_required_contexts',
                                        'optional_contexts')}
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

    def rebind_head(self, revision_id, head, gated=False, drop_slots=False, ok=True):
        """Owner-sourced plan revision to a new head; after a merge it also drops the settled fixer slot."""
        self.job('decision', {'caller': self.caller, 'decision': {
            'id': 'owner-' + revision_id, 'quote': self.request.read_text().strip(), 'source': str(self.request),
            'source_sha256': hashlib.sha256(self.request.read_bytes()).hexdigest(), 'scope': 'plan:' + revision_id}})
        stages = [{k: v for k, v in stage.items() if k != 'status'} for stage in self.plan(head, gated=gated)['stages']]
        new_plan = {'stages': stages}
        if drop_slots:
            for stage in stages:
                stage['execution_mode'] = 'direct'
            new_plan['tasks'] = []
        return self.job('plan-revision', {'caller': self.caller, 'new_plan': new_plan,
                                          'revision': {'id': revision_id, 'owner_decision_id': 'owner-' + revision_id}},
                        ok=ok)

    def statuses(self):
        overview = self.job('overview')
        return ({s['id']: s['status'] for s in overview['stages']},
                {h['task_id']: h['status'] for h in overview['handles']})

    def merge_allowed(self, stage_id):
        """The land stage's merge-capable step may run only once its review dependency holds current acceptance."""
        stages = {s['id']: s for s in self.job('overview')['stages']}
        return all(stages[dep]['status'] == 'accepted-at-snapshot' for dep in stages[stage_id]['depends_on'])

    # -- scenarios ---------------------------------------------------------------------------
    def test_fixer_rounds_then_one_rebind_accepts_the_merge(self):
        self.job('create', self.plan())
        brief = self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H2}])
        self.assertEqual(brief['authorization']['prs'][PR12], ['read', 'push', 'communicate', 'merge'])
        self.assertIn('worker_id: babysitter/pr-maintainer', json.dumps(brief['effective_definition']))
        # A new bot thread lands at H2: the next round is a plain retry, with no head rebind between rounds.
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'new thread at H2'})
        self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H3}])
        self.assertEqual(self.stage_contract('pr-12')['head_sha'], H1)
        # GitHub merges H3. The stage still binds H1, so an H3 read is not acceptance yet.
        self.assertNotEqual(self.accept('pr-12', head=H3)[0].returncode, 0)
        # One owner-sourced rebind to the merged head drops the settled fixer slot: no verify-only round.
        self.rebind_head('merged-h3', H3, drop_slots=True)
        self.assertEqual(self.stage_contract('pr-12')['head_sha'], H3)
        # A push-authorized PR with no review stage reaches merged on GitHub's own gate.
        landed, argv, published = self.accept('pr-12')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)
        final = self.run_cli('job_acceptance_cli.py', 'validate-final', {
            'caller': self.caller, 'validator_argv_by_stage': {'pr-12': argv},
            'input_file_by_stage': {'pr-12': published}}, ok=False)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertTrue(json.loads(final.stdout)['accepted'])

    def test_incomplete_thread_list_or_open_thread_is_refused(self):
        self.job('create', self.plan())
        self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H2}])
        self.rebind_head('merged-h2', H2, drop_slots=True)
        # Only the first page of threads was read: 1 entry against GitHub's total of 55.
        partial, *_ = self.accept('pr-12', thread_count=55)
        self.assertNotEqual(partial.returncode, 0)
        self.assertIn('review thread list is incomplete', partial.stdout + partial.stderr)
        open_thread, *_ = self.accept('pr-12', threads=[{'id': 'T1', 'resolved': False, 'head_sha': H2}])
        self.assertNotEqual(open_thread.returncode, 0)
        # Two copies of a resolved thread cannot stand in for an unresolved second one.
        duplicated, *_ = self.accept('pr-12', threads=[{'id': 'T1', 'resolved': True, 'head_sha': H2}] * 2)
        self.assertNotEqual(duplicated.returncode, 0)
        self.assertIn('distinct host thread IDs', duplicated.stdout + duplicated.stderr)
        anonymous, *_ = self.accept('pr-12', threads=[{'resolved': True, 'head_sha': H2}])
        self.assertNotEqual(anonymous.returncode, 0)

    def test_neutral_and_skipped_required_checks_pass_as_they_merge(self):
        # merge-pr.sh merges on NEUTRAL/SKIPPED required checks; acceptance must agree or a merged PR strands.
        self.job('create', self.plan())
        self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H2}])
        self.rebind_head('merged-h2', H2, drop_slots=True)
        for conclusion in ('neutral', 'skipped'):
            with self.subTest(conclusion):
                landed, *_ = self.accept('pr-12', conclusion=conclusion)
                self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)
        for conclusion in ('failure', 'cancelled', 'SUCCESS'):
            with self.subTest(conclusion):
                self.assertNotEqual(self.accept('pr-12', conclusion=conclusion)[0].returncode, 0)

    def followup(self, brief, parent, status):
        """One tracked same-child follow-up of the maintain slot, through the CLI."""
        request = brief['request_id'] + '-fu1'
        staged = self.job('followup-prepare', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'request_id': request})
        fu_brief = json.loads(Path(staged['path']).read_text())
        host = parent + '-fu1'
        scope = {'mode': 'worker-evidence', 'path': 'artifacts/tasks/pr-12-maintain'}
        for event in ({'kind': 'followup', 'request_id': request, 'host_task_id': host, 'parent_host_task_id': parent,
                       'child_thread_id': 'thread-' + parent, 'target': WORKHORSE, 'scope': scope},
                      {'kind': 'completion', 'request_id': request, 'host_task_id': host, 'completion_id': host + '-done',
                       'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False}):
            self.job('task-observation', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'event': event})
        result = {'schema_version': 1, **{k: fu_brief[k] for k in ('job_id', 'stage_id', 'logical_slot_id', 'request_id',
                                                                     'worker_id', 'effective_brief_sha256', 'revision')},
                  'status': status, 'conclusion': 'synthetic follow-up', 'requirements': [
                      {'id': r['id'], 'status': 'passed', 'evidence': ['fixture']} for r in fu_brief['requirements']],
                  'review_verdict': None, 'findings': [], 'gaps': [], 'uncertainties': [], 'changes': [],
                  'commands': [], 'artifacts': [], 'binding': fu_brief['snapshot'], 'extra_work_requests': [],
                  'metrics': {}}
        self.job('result', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'request_id': request,
                            'completion_id': host + '-done', 'result': {'json': json.dumps(result)}})

    def test_repeated_needs_followup_escalates_instead_of_stranding_the_slot(self):
        self.job('create', self.plan())
        brief = self.dispatch('pr-12-maintain', status='needs-followup')
        self.followup(brief, self.last_host, 'needs-followup')
        # The one declared follow-up is spent, and an awaiting-followup slot cannot be retried or removed.
        spent = self.job('followup-prepare', {'caller': self.caller, 'task_id': 'pr-12-maintain',
                                              'request_id': brief['request_id'] + '-fu2'}, ok=False)
        self.assertNotEqual(spent.returncode, 0)
        self.assertNotEqual(self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain',
                                               'reason': 'again'}, ok=False).returncode, 0)
        # Escalation: an owner-sourced revision moves the slot to the next candidate, staling it, so retry works.
        self.job('decision', {'caller': self.caller, 'decision': {
            'id': 'owner-escalate', 'quote': self.request.read_text().strip(), 'source': str(self.request),
            'source_sha256': hashlib.sha256(self.request.read_bytes()).hexdigest(), 'scope': 'plan:escalate'}})
        tasks = [{k: v for k, v in t.items() if k != 'request_id'} for t in self.plan()['tasks']]
        tasks[0]['target'] = dict(WORKHORSE, providerInstanceId='fixture-stronger', model='fixture-medium')
        self.job('plan-revision', {'caller': self.caller, 'new_plan': {'tasks': tasks},
                                   'revision': {'id': 'escalate', 'owner_decision_id': 'owner-escalate'}})
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'escalated candidate'})
        # The strongest candidate also returns needs-followup: the slot's follow-up is spent for good, so the
        # next escalation cycles the target back down the list, which stales the slot again.
        self.dispatch('pr-12-maintain', status='needs-followup')
        self.assertNotEqual(self.job('followup-prepare', {'caller': self.caller, 'task_id': 'pr-12-maintain',
                                                          'request_id': 'late-fu'}, ok=False).returncode, 0)
        self.job('decision', {'caller': self.caller, 'decision': {
            'id': 'owner-cycle', 'quote': self.request.read_text().strip(), 'source': str(self.request),
            'source_sha256': hashlib.sha256(self.request.read_bytes()).hexdigest(), 'scope': 'plan:cycle'}})
        tasks[0]['target'] = WORKHORSE
        self.job('plan-revision', {'caller': self.caller, 'new_plan': {'tasks': tasks},
                                   'revision': {'id': 'cycle', 'owner_decision_id': 'owner-cycle'}})
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'cycled candidate'})
        self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H2}])
        self.rebind_head('merged-h2', H2, drop_slots=True)
        landed, *_ = self.accept('pr-12')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)

    def test_dropping_a_fixer_slot_needs_its_blockers_disposed(self):
        self.job('create', self.plan())
        finding = {'id': 'F1', 'severity': 'blocker', 'scenario': 'ci fails at ' + H1, 'source_evidence': ['ci log']}
        self.dispatch('pr-12-maintain', status='failed', verdict='adverse', findings=[finding])
        refused = self.rebind_head('merged-h2', H2, drop_slots=True, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('unresolved blocker or major finding', refused.stderr)
        evidence = self.base / 'owner' / 'f1-fixed.txt'
        evidence.write_text('ci green at ' + H2 + '\n')
        self.job('finding-disposition', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'finding_id': 'F1',
                                         'disposition': 'fixed', 'evidence': {
                                             'path': str(evidence), 'bytes': evidence.stat().st_size,
                                             'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}})
        self.rebind_head('merged-h2-disposed', H2, drop_slots=True)
        landed, *_ = self.accept('pr-12')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)

    def test_failed_rounds_exhaust_the_budget_and_cannot_reset(self):
        # Budget-exhaustion mechanism: pin the cycles so this does not track the shipped default.
        self.job('create', self.plan(max_repair_cycles=3))
        failure = {'id': 'F1', 'severity': 'blocker', 'scenario': 'ci still fails', 'source_evidence': ['ci log']}
        self.dispatch('pr-12-maintain', status='failed', verdict='adverse', findings=[failure])
        for repair in range(3):
            self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': f'repair {repair + 1}'})
            self.dispatch('pr-12-maintain', status='failed', verdict='adverse', findings=[failure])
        refused = self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'escalate'}, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('budget exhausted', refused.stderr)
        self.assertEqual(self.statuses()[1]['pr-12-maintain'], 'failed')
        self.assertNotEqual(self.statuses()[0]['pr-12'], 'accepted-at-snapshot')

    def test_shipped_plan_uses_the_shared_default_repair_allowance(self):
        from shared.job_coordination import DEFAULT_MAX_REPAIR_CYCLES
        self.assertEqual(self.plan()['policy']['max_repair_cycles'], DEFAULT_MAX_REPAIR_CYCLES)

    def test_read_only_triage_ends_with_named_blockers_not_acceptance(self):
        plan = self.plan()
        plan['authorization'] = {'actions': ['read'], 'prs': {PR12: ['read']}}
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

    # -- operator-requested review before landing ---------------------------------------------
    def test_review_gated_merge_waits_for_review_at_the_exact_head(self):
        self.job('create', self.plan(gated=True))
        early, *_ = self.accept('pr-12-land')
        self.assertNotEqual(early.returncode, 0)
        self.assertIn('dependency lacks current authoritative acceptance', early.stderr + early.stdout)
        self.assertNotEqual(self.job('prepare', {'caller': self.caller, 'task_id': 'pr-12-review'}, ok=False).returncode, 0)
        self.dispatch('pr-12-maintain')
        finding = {'id': 'R1', 'severity': 'major', 'scenario': 'the fix drops input validation',
                   'source_evidence': ['src/widget.py at ' + H1]}
        self.dispatch('pr-12-review', verdict='adverse', findings=[finding])
        self.assertNotEqual(self.accept('pr-12')[0].returncode, 0)
        self.assertFalse(self.merge_allowed('pr-12-land'))
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'review finding R1'})
        self.dispatch('pr-12-maintain')
        evidence = self.base / 'owner' / 'r1-fixed.txt'
        evidence.write_text('validation restored at ' + H1 + '\n')
        self.job('finding-disposition', {'caller': self.caller, 'task_id': 'pr-12-review', 'finding_id': 'R1',
                                         'disposition': 'fixed', 'evidence': {
                                             'path': str(evidence), 'bytes': evidence.stat().st_size,
                                             'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}})
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-review', 'reason': 'fresh review round',
                           'category': 'review'})
        self.dispatch('pr-12-review', verdict='approve')
        reviewed, argv, published = self.accept('pr-12')
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        self.assertTrue(self.merge_allowed('pr-12-land'))
        # The pinned land command merged the reviewed head: accept land directly, with no post-merge rebind.
        landed, argv_land, published_land = self.accept('pr-12-land')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)
        final = self.run_cli('job_acceptance_cli.py', 'validate-final', {
            'caller': self.caller, 'validator_argv_by_stage': {'pr-12': argv, 'pr-12-land': argv_land},
            'input_file_by_stage': {'pr-12': published, 'pr-12-land': published_land}}, ok=False)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertTrue(json.loads(final.stdout)['accepted'])

    def test_review_only_pr_lands_after_its_review(self):
        # Operator asked for review before landing; this PR needs no repair, so the maintain slot only verifies.
        self.job('create', self.plan(gated=True))
        self.assertNotEqual(self.accept('pr-12-land')[0].returncode, 0)
        brief = self.dispatch('pr-12-maintain')
        self.assertEqual(brief['revision'], 'pr-12@' + H1[:12])
        self.dispatch('pr-12-review', verdict='approve')
        reviewed, *_ = self.accept('pr-12')
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        landed, *_ = self.accept('pr-12-land')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)

    def test_review_gated_fixer_push_rebinds_and_lands_at_the_reviewed_head(self):
        self.job('create', self.plan(gated=True))
        self.dispatch('pr-12-maintain', changes=[{'path': 'src/widget.py', 'pushed_head': H2}])
        # The fixer pushed H2: rebind both stages, which stales the maintainer, then verify and review at H2.
        self.rebind_head('fixer-push', H2, gated=True)
        self.assertEqual(self.stage_contract('pr-12')['head_sha'], H2)
        self.assertNotEqual(self.accept('pr-12')[0].returncode, 0)
        self.job('retry', {'caller': self.caller, 'task_id': 'pr-12-maintain', 'reason': 'verify pushed head'})
        self.dispatch('pr-12-maintain')
        self.dispatch('pr-12-review', verdict='approve')
        reviewed, argv, published = self.accept('pr-12')
        self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
        landed, argv_land, published_land = self.accept('pr-12-land')
        self.assertEqual(landed.returncode, 0, landed.stdout + landed.stderr)
        self.assertEqual(self.stage_contract('pr-12-land')['head_sha'], H2)
        final = self.run_cli('job_acceptance_cli.py', 'validate-final', {
            'caller': self.caller, 'validator_argv_by_stage': {'pr-12': argv, 'pr-12-land': argv_land},
            'input_file_by_stage': {'pr-12': published, 'pr-12-land': published_land}}, ok=False)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)

    def test_head_moving_after_review_reopens_the_gate(self):
        self.job('create', self.plan(gated=True))
        self.dispatch('pr-12-maintain')
        self.dispatch('pr-12-review', verdict='approve')
        self.assertEqual(self.accept('pr-12')[0].returncode, 0)
        self.assertTrue(self.merge_allowed('pr-12-land'))
        self.rebind_head('author-push', H2, gated=True)
        self.assertFalse(self.merge_allowed('pr-12-land'))
        self.assertNotEqual(self.accept('pr-12-land')[0].returncode, 0)

    def test_merged_acceptance_requires_the_review_stage_upstream_at_the_same_head(self):
        def land_without_review_dependency(plan):
            plan['stages'][1]['depends_on'] = []
        def land_at_another_head(plan):
            plan['stages'][1]['validator_contract']['head_sha'] = H2
            plan['stages'][1]['revision'] = 'pr-12-land@' + H2[:12]
        for name, mutate, reason in (('no dependency', land_without_review_dependency, 'does not depend on review stage'),
                                     ('other head', land_at_another_head, 'bound to a different head')):
            with self.subTest(name):
                self.state = self.base / ('state-' + name.replace(' ', '-'))
                plan = self.plan(gated=True)
                mutate(plan)
                self.job('create', plan)
                self.dispatch('pr-12-maintain')
                self.dispatch('pr-12-review', verdict='approve')
                reviewed, *_ = self.accept('pr-12')
                self.assertEqual(reviewed.returncode, 0, reviewed.stdout + reviewed.stderr)
                refused, *_ = self.accept('pr-12-land')
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn('review_gate', refused.stdout + refused.stderr)
                self.assertIn(reason, refused.stdout + refused.stderr)

    def test_review_stage_cannot_request_merged(self):
        plan = self.plan(gated=True)
        plan['stages'][0]['validator_contract']['authorized_endstate'].update(requested='merged', observed='merged')
        self.job('create', plan)
        self.dispatch('pr-12-maintain')
        self.dispatch('pr-12-review', verdict='approve')
        review, *_ = self.accept('pr-12')
        self.assertNotEqual(review.returncode, 0)
        self.assertIn('a stage holding a review slot cannot request merged', review.stdout + review.stderr)

    def test_reviewer_on_the_maintainers_lineage_is_refused(self):
        plan = self.plan(gated=True)
        plan['tasks'][1]['target'] = dict(WORKHORSE, providerInstanceId='fixture-other', model='fixture-other')
        self.job('create', plan)
        self.dispatch('pr-12-maintain')
        refused = self.job('prepare', {'caller': self.caller, 'task_id': 'pr-12-review'}, ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('lineage', refused.stderr)

if __name__ == '__main__':
    unittest.main()
