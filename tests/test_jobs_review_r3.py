"""Regression coverage for Stage 3 repair findings S3-R3-01..07.

All host observations and owner records are synthetic local fixtures. These
tests exercise the public job API; subprocess cleanup uses only owned fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs import JobError, create_job, decision, prepare, record_dispatch, record_result, revise_plan, retry_task
from core.jobs.store import Store, _atomic, canonical, digest
from shared.job_acceptance import AcceptanceError, _bounded_run, accept_stage


class Stage3Repair5Tests(unittest.TestCase):
    def setUp(self):
        from tests.test_jobs_review import JobReviewTests
        self.fx = JobReviewTests()

    def caller(self):
        return {"installation_id": "install-fixture", "workflow": "ape/review-fixture",
                "package_digest": "a" * 64, "actor": "coordinator"}

    def store(self, root, job_id="repair5"):
        job = self.fx.base_job(job_id)
        job["pins"]["ape"]["effective_workers"] = {
            "ape/source-researcher": {"bytes": "synthetic pinned worker", "sha256": "b" * 64}}
        create_job(job, root, job["pins"])
        return Store(root, job_id)

    def accepted_handle(self, store):
        record_dispatch(store, self.caller(), "t0", {"kind": "accepted", "request_id": "req0",
            "host_task_id": "host0", "status": "running", "work_state": "working",
            "has_pending_child_runs": False})

    def test_worker_observation_traversal_is_refused_without_mutating_job(self):
        from shared.job_coordinator import publish_observation
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            store.verify_pins = lambda job: None  # This fixture isolates input ownership.
            worker = store.path / 'artifacts/tasks/t0/result.json'
            worker.parent.mkdir(parents=True)
            worker.write_text('{}')
            (store.path / 'tmp').mkdir()
            stage_id = store.load()['stages'][0]['id']
            before = store.file.read_bytes()
            for path in (worker, store.path / 'tmp/../artifacts/tasks/t0/result.json'):
                with self.subTest(path=path), self.assertRaises(JobError):
                    publish_observation(store, self.caller(), stage_id, path)
                self.assertEqual(store.file.read_bytes(), before)
                self.assertFalse((store.path / 'observations').exists())
            outside = Path(td) / 'coordinator.json'
            outside.write_text('{}')
            published = publish_observation(store, self.caller(), stage_id, outside)
            self.assertEqual(published['sha256'], digest(outside.read_bytes()))

    def test_r3_01_uncertainty_after_accepted_handle_is_refused_and_live_retry_refused(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td); self.accepted_handle(store)
            with self.assertRaises(JobError):
                record_dispatch(store, self.caller(), "t0", {"kind": "uncertain", "request_id": "req0"})
            state = store.load(); self.assertEqual(state["tasks"][0]["status"], "running")
            # A terminal original remains reconcilable and is a positive control.
            record_dispatch(store, self.caller(), "t0", {"kind": "reconciled", "request_id": "req0",
                "host_task_id": "host0", "status": "completed", "work_state": "result_available",
                "has_pending_child_runs": False})
            self.assertEqual(store.load()["tasks"][0]["status"], "awaiting-acceptance")

    def test_r3_02_old_terminal_handle_never_overwrites_new_current_request(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td); self.accepted_handle(store)
            # Model an already charged replacement request while retaining old history.
            state = store.load(); task = state["tasks"][0]
            task.update(status="pending", request_id="req0-deadbeef-a1")
            _atomic(store.file, canonical(state))
            record_dispatch(store, self.caller(), "t0", {"kind": "reconciled", "request_id": "req0",
                "host_task_id": "host0", "status": "completed", "work_state": "result_available",
                "has_pending_child_runs": False})
            task = store.load()["tasks"][0]
            self.assertEqual(task["status"], "pending")
            self.assertEqual(task["request_id"], "req0-deadbeef-a1")
            self.assertEqual(task["handles"][0]["status"], "completed")

    def test_r3_02_retry_refuses_stale_slot_with_live_or_pending_child(self):
        for child_pending in (False, True):
            with self.subTest(child_pending=child_pending), tempfile.TemporaryDirectory() as td:
                store = self.store(td); self.accepted_handle(store)
                state = store.load(); state["tasks"][0]["status"] = "failed"
                state["tasks"][0]["handles"][0]["has_pending_child_runs"] = child_pending
                _atomic(store.file, canonical(state))
                with self.assertRaises(JobError):
                    retry_task(store, self.caller(), "t0", "fixture retry")

    def test_r3_03_worker_artifact_cannot_source_owner_decision_but_external_source_can(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            worker_source = store.path / "artifacts/tasks/t0/owner-note.txt"
            worker_source.parent.mkdir(parents=True); worker_source.write_text("Owner approves waiver R1.\n")
            worker_record = {"id": "d-worker", "quote": "approves waiver R1", "source": str(worker_source),
                "source_sha256": digest(worker_source.read_bytes()), "scope": "waiver:t0", "requirement_ids": ["R1"]}
            with self.assertRaises(JobError):
                decision(store, self.caller(), worker_record)
            external = Path(td) / "owner-record.txt"
            external.write_text("Owner approves waiver R1 for this fixture.\n")
            owner_record = {"id": "d-owner", "quote": "approves waiver R1", "source": str(external),
                "source_sha256": digest(external.read_bytes()), "scope": "waiver:t0", "requirement_ids": ["R1"]}
            decision(store, self.caller(), owner_record)
            self.assertEqual(store.load()["decisions"][0]["id"], "d-owner")

    def test_r3_04_accept_stage_timeout_writes_failed_receipt_and_keeps_charge(self):
        from tests.test_jobs_review import JobReviewTests
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); fx = JobReviewTests(); version, manifest, prefix, agents, state_root = fx.install(root, "ape")
            job = fx.base_job("timeout-receipt"); job["installation_id"] = manifest["installation_id"]
            job["pins"] = {}; job["dependencies"] = [{"key": "ape", "plugin": "ape"}]
            job["tasks"] = []; job["stages"] = [job["stages"][0]]
            job["stages"][0].update(execution_mode="direct", validator_dependency="ape", revision="r1")
            from tests.test_ape_validate_report import pin_source, study_descriptor
            job["stages"][0]["validator_contract"] = {"sources": [pin_source(root, "src")]}
            from shared.job_coordinator import create_pinned_job, publish_observation
            from core.jobs.store import Store
            create_pinned_job(job, state_root, prefix, agents, root / "config/workers.json")
            store = Store(state_root, job["job_id"])
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"],
                "package_digest": manifest["package_digest"], "actor": "coordinator"}
            obs = root / "observation.json"; obs.write_text(json.dumps(study_descriptor(
                root, job["stages"][0]["validator_contract"]["sources"][0], job["stages"][0]["requirements"],
                job["stages"][0]["criteria"])))
            ref = publish_observation(store, caller, "s0", str(obs))
            validator = version / "scripts/validate_report.py"
            from shared import job_acceptance
            def eof_then_hang(job_data, stage, argv, input_file, binding):
                _bounded_run([sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(5)"],
                    root, {"timeout_seconds": 0.2, "max_output_bytes": 1024})
            with mock.patch.object(job_acceptance, "_invoke", side_effect=eof_then_hang):
                result = accept_stage(store, caller, "s0", [str(validator), "--input", ref["path"]], ref["path"], "r1")
            self.assertFalse(result["accepted"], result)
            after = store.load(); self.assertEqual(after["stages"][0]["status"], "failed")
            self.assertEqual(after["stages"][0]["acceptance_runs"], 1)
            receipts = list((store.path / "acceptance").glob("*.json"))
            self.assertEqual(len(receipts), 1); self.assertFalse(json.loads(receipts[0].read_text())["accepted"])

    def test_r3_05_leader_exit_cleans_owned_background_process_group(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "child.pid"
            command = [sys.executable, "-c", "import subprocess,sys,os,json; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); open(sys.argv[1],'w').write(json.dumps({'child':p.pid,'group':os.getpgrp()})); print('leader done')", str(marker)]
            with self.assertRaises(AcceptanceError):
                _bounded_run(command, td, {"timeout_seconds": 0.25, "max_output_bytes": 1024})
            if marker.exists():
                owned = json.loads(marker.read_text()); pid = owned['child']
                try:
                    state = Path("/proc") / str(pid) / "stat"
                    deadline = time.monotonic() + 1
                    while state.exists() and state.read_text().split()[2] not in ('Z', 'X') and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if state.exists(): self.assertIn(state.read_text().split()[2], ('Z', 'X'))
                finally:
                    try: os.killpg(owned['group'], signal.SIGKILL)
                    except ProcessLookupError: pass

    def test_r3_06_execution_mode_change_stales_prior_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td); state = store.load()
            state["stages"][0].update(status="accepted-at-snapshot", acceptance={"sha256": "c" * 64})
            state["stages"][1].update(status="accepted-at-snapshot", acceptance={"sha256": "e" * 64})
            _atomic(store.file, canonical(state))
            new = store.load(); new["stages"][0]["execution_mode"] = "direct"
            # Removing the only task is permitted only with owner evidence; keep the
            # slot and revise an unrelated stage field to isolate invalidation.
            source = Path(td) / "plan-owner.txt"; source.write_text("Owner approves execution mode change.\n")
            decision(store, self.caller(), {"id": "plan-decision", "quote": "approves execution mode change",
                "source": str(source), "source_sha256": digest(source.read_bytes()), "scope": "plan:mode"})
            revise_plan(store, self.caller(), {"id": "mode", "owner_decision_id": "plan-decision"}, new)
            after = store.load()
            self.assertEqual(after["stages"][0]["status"], "stale")
            self.assertEqual(after["stages"][1]["status"], "stale")

    def test_r3_02_affected_revision_preserves_live_handle_identity_and_brief(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td); self.accepted_handle(store)
            state = store.load(); task = state["tasks"][0]
            (store.path / "briefs").mkdir(exist_ok=True)
            brief = store.path / "briefs/t0.json"; brief.write_text("synthetic immutable brief")
            task["brief"] = {"path": str(brief), "sha256": digest(brief.read_bytes())}
            _atomic(store.file, canonical(state))
            new = store.load(); new["stages"][0]["revision"] = "s0-r2"
            owner_source = Path(td) / "plan-owner.txt"; owner_source.write_text("Owner approves revision change.\n")
            decision(store, self.caller(), {"id": "plan-revision", "quote": "approves revision change",
                "source": str(owner_source), "source_sha256": digest(owner_source.read_bytes()), "scope": "plan:rev"})
            revise_plan(store, self.caller(), {"id": "rev", "owner_decision_id": "plan-revision"}, new)
            after = store.load()["tasks"][0]
            self.assertEqual(after["status"], "running")
            self.assertEqual(after["handles"][0]["task_id"], "host0")
            self.assertTrue(Path(after["brief"]["path"]).exists())
            self.assertTrue(after['inputs_stale'])
            with self.assertRaises(JobError):
                retry_task(store, self.caller(), 't0', 'cannot replace live handle')

    def test_r3_07_oversized_state_rejected_before_json_parse(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td); raw = store.file.read_bytes()
            # Make a syntactically invalid body beyond the documented ceiling; the
            # error should identify size, proving parsing was not attempted.
            store.file.write_bytes(b"{" + b" " * (16 * 1024 * 1024 + 1))
            started = time.monotonic()
            with self.assertRaisesRegex(JobError, "oversized|byte limit|size"):
                store.load()
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertGreater(len(raw), 0)

    def test_plan_preserves_omitted_runtime_and_exhausted_uncertainty(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            for _ in range(3):
                record_dispatch(store, self.caller(), 't0', {'kind': 'uncertain', 'request_id': 'req0'})
            before = store.load()['tasks'][0]
            plan = store.load()
            keep = {'task_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'dependency_key', 'write_scope'}
            plan['tasks'][0] = {k: v for k, v in before.items() if k in keep}
            revise_plan(store, self.caller(), {'id': 'omit-runtime'}, plan)
            before.setdefault('cycle', 0)
            self.assertEqual(store.load()['tasks'][0], before)
            with self.assertRaises(JobError):
                prepare(store, self.caller(), 't0', lambda *_: True, lambda *_: True)
            with self.assertRaises(JobError):
                record_dispatch(store, self.caller(), 't0', {'kind': 'uncertain', 'request_id': 'req0'})

    def test_plan_rejects_live_request_rebinding_and_runtime_injection(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            prepare(store, self.caller(), 't0', lambda *_: True, lambda *_: True)
            self.accepted_handle(store)
            before = store.file.read_bytes()
            for field, value in (('request_id', 'replacement'), ('uncertain_calls', 0),
                                 ('capacity_retry_events', ['fake']), ('brief', {}),
                                 ('prepared_followup', {'request_id': 'fake'}), ('reconciliation', [])):
                plan = store.load(); plan['tasks'][0][field] = value
                with self.subTest(field=field), self.assertRaises(JobError):
                    revise_plan(store, self.caller(), {'id': 'inject-' + field}, plan)
                self.assertEqual(store.file.read_bytes(), before)
            self.assertEqual(len(store.load()['tasks'][0]['handles']), 1)

    def test_revision_and_decision_identity_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            source = Path(td) / 'owner.txt'; source.write_text('approve exactly one limit expansion')
            owner = {'id': 'owner-limit', 'scope': 'plan:limit-one', 'quote': source.read_text(),
                     'source': str(source), 'source_sha256': digest(source.read_bytes())}
            decision(store, self.caller(), owner)
            plan = store.load(); plan['policy']['max_repair_cycles'] = 4
            revision = {'id': 'limit-one', 'owner_decision_id': 'owner-limit'}
            revise_plan(store, self.caller(), revision, plan)
            before = store.file.read_bytes()
            for limit in (4, 5):
                plan = store.load(); plan['policy']['max_repair_cycles'] = limit
                with self.subTest(limit=limit), self.assertRaises(JobError):
                    revise_plan(store, self.caller(), revision, plan)
                self.assertEqual(store.file.read_bytes(), before)
            with self.assertRaises(JobError):
                decision(store, self.caller(), {**owner, 'scope': 'plan:limit-two'})
            plan = store.load(); plan['policy']['max_repair_cycles'] = 5
            with self.assertRaises(JobError):
                revise_plan(store, self.caller(), {'id': 'limit-two', 'owner_decision_id': 'owner-limit'}, plan)
            decision(store, self.caller(), {**owner, 'id': 'owner-two', 'scope': 'plan:limit-two'})
            revise_plan(store, self.caller(), {'id': 'limit-two', 'owner_decision_id': 'owner-two'}, plan)
            self.assertEqual(store.load()['policy']['max_repair_cycles'], 5)
            self.assertEqual(len(store.load()['plan_revisions']), 2)

    def test_worker_source_alias_and_symlink_cannot_be_authority(self):
        from shared.job_coordinator import publish_observation
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td); store.verify_pins = lambda job: None
            worker = store.path / 'artifacts/tasks/t0/source.txt'
            worker.parent.mkdir(parents=True); worker.write_text('{}')
            alias = Path('//' + str(worker).lstrip('/'))
            outside = Path(td) / 'external.txt'; outside.write_text('{}')
            link = Path(td) / 'source-link'; link.symlink_to(outside)
            before = store.file.read_bytes()
            for path in (alias, link):
                with self.subTest(path=path), self.assertRaises((JobError, OSError)):
                    publish_observation(store, self.caller(), 's0', path)
                with self.subTest(owner_path=path), self.assertRaises((JobError, OSError)):
                    decision(store, self.caller(), {'id': 'alias', 'scope': 'plan:alias', 'quote': '{}',
                        'source': str(path), 'source_sha256': digest(b'{}')})
                self.assertEqual(store.file.read_bytes(), before)
            published = publish_observation(store, self.caller(), 's0', outside)
            self.assertEqual(published['sha256'], digest(b'{}'))

    def test_original_uncertainty_cannot_be_cleared_by_charged_retry(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            for _ in range(3):
                record_dispatch(store, self.caller(), 't0', {'kind': 'uncertain', 'request_id': 'req0'})
            with self.assertRaises(JobError):
                retry_task(store, self.caller(), 't0', 'do not replace an unreconciled original')
            self.assertEqual(store.load()['tasks'][0]['request_id'], 'req0')
            self.assertEqual(store.load()['tasks'][0]['uncertain_calls'], 3)

    def test_old_terminal_observation_after_public_retry_leaves_new_prepare_usable(self):
        with tempfile.TemporaryDirectory() as td:
            store = self.store(td)
            ref = prepare(store, self.caller(), 't0', lambda *_: True, lambda *_: True)
            self.accepted_handle(store)
            event = {'kind': 'reconciled', 'request_id': 'req0', 'host_task_id': 'host0',
                     'status': 'completed', 'work_state': 'result_available', 'has_pending_child_runs': False}
            record_dispatch(store, self.caller(), 't0', event)
            # R16-ST-01: the terminal result is imported before a charged replacement supersedes its request.
            brief = json.loads(Path(ref['path']).read_text())
            result = self.fx.valid_result()
            for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision'):
                result[key] = brief[key]
            result['binding'] = brief['snapshot']
            result['requirements'] = [{'id': r['id'], 'status': 'passed', 'evidence': ['fixture']} for r in brief['requirements']]
            record_result(store, self.caller(), 't0', {'request_id': 'req0', 'completion_id': 'req0-done',
                                                       'result': json.dumps(result).encode()})
            retry_task(store, self.caller(), 't0', 'charged repair')
            current = store.load()['tasks'][0]['request_id']
            record_dispatch(store, self.caller(), 't0', event)
            self.assertEqual(store.load()['tasks'][0]['request_id'], current)
            self.assertEqual(store.load()['tasks'][0]['status'], 'pending')
            prepared = prepare(store, self.caller(), 't0', lambda *_: True, lambda *_: True)
            self.assertEqual(prepared['provenance']['request_id'], current)


if __name__ == "__main__":
    unittest.main()
