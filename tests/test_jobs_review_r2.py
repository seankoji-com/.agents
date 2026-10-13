"""Focused Stage 3 r2 repair support probes (offline, synthetic evidence only).

This module intentionally does not inherit the r1 TestCase: it reuses only its
fixture builders so unittest will not execute the older matrix twice.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs import JobError, create_job, decision, prepare, record_dispatch, retry_task, revise_plan
from core.jobs.store import Store, _atomic, canonical, digest
from shared.job_acceptance import AcceptanceError, _adapter, _bounded_run, _semantic_binding
from shared.job_coordinator import verify_pinned_dependency

# Reuse fixture constructors without inheriting or registering their tests.
class R2ReviewSupportTests(unittest.TestCase):
    def setUp(self):
        from tests.test_jobs_review import JobReviewTests
        self.fx = JobReviewTests()

    def _preparable_store(self, root):
        job = self.fx.base_job()
        job["pins"]["ape"]["effective_workers"] = {
            "ape/source-researcher": {"bytes": "synthetic pinned worker definition", "sha256": "a" * 64}
        }
        create_job(job, root, job["pins"])
        return Store(root, job["job_id"])

    def test_r2_01_public_disposition_records_actual_evidence_and_binding(self):
        """R2-01: dispositions must be a coordinator API, not job.json surgery."""
        from shared import job_coordinator

        self.assertTrue(callable(getattr(job_coordinator, "dispose_finding", None)))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self.fx.make_store(root)
            caller = self.fx.caller()
            task = store.load()["tasks"][0]
            task["finding_dispositions"] = [{"finding_id": "F-1", "finding": {"id": "F-1", "severity": "major"}, "disposition": None}]
            state = store.load()
            state["tasks"][0]["finding_dispositions"] = task["finding_dispositions"]
            _atomic(store.file, canonical(state))  # metadata-only negative/fixture setup
            evidence = root / "repair-evidence.txt"
            evidence.write_bytes(b"synthetic repair evidence: F-1 corrected\n")
            ref = {"path": str(evidence), "sha256": digest(evidence.read_bytes()), "bytes": evidence.stat().st_size}
            before = _semantic_binding(store.load(), store.load()["stages"][0])
            job_coordinator.dispose_finding(store, caller, "t0", "F-1", "fixed", ref)
            after_state = store.load()
            after = _semantic_binding(after_state, after_state["stages"][0])
            row = after_state["tasks"][0]["finding_dispositions"][0]
            self.assertEqual(row["disposition"], "fixed")
            self.assertEqual(Path(row["evidence"]["path"]).read_bytes(), evidence.read_bytes())
            self.assertEqual(row["evidence"]["sha256"], ref["sha256"])
            self.assertEqual(row["evidence"]["bytes"], ref["bytes"])
            self.assertNotEqual(before, after)
            self.assertTrue(any(h.get("kind") == "finding-disposition" for h in after_state["history"]))

    def test_r2_02_uncertain_exhaustion_blocks_new_prepare_but_reconciles_original(self):
        """R2-02: the fourth launch is refused; discovered original IDs remain reconcilable."""
        with tempfile.TemporaryDirectory() as td:
            store = self._preparable_store(td)
            caller = self.fx.caller()
            for _ in range(3):
                record_dispatch(store, caller, "t0", {"kind": "uncertain", "request_id": "req0"})
            with self.assertRaises((JobError, AcceptanceError)):
                prepare(store, caller, "t0", lambda *_: True, lambda *_: True)
            with self.assertRaises(JobError):
                record_dispatch(store, caller, "t0", {"kind": "uncertain", "request_id": "req0"})
            record_dispatch(store, caller, "t0", {"kind": "accepted", "request_id": "req0", "host_task_id": "host-original"})
            with self.assertRaises(JobError):
                record_dispatch(store, caller, "t0", {"kind": "uncertain", "request_id": "req0"})
            record_dispatch(store, caller, "t0", {
                "kind": "reconciled", "request_id": "req0", "host_task_id": "host-original",
                "status": "completed", "work_state": "result_available", "has_pending_child_runs": False,
            })
            self.assertEqual(store.load()["tasks"][0]["handles"][0]["task_id"], "host-original")

    def test_r2_03_decision_source_quote_is_verified_from_actual_bytes(self):
        """R2-03: source-byte integrity is tested; caller ownership remains declarative."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._preparable_store(root)
            source = root / "owner-note.txt"
            source.write_bytes(b"Owner approved the bounded repair for issue 28.\n")
            base = {"id": "d1", "quote": "Owner approved the bounded repair", "source": str(source),
                    "source_sha256": digest(source.read_bytes()), "scope": "plan:revision-1"}
            decision(store, self.fx.caller(), base)
            with self.assertRaises(JobError):
                decision(store, self.fx.caller(), {**base, "id": "d2", "quote": "not present in bytes"})
            with self.assertRaises(JobError):
                decision(store, self.fx.caller(), {**base, "id": "d3", "source_sha256": "0" * 64})

    def test_r2_04_ape_validator_derives_status_from_pinned_sources(self):
        """R2-04: installed validator consumes source bytes and findings, not plan status."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state_root = self.fx.install(root, "ape")
            validator = version / "scripts" / "validate_report.py"
            from tests.test_ape_validate_report import pin_source, study_descriptor
            source_pin = pin_source(root, "S-1")
            criteria = [{"id": "provenance", "kind": "source-provenance"},
                        {"id": "coverage", "kind": "finding-source-coverage"}]
            job = self.fx.base_job("ape-pins-r2")
            job["installation_id"] = manifest["installation_id"]
            job["pins"] = {}
            job["stages"][0]["criteria"] = criteria
            job["stages"][0]["validator_contract"] = {"sources": [source_pin]}
            from shared.job_coordinator import create_pinned_job, pinned_store, publish_observation
            create_pinned_job(job, state_root, prefix, agents, root / "config" / "workers.json")
            store = pinned_store(state_root, job["job_id"])
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"],
                      "package_digest": manifest["package_digest"], "actor": "coordinator"}
            report = root / "report.json"
            data = study_descriptor(root, source_pin, job["stages"][0]["requirements"], criteria)
            def run():
                report.write_text(json.dumps(data))
                ref = publish_observation(store, caller, "s0", str(report))
                return subprocess.run([sys.executable, str(validator), "--input", ref["path"]], capture_output=True, text=True)
            good = run()
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            data["criteria"][0]["status"] = "passed"
            forged = run()
            self.assertNotEqual(forged.returncode, 0, forged.stdout)
            data["criteria"][0].pop("status")
            data["findings"][0]["quote"] = "not in pinned source"
            bad_quote = run()
            self.assertNotEqual(bad_quote.returncode, 0, bad_quote.stdout)

    def test_r2_05_coordinator_observation_is_frozen_and_worker_artifact_rejected(self):
        """R2-05: validators consume published coordinator input references only."""
        from shared import job_coordinator

        self.assertTrue(callable(getattr(job_coordinator, "publish_observation", None)))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Use an actual pinned install and task-scoped store.
            version, manifest, prefix, agents, state_root = self.fx.install(root, "ape")
            job = self.fx.base_job("observation-r2")
            job["installation_id"] = manifest["installation_id"]
            job["pins"] = {}
            from shared.job_coordinator import create_pinned_job
            create_pinned_job(job, state_root, prefix, agents, root / "config" / "workers.json")
            from shared.job_coordinator import pinned_store
            store = pinned_store(state_root, job["job_id"])
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"],
                      "package_digest": manifest["package_digest"], "actor": "coordinator"}
            source = root / "coordinator-observation.json"
            source.write_bytes(b'{"criterion":"from coordinator"}\n')
            ref = job_coordinator.publish_observation(store, caller, "s0", str(source))
            self.assertEqual(Path(ref["path"]).read_bytes(), source.read_bytes())
            self.assertEqual(ref["sha256"], digest(source.read_bytes()))
            worker_artifact = store.path / "artifacts" / "tasks" / "t0" / "input.json"
            worker_artifact.parent.mkdir(parents=True, exist_ok=True)
            worker_artifact.write_bytes(source.read_bytes())
            with self.assertRaises((JobError, AcceptanceError, OSError)):
                _adapter(store.load(), store.load()["stages"][0],
                         [str(version / "scripts" / "validate_report.py"), "--input", str(worker_artifact)],
                         str(worker_artifact))

    def test_r2_06_pr_contract_binds_empty_policy_required_checks_and_endstate(self):
        """R2-06: legitimate optional failure is tolerated; contract mismatch is rejected."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state_root = self.fx.install(root, "babysitter")
            validator = version / "scripts" / "validate_pr.py"
            head = "a" * 40
            endstate = {"requested": "mergeable", "observed": "mergeable", "authorization_ref": "d1"}
            checks = [{"context": "ci", "conclusion": "success", "head_sha": head},
                      {"context": "optional", "conclusion": "failure", "head_sha": head}]
            data = {"pr": "fixture/1", "head_sha": head, "required_contexts": ["ci"],
                    "required_checks": checks, "optional_contexts": ["optional"],
                    "allow_empty_required_contexts": False, "review_threads": [], "authorized_endstate": endstate}
            fields = ("pr", "head_sha", "required_contexts", "required_checks", "review_threads",
                      "authorized_endstate", "allow_empty_required_contexts", "optional_contexts")
            content = {k: data[k] for k in fields}
            data["host_observations"] = [{"observer": "coordinator", "kind": "pr-state", "source": "synthetic",
                                          "content": content, "sha256": digest(canonical(content)),
                                          "allow_empty_required_contexts": False}]
            input_path = root / "pr.json"
            input_path.write_text(json.dumps(data))
            job = self.fx.base_job("pr-contract-r2")
            job["installation_id"] = manifest["installation_id"]
            job["dependencies"] = [{"key": "bs", "plugin": "babysitter"}]
            job["pins"] = {}
            job["tasks"][0]["dependency_key"] = "bs"
            job["stages"][0]["validator_dependency"] = "bs"
            job["stages"][0]["validator_contract"] = {k: data[k] for k in fields}
            from shared.job_coordinator import create_pinned_job, pinned_store, publish_observation
            create_pinned_job(job, state_root, prefix, agents, root / "config" / "workers.json")
            store = pinned_store(state_root, job["job_id"])
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"],
                      "package_digest": manifest["package_digest"], "actor": "coordinator"}
            ref = publish_observation(store, caller, "s0", str(input_path))
            stage = store.load()["stages"][0]
            argv = [str(validator), "--input", ref["path"]]
            self.assertEqual(stage["validator_contract"], {k: data[k] for k in fields})
            frozen_data = json.loads(Path(ref["path"]).read_text())
            self.assertEqual({k: frozen_data.get(k) for k in stage["validator_contract"]}, stage["validator_contract"])
            # The installed validator itself confirms the declared optional failure policy.
            proc = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(os.path.realpath(_adapter(store.load(), stage, argv, ref["path"])[0]), os.path.realpath(validator))
            stage["validator_contract"]["required_checks"] = []
            with self.assertRaises(AcceptanceError):
                _adapter(store.load(), stage, argv, ref["path"])
            stage["validator_contract"]["required_checks"] = checks
            data["required_contexts"] = []
            data["required_checks"] = []
            data["allow_empty_required_contexts"] = True
            updated_contract = {k: data[k] for k in fields}
            new_plan = store.load()
            new_plan["stages"][0]["validator_contract"] = updated_contract
            owner_source = root / "empty-policy-owner.txt"
            owner_source.write_bytes(b"Owner permits an explicitly observed empty required-context policy.\n")
            decision(store, caller, {"id": "empty-policy", "quote": "Owner permits an explicitly observed empty required-context policy",
                                     "source": str(owner_source), "source_sha256": digest(owner_source.read_bytes()),
                                     "scope": "plan:empty-policy"})
            revise_plan(store, caller, {"id": "empty-policy", "owner_decision_id": "empty-policy"}, new_plan)
            content = {k: data[k] for k in fields}
            data["host_observations"] = [{"observer": "coordinator", "kind": "pr-state", "source": "synthetic",
                                          "content": content, "sha256": digest(canonical(content)),
                                          "allow_empty_required_contexts": True}]
            input_path.write_text(json.dumps(data))
            ref = publish_observation(store, caller, "s0", str(input_path))
            stage = store.load()["stages"][0]
            argv = [str(validator), "--input", ref["path"]]
            self.assertEqual(os.path.realpath(_adapter(store.load(), stage, argv, ref["path"])[0]), os.path.realpath(validator))
            proc = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_r2_07_imps_final_gate_must_cover_the_owned_stage_identity(self):
        """Use a valid published descriptor before changing final gate coverage."""
        from shared.job_coordinator import create_pinned_job, pinned_store, publish_observation
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state = self.fx.install(root, 'imps')
            row = {'id':'owned', 'state_subdir':'owned', 'run_id':'r1', 'stage_sha256':digest((version/'scripts/validate_stage.py').read_bytes())}
            declared = {'required_stages':['owned'], 'stages':[row]}
            data = {'state_root':str(root/'gates'), 'package_root':str(version), **declared}
            plan = root/'final-plan.json'; plan.write_text(json.dumps(data))
            descriptor = root/'descriptor.json'; descriptor.write_text(json.dumps({'state_root':data['state_root'],'final_plan':str(plan)}))
            job = self.fx.base_job('imps-coverage-r2'); job.update(installation_id=manifest['installation_id'],pins={},tasks=[],dependencies=[{'key':'imps','plugin':'imps'}])
            job['stages'][0].update(execution_mode='direct',validator_dependency='imps',validator_contract={'final_plan':declared})
            create_pinned_job(job,state,prefix,agents,root/'config/workers.json'); store=pinned_store(state,job['job_id'])
            caller={'installation_id':manifest['installation_id'],'workflow':job['workflow'],'package_digest':manifest['package_digest'],'actor':'coordinator'}
            ref=publish_observation(store,caller,'s0',str(descriptor)); argv=[str(version/'scripts/validate_stage.py'),'--state-root',data['state_root'],'--final-plan',str(plan)]
            self.assertEqual(os.path.realpath(_adapter(store.load(),store.load()['stages'][0],argv,ref['path'])[0]), os.path.realpath(Path(argv[0])))
            data.update(required_stages=['other'],stages=[{**row,'id':'other'}]); plan.write_text(json.dumps(data))
            with self.assertRaisesRegex(AcceptanceError,'gate identities/coverage'):
                _adapter(store.load(),store.load()['stages'][0],argv,ref['path'])

    def test_r2_08_replacing_logical_slot_preserves_spent_attempt_budget(self):
        """R2-08: task ID replacement cannot reset stage/logical-slot counters.

        R20-stage3-shard-4-02: a replacement that copies cycle 3 is refused by the separate
        new-slot runtime guard, so the budget is checked with a declarative replacement that
        supplies only default runtime fields.
        """
        def replaced(td, attempt, cycle, copied=False):
            store = self._preparable_store(Path(td))
            caller = self.fx.caller()
            state = store.load()
            state["tasks"][0].update(status="failed", attempt=attempt, cycle=cycle)
            _atomic(store.file, canonical(state))  # synthetic persisted history state
            revised = store.load()
            declared = {"task_id": "replacement", "stage_id": "s0", "logical_slot_id": "primary",
                        "request_id": "replacement-request", "worker_id": "ape/source-researcher",
                        "dependency_key": "ape", "status": "pending",
                        "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/replacement"}}
            if copied:
                declared = {**revised["tasks"][0], **declared, "attempt": 0, "execution_history": [], "handles": [], "followups": []}
            revised["tasks"] = [declared]
            source = Path(td) / "owner.txt"
            source.write_bytes(b"Owner approves a reviewed replacement slot for this synthetic regression.\n")
            decision(store, caller, {"id": "slot-revision", "quote": "Owner approves a reviewed replacement slot",
                                     "source": str(source), "source_sha256": digest(source.read_bytes()),
                                     "scope": "plan:replace-slot"})
            revise_plan(store, caller, {"id": "replace-slot", "owner_decision_id": "slot-revision"}, revised)
            return store, caller, next(t for t in store.load()["tasks"] if t["task_id"] == "replacement")

        prepare_fresh = lambda store, caller: prepare(store, caller, "replacement", lambda *_: True, lambda *_: True)
        with tempfile.TemporaryDirectory() as td:
            # The copied runtime cycle is refused by the new-slot guard, before any budget check.
            with self.assertRaisesRegex(JobError, "new slots cannot supply performed runtime state"):
                replaced(td, 4, 3, copied=True)
        with tempfile.TemporaryDirectory() as td:
            store, caller, task = replaced(td, 4, 3)
            self.assertEqual((task.get("attempt"), task.get("cycle")), (4, 3))
            with self.assertRaisesRegex(JobError, "requires a charged repair pass"):
                prepare_fresh(store, caller)
            with self.assertRaisesRegex(JobError, "task execution budget exhausted"):
                retry_task(store, caller, "replacement", "replacement at the spent limit")
            with self.assertRaisesRegex(JobError, "requires a charged repair pass"):
                prepare_fresh(store, caller)
        with tempfile.TemporaryDirectory() as td:
            # Positive control: the same replacement of a slot with budget left inherits it and can run.
            store, caller, task = replaced(td, 1, 0)
            self.assertEqual((task.get("attempt"), task.get("cycle")), (1, 0))
            with self.assertRaisesRegex(JobError, "requires a charged repair pass"):
                prepare_fresh(store, caller)
            retry_task(store, caller, "replacement", "charged replacement repair")
            self.assertTrue(Path(prepare_fresh(store, caller)["path"]).is_file())
            task = next(t for t in store.load()["tasks"] if t["task_id"] == "replacement")
            self.assertEqual((task.get("attempt"), task.get("cycle")), (1, 1))

    def test_r2_09_overview_renders_real_handles_and_followups(self):
        """R2-09: operators can reconcile every actual host identity and child state."""
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.make_store(td)
            state = store.load()
            state["tasks"][0]["status"] = "running"
            state["tasks"][0]["handles"] = [{"task_id": "host-7", "request_id": "req0", "child_thread_id": "thread-8",
                                               "status": "running", "work_state": "waiting_for_children", "has_pending_child_runs": True}]
            state["tasks"][0]["followups"] = [{"task_id": "host-9", "request_id": "req-followup", "child_thread_id": "thread-10",
                                                 "status": "completed", "work_state": "result_available", "has_pending_child_runs": False}]
            _atomic(store.file, canonical(state))
            overview = Store(td, "review-job").overview()
            slot = overview["handles"][0]
            self.assertEqual(slot["task_id"], "t0")
            for name in ("handles", "followups"):
                self.assertEqual(len(slot[name]), len(state["tasks"][0][name]))
                for actual, rendered in zip(state["tasks"][0][name], slot[name]):
                    for key in ("task_id", "request_id", "child_thread_id", "status", "work_state", "has_pending_child_runs"):
                        self.assertEqual(rendered[key], actual[key])

    def test_r2_10_new_plan_tasks_cannot_supply_runtime_fields(self):
        """R2-10: runtime-field rejection applies to added task IDs too."""
        with tempfile.TemporaryDirectory() as td:
            store = self.fx.make_store(td)
            plan = store.load()
            new_task = {**plan["tasks"][0], "task_id": "new-task", "request_id": "new-request",
                        "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/new-task"},
                        "attempt": 99, "status": "awaiting-acceptance", "execution_history": [{"forged": True}]}
            plan["tasks"].append(new_task)
            source = Path(td) / "owner.txt"
            source.write_bytes(b"Owner approves adding the new task slot for this synthetic regression.\n")
            decision(store, self.fx.caller(), {"id": "new-task-revision", "quote": "Owner approves adding the new task slot",
                                               "source": str(source), "source_sha256": digest(source.read_bytes()),
                                               "scope": "plan:new-task-runtime"})
            with self.assertRaises(JobError):
                revise_plan(store, self.fx.caller(), {"id": "new-task-runtime", "owner_decision_id": "new-task-revision"}, plan)

    def test_r2_11_relative_validator_paths_rejected_before_execution(self):
        """A valid observation reaches the path check before rejecting a relative root."""
        from shared.job_coordinator import create_pinned_job, pinned_store, publish_observation
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); version,manifest,prefix,agents,state=self.fx.install(root,'elephant-goldfish')
            contract={'root':str(root/'thinking'),'slug':'fixture','mode':'handoff'}
            job=self.fx.base_job('absolute-root-r2');job.update(installation_id=manifest['installation_id'],pins={},tasks=[],dependencies=[{'key':'eg','plugin':'elephant-goldfish'}])
            job['stages'][0].update(execution_mode='direct',validator_dependency='eg',validator_contract=contract)
            create_pinned_job(job,state,prefix,agents,root/'config/workers.json');store=pinned_store(state,job['job_id'])
            caller={'installation_id':manifest['installation_id'],'workflow':job['workflow'],'package_digest':manifest['package_digest'],'actor':'coordinator'}
            inp=root/'descriptor.json';inp.write_text(json.dumps(contract));ref=publish_observation(store,caller,'s0',str(inp))
            argv=[str(version/'scripts/validate_document.py'),'--root',contract['root'],'--slug','fixture','--mode','handoff']
            self.assertEqual(os.path.realpath(_adapter(store.load(),store.load()['stages'][0],argv,ref['path'])[0]), os.path.realpath(Path(argv[0])))
            argv[2]='thinking'
            with self.assertRaisesRegex(AcceptanceError,'root must be absolute'):
                _adapter(store.load(),store.load()['stages'][0],argv,ref['path'])

    def test_r2_12_document_contract_requires_absolute_path_slug_and_hash(self):
        """R2-12: factual/cold-read contracts bind the exact document identity."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state_root = self.fx.install(root, "elephant-goldfish")
            document_root = root / "docs"
            document_root.mkdir()
            document = document_root / "doc.md"
            document.write_text("synthetic document\n")
            doc_sha = digest(document.read_bytes())
            content = {"document_sha256": doc_sha, "verdict": "ready"}
            evidence = {"observer": "coordinator", "kind": "cold-read", "source": "synthetic cold-read receipt",
                        "content": content, "sha256": digest(canonical(content))}
            data = {"kind": "cold-read-observation", "mode": "cold-read", "root": str(root), "slug": "docs",
                    "document_path": str(document), "document_sha256": doc_sha, "verdict": "ready", "evidence": [evidence]}
            inp = root / "observation.json"
            inp.write_text(json.dumps(data))
            job = self.fx.base_job("document-contract-r2")
            job["installation_id"] = manifest["installation_id"]
            job["dependencies"] = [{"key": "eg", "plugin": "elephant-goldfish"}]
            job["pins"] = {}
            job["tasks"][0]["dependency_key"] = "eg"
            contract = {k: data[k] for k in ("mode", "root", "slug", "document_path", "document_sha256")}
            job["stages"][0]["validator_dependency"] = "eg"
            job["stages"][0]["validator_contract"] = contract
            from shared.job_coordinator import create_pinned_job, pinned_store, publish_observation
            create_pinned_job(job, state_root, prefix, agents, root / "config" / "workers.json")
            store = pinned_store(state_root, job["job_id"])
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"],
                      "package_digest": manifest["package_digest"], "actor": "coordinator"}
            ref = publish_observation(store, caller, "s0", str(inp))
            stage = store.load()["stages"][0]
            argv = [str(version / "scripts" / "validate_document.py"), "--root", str(root), "--slug", "docs",
                    "--mode", "cold-read", "--input", ref["path"]]
            self.assertEqual(os.path.realpath(_adapter(store.load(), stage, argv, ref["path"])[0]), os.path.realpath(version / "scripts" / "validate_document.py"))
            del stage["validator_contract"]["slug"]
            with self.assertRaises(AcceptanceError):
                _adapter(store.load(), stage, argv, ref["path"])

    def test_r2_13_acceptance_cli_invalid_input_returns_two_without_traceback(self):
        """R2-13: malformed descriptors are invocation errors, not uncaught traces."""
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "bad.json"
            inp.write_text("{")
            proc = subprocess.run([sys.executable, str(ROOT / "shared" / "job_acceptance_cli.py"), "validate",
                                   "--state-root", td, "--job", "bad id", "--input", str(inp)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_r2_14_status_is_read_only_and_does_not_execute_validators(self):
        """R2-14: status derives receipt state without launching adapter processes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job = self.fx.base_job("status-read-r2")
            job["pins"]["ape"]["package_dir"] = str(ROOT)
            job["stages"][0]["status"] = "accepted-at-snapshot"
            job["stages"][0]["acceptance"] = {"path": str(root / "missing-receipt.json"), "sha256": "0" * 64}
            store = self.fx.make_store(root, job)
            before = store.file.read_bytes()
            import contextlib
            import io
            import shared.job_cli as cli
            out = io.StringIO()
            from unittest import mock
            with contextlib.redirect_stdout(out), mock.patch.object(cli, "pinned_store", return_value=store), \
                    mock.patch.object(cli, "verify_all_pins", return_value=job), \
                    mock.patch("shared.job_acceptance._invoke", side_effect=AssertionError("status executed validator")):
                self.assertEqual(cli.main(["status", "--state-root", td, "--job", job["job_id"]]), 0)
            self.assertTrue(json.loads(out.getvalue())["stages"])
            self.assertEqual(store.file.read_bytes(), before)

    def test_r2_15_descriptor_size_is_checked_before_unbounded_read(self):
        """R2-15: hostile descriptor size is rejected by a bounded regular-file read."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            version, manifest, prefix, agents, state_root = self.fx.install(root, "ape")
            job = self.fx.base_job("descriptor-size-r2")
            job["installation_id"] = manifest["installation_id"]
            job["pins"] = {}
            from shared.job_coordinator import create_pinned_job
            create_pinned_job(job, state_root, prefix, agents, root / "config" / "workers.json")
            descriptor = root / "oversized.json"
            descriptor.write_bytes(b" " * (1024 * 1024 + 1))
            proc = subprocess.run([sys.executable, str(version / "shared" / "job_cli.py"), "overview",
                                   "--state-root", str(state_root), "--job", job["job_id"], "--input", str(descriptor)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertNotIn("Traceback", proc.stderr)

    def test_r2_16_conflicting_pin_limit_values_are_not_silently_first_wins(self):
        """R2-16: job defaults cannot depend on dependency insertion order."""
        job = self.fx.base_job()
        job["dependencies"].append({"key": "second", "plugin": "ape"})
        job["policy"].pop("max_live_workers", None)
        job["pins"]["second"] = {"package_digest": "b" * 64, "limits": {"max_live_workers": 3}}
        job["pins"]["ape"] = {"package_digest": "a" * 64, "limits": {"max_live_workers": 2}}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(JobError):
                create_job(job, td, job["pins"])

    def test_r2_17_brief_exposes_exact_known_waiver_decision_reference(self):
        """R2-17: a worker can cite a specific owner decision delivered by prepare."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._preparable_store(root)
            caller = self.fx.caller()
            source = root / "waiver-source.txt"
            source.write_bytes(b"Owner permits waiver for requirement R1 in this fixture.\n")
            decision(store, caller, {"id": "waiver-1", "quote": "Owner permits waiver for requirement R1",
                                     "source": str(source), "source_sha256": digest(source.read_bytes()),
                                     "scope": "waiver:t0", "requirement_ids": ["R1"]})
            prepared = prepare(store, caller, "t0", lambda *_: True, lambda *_: True)
            brief = json.loads(Path(prepared["path"]).read_text())
            refs = brief.get("owner_waivers", brief.get("owner_decisions", brief.get("decisions", [])))
            self.assertTrue(any(row.get("id") == "waiver-1" for row in refs))

    def test_stage_criterion_weakening_requires_source_bound_owner_decision(self):
        with tempfile.TemporaryDirectory() as td:
            store=self._preparable_store(td);caller=self.fx.caller()
            plan=store.load();plan['stages'][0]['criteria']=[]
            with self.assertRaisesRegex(JobError,'owner decision'):
                revise_plan(store,caller,{'id':'weaker-criteria'},plan)
            source=store.root/'approval.txt';source.write_text('approve this weaker criterion coverage\n')
            decision(store,caller,{'id':'criterion-owner','quote':'approve this weaker criterion coverage','source':str(source),'source_sha256':digest(source.read_bytes()),'scope':'plan:weaker-criteria'})
            revise_plan(store,caller,{'id':'weaker-criteria','owner_decision_id':'criterion-owner'},plan)
            self.assertEqual(store.load()['stages'][0]['criteria'],[])
            self.assertEqual(store.load()['stages'][0]['status'],'stale')

    def test_existing_validator_output_ceiling_remains_enforced(self):
        """Keep the prior finite-output guard while extending acceptance coverage."""
        with self.assertRaisesRegex(AcceptanceError, "output limit"):
            _bounded_run([sys.executable, "-c", "print('x' * 4096)"], ROOT,
                         {"timeout_seconds": 5, "max_output_bytes": 128})


if __name__ == "__main__":
    unittest.main()
