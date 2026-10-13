"""Issue #28 Stage 5 cross-stage regressions through installed CLIs (REQ-JOB, REQ-VISIBILITY,
REQ-EVIDENCE, REQ-REPAIR).

Every call goes through an isolated installed package: `bin/t3-plugins` for pins and the
pinned `shared/job_cli.py` / `shared/job_acceptance_cli.py` for job state. Each helper
call is a fresh process, so the coordinator keeps nothing in memory between steps; a
"restart" additionally recovers the package from the job pin before reading the overview.
Worker results are synthetic JSON; validators are the real pinned adapters. No model,
no network, no GitHub.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_ape_validate_report import (descriptor, fingerprint, pin_source,  # noqa: E402
                                             research_findings, research_markdown, synthesis_findings,
                                             synthesis_markdown, write_pin)
from tests.test_rebuild_installed import Sandbox, worker_result  # noqa: E402

CRITERIA = [{'id': 'C-PROVENANCE', 'kind': 'source-provenance'}]
TRANSCRIPT_MARKER = 'RAW-WORKER-TRANSCRIPT-7f3a'


class ApeJob:
    """A five-stage ape forage job: four ordered research stages, each pinning one candidate
    snapshot, then one direct synthesis stage that consumes every accepted research report."""

    STAGES = ('s1', 's2', 's3', 's4', 'final')

    def __init__(self, case, box: Sandbox, job_id: str):
        self.case, self.box, self.job_id = case, box, job_id
        self.pkg, self.manifest = box.install('ape')
        self.caller = box.caller(self.manifest, 'ape/forage')
        self.validator = self.pkg / 'scripts' / 'validate_report.py'
        # Coordinator-owned snapshots and reports, outside job state (snapshot_source.py's layout).
        self.sources = {f's{i}': pin_source(box.private, f'src-{i}') for i in range(1, 5)}
        self.outputs = {s: box.private / 'reports' / f'{s}.md' for s in self.STAGES}

    def stage(self, stage_id):
        sources = list(self.sources.values()) if stage_id == 'final' else [self.sources[stage_id]]
        index = self.STAGES.index(stage_id)
        return {'id': stage_id, 'depends_on': list(self.STAGES[:4]) if stage_id == 'final' else
                [self.STAGES[index - 1]] if index else [],
                'requirements': [f'R{i}' for i in range(1, 5)] if stage_id == 'final' else ['R' + stage_id[1]],
                'status': 'pending', 'execution_mode': 'direct' if stage_id == 'final' else 'workers',
                'validator_dependency': 'ape', 'revision': stage_id + '-r1', 'criteria': CRITERIA,
                'outputs': [str(self.outputs[stage_id])], 'validator_contract': {'sources': sources}}

    def plan(self):
        tasks = [{'task_id': f'{s}-research', 'stage_id': s, 'logical_slot_id': 'primary',
                  'request_id': f'{s}-research-r0', 'dependency_key': 'ape', 'status': 'pending', 'attempt': 0,
                  'worker_id': 'ape/synthesizer' if s == 's4' else 'ape/source-researcher',
                  'handles': [], 'followups': [], 'dispatch_retries': 0,
                  'write_scope': {'mode': 'worker-evidence', 'path': f'artifacts/tasks/{s}-research'}}
                 for s in self.STAGES[:4]]
        return {'schema_version': 1, 'job_id': self.job_id, 'installation_id': self.manifest['installation_id'],
                'workflow': 'ape/forage', 'owner': {'id': 'owner'}, 'objective': 'compare four pinned sources',
                'requirements': {f'R{i}': f'source {i} provenance is pinned and reported' for i in range(1, 5)},
                'authorization': {'actions': ['read']}, 'constraints': ['Research is read-only in the target.'],
                'dependencies': [{'key': 'ape', 'plugin': 'ape'}], 'pins': {},
                'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
                'result_contract': {'schema_version': 1}, 'stages': [self.stage(s) for s in self.STAGES],
                'tasks': tasks, 'decisions': [], 'history': [], 'metrics': {}}

    def create(self):
        self.box.create(self.pkg, self.plan())

    def report(self, stage_id):
        """A complete descriptor under the current ape contract: sections, Provenance, pinned
        revisions and hashes, line citations, coverage and coordinator inspection receipts."""
        finger = fingerprint(self.box.private)
        if stage_id != 'final':
            pin = self.sources[stage_id]
            report = write_pin(self.outputs[stage_id], research_markdown(pin))
            return descriptor('forage-research', [pin], [{'id': 'R' + stage_id[1], 'source_ids': [pin['id']]}],
                              finger, report, research_findings(pin), criteria=CRITERIA)
        pins = list(self.sources.values())
        consumed = [{'id': f'rep-{s}', 'source_id': self.sources[s]['id'],
                     **write_pin(self.outputs[s], research_markdown(self.sources[s]))} for s in self.STAGES[:4]]
        report = write_pin(self.outputs['final'], synthesis_markdown(pins, consumed))
        return descriptor('forage-synthesis', pins, [{'id': f'R{i}', 'source_ids': [f'src-{i}']} for i in range(1, 5)],
                          finger, report, synthesis_findings(pins, consumed), consumed, criteria=CRITERIA)

    def finish_worker(self, stage_id, brief, pkg=None, host=None):
        task = f'{stage_id}-research'
        host = host or f'host-{brief["request_id"]}'
        out = self.box.complete(pkg or self.pkg, self.job_id, self.caller, task, brief, host,
                                worker_result(brief, conclusion=f'{TRANSCRIPT_MARKER} {stage_id}'))
        self.case.assertEqual(out['status'], 'awaiting-acceptance', out)

    def accept(self, stage_id, pkg=None):
        pkg = pkg or self.pkg
        observed = self.box.publish(pkg, self.job_id, self.caller, stage_id, self.report(stage_id))
        proc = self.box.accept(pkg, 'accept-stage', self.job_id, {
            'caller': self.caller, 'stage_id': stage_id, 'revision': stage_id + '-r1', 'input_file': observed,
            'validator_argv': [str(self.validator), '--input', observed]})
        self.case.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def run_stage(self, stage_id):
        if stage_id != 'final':
            brief = self.box.dispatch(self.pkg, self.job_id, self.caller, f'{stage_id}-research',
                                      f'host-{stage_id}-research-r0')
            self.finish_worker(stage_id, brief)
        return self.accept(stage_id)

    def final(self):
        state = self.box.state_of(self.job_id)
        observed = {s['id']: s['observation_ref']['path'] if s.get('observation_ref') else
                    self.box.publish(self.pkg, self.job_id, self.caller, s['id'], self.report(s['id']))
                    for s in state['stages']}
        return self.box.accept(self.pkg, 'validate-final', self.job_id, {
            'caller': self.caller,
            'validator_argv_by_stage': {s: [str(self.validator), '--input', p] for s, p in observed.items()},
            'input_file_by_stage': observed})

    def statuses(self):
        return {s['id']: s['status'] for s in self.box.state_of(self.job_id)['stages']}


class FiveStageRestartTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='t3p-integration-')
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))

    def test_restart_mid_job_resumes_from_overview_with_plan_coverage_decisions_and_handles(self):
        box, job = self.box, ApeJob(self, self.box, 'five-stage')
        job.create()
        job.run_stage('s1')
        job.run_stage('s2')
        # An unresolved cross-stage decision: recorded owner evidence for a later synthesis scope.
        decision = box.owner_decision('d-synthesis', 'Keep synthesis to the four pinned sources.', 'plan:synthesis-scope')
        box.job(job.pkg, 'decision', job.job_id, {'caller': job.caller, 'decision': decision})
        brief = box.dispatch(job.pkg, job.job_id, job.caller, 's3-research', 'host-s3-research-r0')
        plan_before = {k: box.state_of(job.job_id)[k] for k in ('requirements', 'constraints', 'authorization',
                                                                'dependencies', 'pins')}

        # --- restart: a new coordinator holds only the job path ---------------------------
        # A later, independent install moves ape's `current`; the job keeps its pinned package.
        source = box.source_copy('ape', lambda p: (p / 'playbooks' / 'study.md').write_text(
            (p / 'playbooks' / 'study.md').read_text() + '\n<!-- later release -->\n'))
        newer, _ = box.install('ape', source=source)
        self.assertNotEqual(newer, job.pkg)
        pkg = box.pinned_package(job.job_id, 'ape')
        self.assertEqual(pkg, job.pkg)
        wrong = box.job(newer, 'overview', job.job_id, check=False)
        self.assertEqual(wrong.returncode, 2)
        self.assertIn('wrong executing package', wrong.stderr)
        raw = box.job(pkg, 'overview', job.job_id, check=False).stdout
        overview = json.loads(raw)
        self.assertNotIn(TRANSCRIPT_MARKER, raw, 'the overview never ingests worker output')
        self.assertEqual([s['id'] for s in overview['stages']], list(ApeJob.STAGES))
        statuses = {s['id']: s['status'] for s in overview['stages']}
        self.assertEqual((statuses['s1'], statuses['s2']), ('accepted-at-snapshot', 'accepted-at-snapshot'))
        # Not yet accepted. Publishing s2's observation marks every later stage stale, even unstarted ones.
        self.assertLessEqual({statuses[s] for s in ('s3', 's4', 'final')}, {'pending', 'stale'})
        self.assertEqual(overview['current_stage'], 's3')
        self.assertEqual(next(s for s in overview['stages'] if s['id'] == 's4')['depends_on'], ['s3'])
        self.assertEqual(overview['requirement_coverage']['R3'], [{'stage': 's3', 'status': statuses['s3']},
                                                                  {'stage': 'final', 'status': statuses['final']}])
        self.assertEqual(set(overview['requirement_coverage']), {'R1', 'R2', 'R3', 'R4'})
        self.assertEqual([d['id'] for d in overview['decisions']], ['d-synthesis'])
        handles = {h['task_id']: h for h in overview['handles']}
        self.assertEqual(handles['s3-research']['status'], 'running')
        self.assertEqual([(h['task_id'], h['request_id'], h['child_thread_id']) for h in handles['s3-research']['handles']],
                         [('host-s3-research-r0', brief['request_id'], 'child-host-s3-research-r0')])
        self.assertEqual(handles['s1-research']['handles'][0]['status'], 'completed')
        self.assertEqual(handles['s4-research']['handles'], [])
        self.assertEqual({k: box.state_of(job.job_id)[k] for k in plan_before}, plan_before)
        # A missing reply is not a reason to recreate work: the live slot cannot be re-prepared.
        again = box.job(pkg, 'prepare', job.job_id, {'caller': job.caller, 'task_id': 's3-research'}, check=False)
        self.assertEqual(again.returncode, 2)
        self.assertIn('already launched', again.stderr)

        # --- resume: the completion notification arrives for the retained handle ---------
        job.finish_worker('s3', brief, pkg)
        job.accept('s3', pkg)
        job.run_stage('s4')
        job.run_stage('final')
        final = job.final()
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertEqual(set(job.statuses().values()), {'accepted-at-snapshot'})
        done = box.job(pkg, 'overview', job.job_id)
        self.assertIsNone(done['current_stage'])
        self.assertEqual([d['id'] for d in done['decisions']], ['d-synthesis'])

    def test_injected_stage3_regression_is_rejected_by_the_final_integrated_gate(self):
        box, job = self.box, ApeJob(self, self.box, 'regression')
        job.create()
        for stage in ApeJob.STAGES:
            job.run_stage(stage)
        passed = job.final()
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)

        # Stage 3's pinned source changes after every stage was accepted.
        source = Path(job.sources['s3']['path'])
        good = source.read_bytes()
        source.write_text('pinned source 3: retry loop removed\n')
        rejected = job.final()
        self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
        self.assertEqual(json.loads(rejected.stdout)['stage_id'], 's3')
        # The responsible stage reopens, its dependents go stale, earlier stages stay accepted.
        self.assertEqual(job.statuses(), {'s1': 'accepted-at-snapshot', 's2': 'accepted-at-snapshot',
                                          's3': 'failed', 's4': 'stale', 'final': 'stale'})
        state = box.state_of(job.job_id)
        self.assertEqual([h['stage_id'] for h in state['history'] if h.get('kind') == 'final-failure'], ['s3'])
        self.assertTrue(next(s for s in state['stages'] if s['id'] == 's3')['acceptance_history'])
        for stage, accepted in (('s2', 0), ('s3', 1), ('final', 1)):
            proc = box.accept(job.pkg, 'validate', job.job_id, {'stage_id': stage})
            self.assertEqual(proc.returncode, accepted, (stage, proc.stdout))
        # Editing an accepted flag back by hand cannot promote the stage: the validator reruns.
        forged = box.state_of(job.job_id)
        for stage in forged['stages']:
            stage['status'] = 'accepted-at-snapshot'
            stage['acceptance'] = stage['acceptance'] or stage['acceptance_history'][-1]
        (box.jobs / job.job_id / 'job.json').write_text(json.dumps(forged))
        self.assertEqual(job.final().returncode, 1)
        self.assertEqual(job.statuses()['s3'], 'failed')

        # Repair: restore the source, charge one s3 cycle, re-run s3 and its stale dependents.
        source.write_bytes(good)
        for stage in ('s3', 's4'):
            box.job(job.pkg, 'retry', job.job_id, {'caller': job.caller, 'task_id': f'{stage}-research',
                                                   'reason': 'final gate reopened s3'})
            brief = box.dispatch(job.pkg, job.job_id, job.caller, f'{stage}-research', f'host-{stage}-repair')
            job.finish_worker(stage, brief, host=f'host-{stage}-repair')
            job.accept(stage)
        job.accept('final')
        repaired = job.final()
        self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
        state = box.state_of(job.job_id)
        cycles = {s['id']: s.get('cycle', 0) for s in state['stages']}
        self.assertEqual(cycles, {'s1': 0, 's2': 0, 's3': 1, 's4': 1, 'final': 1})
        self.assertEqual(state['final_passes'], 4)


class RepairBudgetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='t3p-repair-')
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))

    def test_initial_plus_three_repairs_then_fifth_pass_refused_across_resume(self):
        box, job = self.box, ApeJob(self, self.box, 'budget')
        job.create()
        task = 's1-research'
        for attempt in range(4):
            # Each pass starts as a restarted coordinator: pinned package, then overview.
            pkg = box.pinned_package(job.job_id, 'ape')
            overview = box.job(pkg, 'overview', job.job_id)
            self.assertEqual(next(s for s in overview['stages'] if s['id'] == 's1').get('cycle', 0), attempt)
            brief = box.dispatch(pkg, job.job_id, job.caller, task, f'host-budget-{attempt}')
            self.assertEqual((brief['attempt'], brief['max_attempts']), (attempt, 4))
            done = f'host-budget-{attempt}-done'
            box.job(pkg, 'task-observation', job.job_id, {'caller': job.caller, 'task_id': task, 'event': {
                'kind': 'completion', 'request_id': brief['request_id'], 'host_task_id': f'host-budget-{attempt}',
                'child_thread_id': f'child-host-budget-{attempt}', 'completion_id': done, 'status': 'completed',
                'work_state': 'result_available', 'has_pending_child_runs': False}})
            out = box.job(pkg, 'result', job.job_id, {'caller': job.caller, 'task_id': task,
                                                      'request_id': brief['request_id'], 'completion_id': done,
                                                      'result': {'json': 'Done.\n' + worker_result(brief)}})
            self.assertEqual((out['status'], out['last_execution_status'], out['attempt']),
                             ('failed', 'malformed-result', attempt + 1))
            retry = box.job(pkg, 'retry', job.job_id, {'caller': job.caller, 'task_id': task,
                                                       'reason': 'malformed result',
                                                       'category': ('primary', 'support', 'review', 'primary')[attempt]},
                            check=False)
            if attempt < 3:
                self.assertEqual(retry.returncode, 0, retry.stderr)
            else:
                self.assertEqual(retry.returncode, 2)
                self.assertIn('budget exhausted', retry.stderr)
        pkg = box.pinned_package(job.job_id, 'ape')
        fifth = box.job(pkg, 'prepare', job.job_id, {'caller': job.caller, 'task_id': task}, check=False)
        self.assertEqual(fifth.returncode, 2)
        stage = next(s for s in box.state_of(job.job_id)['stages'] if s['id'] == 's1')
        self.assertEqual((stage['cycle'], stage['attempts']['primary'] + stage['attempts']['support']
                          + stage['attempts']['review']), (3, 3))

        # An owner-approved escalation to another target keeps the slot's spent attempts.
        state = box.state_of(job.job_id)
        tasks = [dict(t, target={'providerInstanceId': 'escalated', 'model': 'fixture-larger', 'lineage': 'l-2'})
                 if t['task_id'] == task else t for t in state['tasks']]
        unapproved = box.job(pkg, 'plan-revision', job.job_id, {'caller': job.caller, 'revision': {'id': 'esc-0'},
                                                                'new_plan': {'tasks': tasks}}, check=False)
        self.assertEqual(unapproved.returncode, 2)
        self.assertIn('undeclared_expansion', unapproved.stderr)
        decision = box.owner_decision('d-esc', 'Escalate s1 to the larger configured tier.', 'plan:esc-1')
        box.job(pkg, 'decision', job.job_id, {'caller': job.caller, 'decision': decision})
        box.job(pkg, 'plan-revision', job.job_id, {'caller': job.caller,
                                                   'revision': {'id': 'esc-1', 'owner_decision_id': 'd-esc'},
                                                   'new_plan': {'tasks': tasks}})
        self.assertEqual(next(t for t in box.state_of(job.job_id)['tasks'] if t['task_id'] == task)['attempt'], 4)
        for command, data in (('prepare', {'caller': job.caller, 'task_id': task}),
                              ('retry', {'caller': job.caller, 'task_id': task, 'reason': 'escalated'})):
            refused = box.job(pkg, command, job.job_id, data, check=False)
            self.assertEqual(refused.returncode, 2, command)

        # The integrated final gate has its own budget: four passes, then the fifth is refused.
        for _ in range(4):
            self.assertEqual(job.final().returncode, 1)
        exhausted = job.final()
        self.assertEqual(exhausted.returncode, 2)
        self.assertIn('final pass budget exhausted', exhausted.stderr)
        self.assertEqual(box.state_of(job.job_id)['final_passes'], 4)


class CrossPluginPinTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='t3p-pins-')
        self.addCleanup(self._tmp.cleanup)
        self.box = Sandbox(Path(self._tmp.name))

    def test_imps_job_babysitter_pin_survives_an_independent_current_change(self):
        box = self.box
        imps, manifest = box.install('imps')
        old_baby, _ = box.install('babysitter')
        caller = box.caller(manifest, 'imps/prs')
        job = {'schema_version': 1, 'job_id': 'imps-prs', 'installation_id': manifest['installation_id'],
               'workflow': 'imps/prs', 'owner': {'id': 'owner'}, 'objective': 'maintain one synthetic PR',
               'requirements': {'R1': 'the PR has current required checks'},
               'authorization': {'actions': ['read']}, 'constraints': ['No pushes or merges.'],
               'dependencies': [{'key': 'imps', 'plugin': 'imps'}, {'key': 'babysitter', 'plugin': 'babysitter'}],
               'pins': {}, 'policy': {'max_repair_cycles': 3, 'max_artifact_bytes': 16777216},
               'result_contract': {'schema_version': 1},
               'stages': [{'id': 'triage', 'depends_on': [], 'requirements': ['R1'], 'status': 'pending',
                           'execution_mode': 'workers', 'validator_dependency': 'babysitter', 'revision': 'triage-r1'}],
               'tasks': [{'task_id': 'maintain', 'stage_id': 'triage', 'logical_slot_id': 'primary',
                          'request_id': 'maintain-r0', 'worker_id': 'babysitter/pr-maintainer',
                          'dependency_key': 'babysitter', 'status': 'pending', 'attempt': 0, 'handles': [],
                          'followups': [], 'dispatch_retries': 0}],
               'decisions': [], 'history': [], 'metrics': {}}
        box.create(imps, job)
        job_file = box.jobs / 'imps-prs' / 'job.json'
        pinned_bytes = job_file.read_bytes()
        old_definition = (old_baby / 'agents' / 'pr-maintainer.md').read_text()

        # Independently, a newer babysitter is installed and becomes `current`.
        marker = 'Later release: a changed maintainer definition.'
        source = box.source_copy('babysitter', lambda p: (p / 'agents' / 'pr-maintainer.md').write_text(
            (p / 'agents' / 'pr-maintainer.md').read_text() + '\n' + marker + '\n'))
        new_baby, _ = box.install('babysitter', source=source)
        self.assertNotEqual(new_baby, old_baby)
        self.assertEqual(Path(box.t3('path', 'babysitter').stdout.strip()).parent.resolve(), new_baby)
        # The job still resolves its pin; an undeclared plugin is refused.
        self.assertEqual(box.pinned_package('imps-prs', 'babysitter'), old_baby)
        self.assertEqual(box.pinned_package('imps-prs', 'imps'), imps)
        undeclared = box.t3('--job', job_file, 'path', 'ape', check=False)
        self.assertEqual(undeclared.returncode, 2)
        self.assertIn('undeclared job dependency', undeclared.stderr)
        self.assertEqual(job_file.read_bytes(), pinned_bytes, 'a current-pointer change never rewrites job pins')
        overview = box.job(imps, 'overview', 'imps-prs')
        self.assertEqual(overview['stages'][0]['status'], 'pending')
        # The next brief composes the pinned babysitter definition, not the newer current one.
        prepared = box.job(imps, 'prepare', 'imps-prs', {'caller': caller, 'task_id': 'maintain',
                                                         'target_reason': 'workhorse tier'})
        brief = json.loads(Path(prepared['path']).read_text())
        self.assertIn(old_definition, brief['effective_definition']['bytes'])
        self.assertNotIn(marker, brief['effective_definition']['bytes'])
        self.assertEqual(brief['effective_definition'],
                         json.loads(pinned_bytes)['pins']['babysitter']['effective_workers']['babysitter/pr-maintainer'])
        # Rolling `current` back and forth leaves the pin intact, and the pinned version cannot be removed.
        box.t3('activate', 'babysitter', old_baby.name)
        box.t3('activate', 'babysitter', new_baby.name)
        refused = box.t3('uninstall', 'babysitter', '--version', old_baby.name, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('version_referenced', refused.stdout)
        self.assertTrue((old_baby / 'entry.md').is_file())
        self.assertEqual(box.pinned_package('imps-prs', 'babysitter'), old_baby)
        shutil.rmtree(source)


if __name__ == '__main__':
    unittest.main()
