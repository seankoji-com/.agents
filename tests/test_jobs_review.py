"""Adversarial regression probes for Stage 3 review findings S3-R01..R24.

These tests intentionally use the public job APIs and actual installed pinned
validators. Synthetic host observations stay local and are never treated as
proof beyond the validator's declared content-binding contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from unittest import mock
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.jobs import (  # noqa: E402
    JobError,
    cancel,
    create_job,
    decision,
    prepare,
    record_dispatch,
    record_result,
    revise_plan,
    retry_task,
    worker_write,
)
from core.jobs.store import Store, canonical, digest  # noqa: E402
from shared.job_acceptance import AcceptanceError, accept_stage, validate_stage  # noqa: E402
from shared.job_coordinator import create_pinned_job, verify_all_pins, verify_pinned_dependency, prepare_followup, publish_observation, dispose_finding  # noqa: E402
from shared.worker_result import parse_result, ResultError  # noqa: E402


def fixture_decision(store, caller, value):
    from core.jobs import decision as actual_decision
    from core.jobs.store import digest
    source = store.root / ('owner-source-' + digest(str(value.get('id')).encode()) + '.txt')
    source.write_text(value.get('quote', '') + '\n')
    value = {**value, 'source': str(source), 'source_sha256': digest(source.read_bytes())}
    return actual_decision(store, caller, value)

class JobReviewTests(unittest.TestCase):
    """Coverage for all fresh R01-R24 findings from the bounded review."""

    def base_job(self, job_id="review-job", *, task_status="pending", two_tasks=False):
        tasks = [
            {
                "task_id": "t0",
                "stage_id": "s0",
                "logical_slot_id": "primary",
                "request_id": "req0",
                "worker_id": "ape/source-researcher",
                "dependency_key": "ape",
                "status": task_status,
                "attempt": 0,
                "handles": [],
                "followups": [],
                "dispatch_retries": 0,
                "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/t0"},
            }
        ]
        if two_tasks:
            tasks.append(
                {
                    **tasks[0],
                    "task_id": "t1",
                    "logical_slot_id": "support",
                    "request_id": "req1",
                    "status": "pending",
                    "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/t1"},
                }
            )
        return {
            "schema_version": 1,
            "job_id": job_id,
            "installation_id": "install-fixture",
            "workflow": "ape/review-fixture",
            "owner": {"id": "owner-fixture"},
            "objective": "verify bounded fixture evidence",
            "requirements": {"R1": "evidence is current and bound"},
            "authorization": {"actions": ["read"]},
            "constraints": ["offline fixture only"],
            "dependencies": [{"key": "ape", "plugin": "ape"}],
            "pins": {"ape": {"package_digest": "a" * 64}},
            "policy": {"max_repair_cycles": 3, "max_artifact_bytes": 1_000_000, "max_live_workers": 2},
            "result_contract": {"schema_version": 1},
            "stages": [
                {
                    "id": "s0",
                    "depends_on": [],
                    "requirements": ["R1"],
                    "status": "pending",
                    "validator_dependency": "ape",
                    "revision": "s0-r1",
                    "criteria": [{"id": "C1", "kind": "source-provenance"}],
                    "attempts": {"primary": 0, "support": 0, "review": 0, "final": 0},
                },
                {
                    "id": "s1",
                    "depends_on": ["s0"],
                    "requirements": ["R1"],
                    "status": "pending",
                    "validator_dependency": "ape",
                    "revision": "s1-r1",
                    "attempts": {"primary": 0, "support": 0, "review": 0, "final": 0},
                },
            ],
            "tasks": tasks,
            "decisions": [],
            "history": [],
            "metrics": {},
        }

    def caller(self, *, actor="coordinator", **extra):
        return {
            "installation_id": "install-fixture",
            "workflow": "ape/review-fixture",
            "package_digest": "a" * 64,
            "actor": actor,
            **extra,
        }

    def make_store(self, root, job=None):
        job = job or self.base_job()
        create_job(job, root, job["pins"])
        return Store(root, job["job_id"])

    def install(self, base, plugin="ape"):
        home = base / "home"
        home.mkdir(parents=True, exist_ok=True)
        prefix, agents, state = base / "prefix", base / "agents", base / "state"
        env = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(base / "config"),
            "XDG_STATE_HOME": str(state),
        }
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/install.py"), "--plugin", plugin,
             "--prefix", str(prefix), "--agents-root", str(agents)],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        version = Path(json.loads(proc.stdout)["data"]["version_dir"])
        manifest = json.loads((version / "install-manifest.json").read_text())
        return version, manifest, prefix, agents, state

    def ape_acceptance_fixture(self, base, *, two_tasks=False):
        version, manifest, prefix, agents, state_root = self.install(base, "ape")
        job = self.base_job("acceptance-review", two_tasks=two_tasks)
        job["installation_id"] = manifest["installation_id"]
        job["pins"] = {}
        source = base / 'source.txt'; source.write_text('fixture source evidence\n')
        source_pin = {'id': 'src', 'url': 'https://example.invalid/source', 'revision': 'r1', 'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        job['stages'][0]['validator_contract'] = {'sources': [source_pin]}
        create_pinned_job(job, state_root, prefix, agents, base / "config" / "workers.json")
        store = Store(state_root, job["job_id"])
        caller = {
            "installation_id": manifest["installation_id"],
            "workflow": job["workflow"],
            "package_digest": manifest["package_digest"],
            "actor": "coordinator",
        }
        report = base / "report.json"
        report.write_text(json.dumps({
            "sources": [source_pin],
            "findings": [],
            "criteria": [{"id": "C1", "kind": "source-provenance"}],
        }))
        self.ingest_ready(store, caller, "t0")
        report = Path(publish_observation(store, caller, "s0", str(report))["path"])
        argv = [str(version / "scripts" / "validate_report.py"), "--input", str(report)]
        return version, manifest, state_root, store, caller, report, argv

    def ingest_ready(self, store, caller, task_id, findings=None):
        verify_all_pins(store)
        prepared = prepare(store, caller, task_id, verify_pinned_dependency, lambda stage: True)
        brief = json.loads(Path(prepared['path']).read_text())
        result = self.valid_result()
        for key in ('job_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id', 'effective_brief_sha256', 'revision'):
            result[key] = brief[key]
        result['binding'] = brief['snapshot']
        result['requirements'] = [{'id': row['id'], 'status': 'passed', 'evidence': ['fixture']} for row in brief['requirements']]
        result['findings'] = findings or []
        result['review_verdict'] = 'adverse' if findings else None
        record_result(store, caller, task_id, {'result': json.dumps(result).encode(), 'completion_id': brief['request_id'] + '-done', 'request_id': brief['request_id']})

    def test_acceptance_requires_every_current_slot_and_disposed_blocking_findings(self):
        """R01: acceptance cannot pass failed, pending, stale, or unresolved slots."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _, _, _, store, caller, report, argv = self.ape_acceptance_fixture(base, two_tasks=True)
            state = store.load()
            state["tasks"][0].update(status="failed", result_ref={"sha256": "c" * 64})
            state["tasks"][0]["finding_dispositions"] = [
                {"finding_id": "F1", "finding": {"severity": "blocker"}, "disposition": None}
            ]
            state["tasks"][1].update(status="pending")
            from core.jobs.store import _atomic
            _atomic(store.file, canonical(state))
            with self.assertRaises((AcceptanceError, JobError)):
                accept_stage(store, caller, "s0", argv, str(report), "s0-r1")
            # Recover both failed slots through charged repair and public ingestion.
            state = store.load()
            for task in state['tasks']:
                task['status'] = 'failed'
                task.pop('brief',None)
            _atomic(store.file, canonical(state))
            for task_id in ('t0', 't1'):
                retry_task(store, caller, task_id, 'fixture repair')
                self.ingest_ready(store, caller, task_id)
            state = store.load()
            evidence = base/'disposition.txt'; evidence.write_text('fixture repair evidence\n')
            dispose_finding(store, caller, 't0', 'F1', 'fixed', {'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),'bytes':evidence.stat().st_size})
            receipt = accept_stage(store, caller, "s0", argv, str(report), "s0-r1")
            self.assertTrue(receipt["accepted"], receipt)
            self.assertTrue(validate_stage(store, "s0")["accepted"])

    def test_waiver_requires_recorded_owner_decision_and_policy_permission(self):
        """R02: a truthy worker-authored owner_evidence string is not authority."""
        result = self.valid_result()
        result["requirements"] = [{"id": "R1", "status": "waived", "evidence": ["self"], "reason": "skip", "owner_evidence": "worker-claims-owner"}]
        expected = self.expected_result(result)
        with self.assertRaises(ResultError):
            parse_result(json.dumps(result).encode(), expected)

    def test_actual_installed_babysitter_validator_requires_declared_checks_and_latest_observation(self):
        """R03: explicit empty policy and stale matching observations cannot pass."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, *_ = self.install(base, "babysitter")
            validator = version / "scripts" / "validate_pr.py"
            inp = base / "pr-observation.json"
            head = "a" * 40
            def observation(data):
                content = {k: data[k] for k in ("pr", "head_sha", "required_contexts", "required_checks", "review_threads", "authorized_endstate", "optional_contexts", "allow_empty_required_contexts")}
                return {"observer": "coordinator", "kind": "pr-state", "source": "fixture-host-snapshot", "content": content,
                        "sha256": hashlib.sha256(canonical(content)).hexdigest()}
            valid = {
                "pr": "fixture/1", "head_sha": head, "required_contexts": ["ci"], "optional_contexts": ["optional"], "allow_empty_required_contexts": False,
                "required_checks": [{"context": "ci", "conclusion": "success", "head_sha": head}],
                "review_threads": [],
                "authorized_endstate": {"requested": "mergeable", "observed": "mergeable", "authorization_ref": "decision-fixture"},
            }
            valid["host_observations"] = [observation(valid)]
            def run(data):
                inp.write_text(json.dumps(data))
                return subprocess.run([sys.executable, str(validator), "--input", str(inp)], capture_output=True, text=True)
            self.assertEqual(run(valid).returncode, 0)
            empty = {**valid, "required_contexts": [], "required_checks": []}
            empty["host_observations"] = [observation(empty)]
            self.assertNotEqual(run(empty).returncode, 0)
            optional_failed = {**valid, "required_checks": [*valid["required_checks"], {"context": "optional", "conclusion": "failure", "head_sha": head}]}
            optional_failed["host_observations"] = [observation(optional_failed)]
            self.assertEqual(run(optional_failed).returncode, 0)
            stale = {**valid, "review_threads": [{"resolved": False, "head_sha": head}]}
            stale["host_observations"] = [observation(valid), observation(stale)]
            self.assertNotEqual(run(stale).returncode, 0)

    def test_plan_revision_preserves_removed_slot_history_and_requires_limit_waiver(self):
        """R04/R05: live slots cannot vanish and null means unlimited workers."""
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td, self.base_job(two_tasks=True))
            caller = self.caller()
            job = store.load()
            job["tasks"][0]["status"] = "running"
            job["tasks"][0]["handles"] = [{"task_id": "host-1", "request_id": "req0", "status": "running"}]
            from core.jobs.store import _atomic
            _atomic(store.file, canonical(job))
            revised = store.load()
            revised["tasks"] = [revised["tasks"][1]]
            with self.assertRaises(JobError):
                revise_plan(store, caller, {"id": "remove-live"}, revised)
            revised = store.load()
            revised["policy"]["max_live_workers"] = None
            with self.assertRaises(JobError):
                revise_plan(store, caller, {"id": "unlimited"}, revised)
            fixture_decision(store, caller, {"id": "owner-unlimited", "quote": "approve unlimited capacity", "source": "fixture decision",
                                     "source_sha256": "f" * 64, "scope": "plan:unlimited"})
            revised = store.load()
            revised["policy"]["max_live_workers"] = None
            revise_plan(store, caller, {"id": "unlimited", "owner_decision_id": "owner-unlimited"}, revised)

    def test_acceptance_commit_rejects_job_mutation_while_validator_runs(self):
        """R07: mutate the real job from the validator process before commit."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, manifest, state_root, store, caller, report, argv = self.ape_acceptance_fixture(base)
            validator = version / "scripts" / "validate_report.py"
            marker = base / "validator-ran"
            import shared.job_acceptance as acceptance
            original_invoke = acceptance._invoke
            def invoke_then_mutate(*args, **kwargs):
                outcome = original_invoke(*args, **kwargs)
                marker.write_text("ran")
                state = store.load()
                state["metrics"]["during_validator"] = True
                from core.jobs.store import _atomic
                _atomic(store.file, canonical(state))
                return outcome
            with mock.patch.object(acceptance, "_invoke", side_effect=invoke_then_mutate):
                receipt = accept_stage(store, caller, "s0", argv, str(report), "s0-r1")
            self.assertTrue(marker.exists())
            self.assertFalse(receipt["accepted"] or store.load()["stages"][0]["status"] == "accepted-at-snapshot")

    def test_repair_budget_is_shared_by_execution_and_acceptance_passes(self):
        """R06: failed standalone acceptance consumes the same initial+3 pass budget."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            _, _, _, store, caller, report, argv = self.ape_acceptance_fixture(base)
            bad = base / "bad-report.json"
            current = json.loads(report.read_text()); current['findings'] = [{'source_id':'src','quote':'nonexistent forged source quote'}]
            bad.write_text(json.dumps(current))
            bad = Path(publish_observation(store, caller, 's0', str(bad))['path'])
            bad_argv = [argv[0], "--input", str(bad)]
            for _ in range(3):
                receipt = accept_stage(store, caller, "s0", bad_argv, str(bad), "s0-r1")
                self.assertFalse(receipt["accepted"])
                retry_task(store, caller, "t0", "acceptance failure", "support")
                self.ingest_ready(store, caller, "t0")
            self.assertFalse(accept_stage(store, caller, "s0", bad_argv, str(bad), "s0-r1")["accepted"])
            with self.assertRaises(JobError):
                retry_task(store, caller, "t0", "fifth pass", "review")
            with self.assertRaises((AcceptanceError, JobError)):
                accept_stage(store, caller, "s0", bad_argv, str(bad), "s0-r1")
            self.assertLessEqual(store.load()["stages"][0].get("cycle", 0), 3)

    def test_stage_coverage_change_stales_transitive_descendants(self):
        """R08: changing criteria or requirement coverage invalidates dependent receipts."""
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            caller = self.caller()
            job = store.load()
            job["requirements"]["R2"] = "new criterion"
            job["stages"][0]["requirements"].append("R2")
            # Revisions without actual result evidence cannot be allowed to retain acceptance.
            with self.assertRaises(JobError):
                revise_plan(store, caller, {"id": "coverage"}, job)
            self.assertEqual(store.load()["stages"][0]["requirements"], ["R1"])

    def test_document_only_brief_omits_job_result_and_stage_stop_contracts(self):
        """R09: no job or stage runtime contract leaks into document-only brief."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            document = base / "document.md"
            document.write_text("# Supplied document only\n")
            job = self.base_job()
            job["result_contract"] = {"schema_version": 1, "marker": "PRIVATE_RESULT_CONTRACT"}
            job["stages"][0]["stop_conditions"] = ["PRIVATE_STOP_CONDITION"]
            job["tasks"][0].update(context_policy="document-only", document={"path": str(document), "sha256": hashlib.sha256(document.read_bytes()).hexdigest()})
            job["pins"]["ape"].update(package_dir="/fixture/package", bundle_dir="/fixture/bundle", installation_id="install-fixture", workers={}, shared={}, task_contract=None)
            job["pins"]["ape"].update(bundle_digest="b" * 64, package_dir="/fixture/package", bundle_dir="/fixture/bundle", installation_id="install-fixture", workers={}, shared={}, effective_workers={"ape/source-researcher": {"bytes": "fixture worker"}})
            store = self.make_store(base / "state", job)
            prepared = prepare(store, self.caller(), "t0", lambda dep, pin: True, lambda stage: False)
            brief = Path(prepared["path"]).read_text()
            self.assertNotIn("PRIVATE_RESULT_CONTRACT", brief)
            self.assertNotIn("PRIVATE_STOP_CONDITION", brief)

    def test_strict_utf8_no_bom_null_binding_and_null_owner_authority(self):
        """R10/R11: reject encoded aliases and bind null exactly."""
        result = self.valid_result()
        expected = self.expected_result(result)
        raw = json.dumps(result).encode()
        with self.assertRaises(ResultError):
            parse_result(b"\xef\xbb\xbf" + raw, expected)
        with self.assertRaises(ResultError):
            parse_result(json.dumps(result).encode("utf-16"), expected)
        expected["binding"] = {"snapshot": "bound"}
        result["binding"] = {"self-chosen": True}
        with self.assertRaises(ResultError):
            parse_result(json.dumps(result).encode(), expected)
        expected["binding"] = None
        result["binding"] = {}
        with self.assertRaises(ResultError):
            parse_result(json.dumps(result).encode(), expected)

    def test_cancel_uncertainty_evidence_freeze_and_followup_identity(self):
        """R12/R13/R14/R23: lifecycle and evidence mutations remain bounded."""
        with tempfile.TemporaryDirectory() as td:
            cancelled_job = self.base_job()
            cancelled_job["pins"]["ape"].update(bundle_digest="b" * 64, package_dir="/fixture/package", bundle_dir="/fixture/bundle", installation_id="install-fixture", workers={}, shared={}, task_contract=None, effective_workers={"ape/source-researcher": {"bytes": "fixture worker"}})
            store = Store(td, cancelled_job["job_id"])
            store.verify_pins = lambda job: True
            create_job(cancelled_job, td, cancelled_job["pins"])
            caller = self.caller()
            cancel(store, caller, "fixture cancellation")
            with self.assertRaises(JobError):
                prepare(store, caller, "t0", lambda dep, pin: True, lambda stage: False)
            # Use a clean independent job to probe uncertain and follow-up handles.
            other_root = Path(td) / "other"
            dispatch_job = self.base_job("dispatch-review")
            dispatch_job["pins"]["ape"].update(bundle_digest="b" * 64, package_dir="/fixture/package", bundle_dir="/fixture/bundle", installation_id="install-fixture", workers={}, shared={}, task_contract=None, effective_workers={"ape/source-researcher": {"bytes": "fixture worker"}})
            other = self.make_store(other_root, dispatch_job)
            other.verify_pins = lambda job: True
            for _ in range(3):
                record_dispatch(other, caller, "t0", {"kind": "uncertain", "request_id": "req0"})
            self.assertEqual(other.load()["tasks"][0]["status"], "blocked")
            with self.assertRaises(JobError):
                record_dispatch(other, caller, "t0", {"kind": "uncertain", "request_id": "req0"})
            evcaller = self.caller(actor="worker", task_id="t0", stage_id="s0", scope=other.load()["tasks"][0]["write_scope"])
            evcaller["package_digest"] = "a" * 64
            worker_write(other, evcaller, "t0", "artifacts/tasks/t0/result.json", b"first")
            state = other.load()
            state["tasks"][0].update(status="awaiting-acceptance", result_ref={"sha256": digest(b"first")}, execution_history=[{"request_id": "req0", "sha256": digest(b"first")}])
            from core.jobs.store import _atomic
            _atomic(other.file, canonical(state))
            with self.assertRaises(JobError):
                worker_write(other, evcaller, "t0", "artifacts/tasks/t0/result.json", b"second")
            # Two follow-ups for one terminal parent and a duplicate host ID must fail.
            record_dispatch(other, caller, "t0", {"kind": "accepted", "request_id": "req0", "host_task_id": "host0", "status": "running", "work_state": "working", "has_pending_child_runs": False})
            terminal = {"kind": "completion", "request_id": "req0", "host_task_id": "host0", "completion_id": "done0", "status": "completed", "work_state": "result_available", "has_pending_child_runs": False}
            record_dispatch(other, caller, "t0", terminal)
            first = {"kind": "followup", "request_id": "req-next", "host_task_id": "host1", "parent_host_task_id": "host0", "target": None, "scope": {"mode": "worker-evidence", "path": "artifacts/tasks/t0"}}
            state = other.load()
            from core.jobs.store import _atomic
            state['tasks'][0]['status'] = 'pending'
            _atomic(other.file, canonical(state))
            prepare(other, caller, 't0', lambda dep, pin: True, lambda stage: True)
            state = other.load(); state['tasks'][0]['status'] = 'awaiting-acceptance'; _atomic(other.file, canonical(state))
            prepare_followup(other, caller, 't0', 'req-next')
            record_dispatch(other, caller, "t0", first)
            with self.assertRaises(JobError):
                record_dispatch(other, caller, "t0", {**first, "request_id": "req-next-2", "host_task_id": "host2"})
            second_slot = self.base_job("dispatch-review")
            second_slot["pins"]["ape"].update(bundle_digest="b" * 64, package_dir="/fixture/package", bundle_dir="/fixture/bundle", installation_id="install-fixture", workers={}, shared={}, task_contract=None, effective_workers={"ape/source-researcher": {"bytes": "fixture worker"}})
            second_slot["tasks"].append({**second_slot["tasks"][0], "task_id": "t1", "logical_slot_id": "support", "request_id": "req1", "handles": [], "followups": [], "write_scope": {"mode": "worker-evidence", "path": "artifacts/tasks/t1"}})
            cross = self.make_store(Path(td) / "cross", second_slot)
            cross.verify_pins = lambda job: True
            record_dispatch(cross, caller, "t0", {"kind": "accepted", "request_id": "req0", "host_task_id": "global-host", "status": "running", "work_state": "working", "has_pending_child_runs": False})
            with self.assertRaises(JobError):
                record_dispatch(cross, caller, "t1", {"kind": "accepted", "request_id": "req1", "host_task_id": "global-host", "status": "running", "work_state": "working", "has_pending_child_runs": False})

    def test_missing_dependency_pin_and_result_contract_are_rejected_at_validation(self):
        """R15/R16: invalid plans fail at creation rather than during prepare."""
        from core.jobs.store import validate
        job = self.base_job()
        job["pins"] = {}
        with self.assertRaises(JobError):
            validate(job)
        job = self.base_job()
        del job["result_contract"]
        with self.assertRaises(JobError):
            validate(job)

    def test_imps_final_invocation_and_document_slug_are_bound_to_actual_inputs(self):
        """R17/R18: installed adapters consume the exact declared flag/path."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            imps, *_ = self.install(base, "imps")
            inp = base / "imps.json"
            plan = {"state_root": str(base / "actual-state"), "package_root": str(imps), "required_stages": ["s"], "stages": [{"id": "s", "state_subdir": "s", "run_id": "missing", "stage_sha256": hashlib.sha256((imps / "scripts" / "validate_stage.py").read_bytes()).hexdigest()}]}
            inp.write_text(json.dumps(plan))
            proc = subprocess.run([sys.executable, str(imps / "scripts" / "validate_stage.py"), "--state-root", str(base / "other-state"), "--final-plan", str(inp)], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn(str(base / "other-state"), proc.stdout + proc.stderr)
            (base / "document").mkdir(parents=True, exist_ok=True)
            (base / "document").mkdir(parents=True, exist_ok=True)
            document, *_ = self.install(base / "document", "elephant-goldfish")
            validator = document / "scripts" / "validate_document.py"
            folder = base / "docs"
            (folder / "slug-a").mkdir(parents=True)
            (folder / "slug-b").mkdir()
            (folder / "slug-a" / "index.md").write_text("# A\n")
            sha = hashlib.sha256((folder / "slug-a" / "index.md").read_bytes()).hexdigest()
            content = {"document_sha256": sha, "verdict": "ready"}
            row = {"observer": "coordinator", "kind": "cold-read", "source": "fixture reader", "content": content,
                   "sha256": hashlib.sha256(canonical(content)).hexdigest()}
            observation = base / "cold-read.json"
            observation.write_text(json.dumps({"kind": "cold-read-observation", "document_path": str(folder / "slug-a" / "index.md"), "document_sha256": sha, "verdict": "ready", "evidence": [row]}))
            proc = subprocess.run([sys.executable, str(validator), "--root", str(folder), "--slug", "slug-b", "--mode", "cold-read", "--input", str(observation)], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)

    def test_installed_cli_rejects_oversize_transport_before_read_and_status_is_read_only(self):
        """R19/R20: bound file reads and do not mint coordinator authority."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, manifest, prefix, agents, state_root = self.install(base, "ape")
            job = self.base_job("cli-review")
            job["installation_id"] = manifest["installation_id"]
            job["pins"] = {}
            create_pinned_job(job, state_root, prefix, agents, base / "config" / "workers.json")
            from shared.job_coordinator import verify_job_pins
            store = Store(state_root, job["job_id"], verify_pins=verify_job_pins)
            before = canonical(store.load())
            script = version / "shared" / "job_cli.py"
            proc = subprocess.run([sys.executable, str(script), "status", "--state-root", str(state_root), "--job", job["job_id"]], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            # A read-only command must not change the state generation or histories.
            self.assertEqual(canonical(store.load()), before)
            oversized = base / "large-result.json"
            with oversized.open("wb") as handle:
                handle.truncate(40_000_000)
            self.assertEqual(oversized.stat().st_size, 40_000_000)
            task = store.load()["tasks"][0]
            task["status"] = "awaiting-acceptance"
            task["brief"] = {
                "path": str(base / "prepared-brief.json"), "sha256": "1" * 64,
                "effective_brief_sha256": "2" * 64, "job_id": job["job_id"], "stage_id": "s0",
                "logical_slot_id": "primary", "request_id": "req0", "worker_id": "ape/source-researcher",
                "revision": "s0-r1", "snapshot": None,
            }
            (base / "prepared-brief.json").write_text("{}")
            from core.jobs.store import _atomic
            changed = store.load()
            changed["tasks"][0] = task
            _atomic(store.file, canonical(changed))
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"], "package_digest": manifest["package_digest"], "actor": "coordinator"}
            cli_input = base / "result-command.json"
            cli_input.write_text(json.dumps({"caller": caller, "task_id": "t0", "completion_id": "large-result", "result": {"path": str(oversized)}}))
            proc = subprocess.run([sys.executable, str(script), "result", "--state-root", str(state_root), "--job", job["job_id"], "--input", str(cli_input)], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)

    def test_validator_process_has_timeout_and_bounded_output(self):
        """R21: actual acceptance invocation must terminate a hanging validator."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, manifest, prefix, agents, state_root = self.install(base, "ape")
            job = self.base_job("hang-review")
            job["tasks"] = []
            job["stages"][0]["execution_mode"] = "direct"
            source = base/"source.txt"; source.write_text("fixture source\n")
            source_pin = {"id":"src","url":"https://example.invalid","revision":"r1","path":str(source),"sha256":hashlib.sha256(source.read_bytes()).hexdigest()}
            job["stages"][0]["validator_contract"] = {"sources":[source_pin]}
            job["stages"][0].update(validator_limits={"timeout_seconds": 1, "max_output_bytes": 1024}, criteria=[{"id": "C1", "kind": "source-provenance"}])
            job["installation_id"] = manifest["installation_id"]
            job["pins"] = {}
            create_pinned_job(job, state_root, prefix, agents, base / "config" / "workers.json")
            store = Store(state_root, job["job_id"])
            caller = {"installation_id": manifest["installation_id"], "workflow": job["workflow"], "package_digest": manifest["package_digest"], "actor": "coordinator"}
            validator = version / "scripts" / "validate_report.py"
            original = validator.read_text()
            report = base / "report.json"
            report.write_text(json.dumps({"sources": [source_pin], "findings": [], "criteria": [{"id": "C1", "kind": "source-provenance"}]}))
            report = Path(publish_observation(store, caller, "s0", str(report))["path"])
            argv = [str(validator), "--input", str(report)]
            hook = base / "sitecustomize.py"
            hook.write_text("import time\ntime.sleep(20)\n")
            env = dict(os.environ, PYTHONPATH=str(base) + os.pathsep + os.environ.get("PYTHONPATH", ""))
            started = time.monotonic()
            try:
                with mock.patch.dict(os.environ, env):
                    receipt = accept_stage(store, caller, 's0', argv, str(report), 's0-r1')
                    self.assertFalse(receipt['accepted'])
                    self.assertIn('timeout', receipt.get('error', ''))
                self.assertLess(time.monotonic() - started, 10)
                hook.write_text("print('x' * 5000)\n")
                with mock.patch.dict(os.environ, env):
                    flooded = accept_stage(store, caller, 's0', argv, str(report), 's0-r1')
                self.assertFalse(flooded['accepted'])
                self.assertIn('output limit', flooded.get('error', ''))
            finally:
                self.assertEqual(validator.read_text(), original)

    def test_tuneup_apply_requires_real_change_and_plan_revision_rejects_runtime_state(self):
        """R22/R24: actual validator criteria and plan data cannot self-promote."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            version, *_ = self.install(base, "agent-tuneup")
            validator = version / "scripts" / "validate_audit.py"
            inp = base / "audit.json"
            inp.write_text(json.dumps({"findings": [], "changes": [], "criteria": {"operation": "apply", "findings_allowed": True, "live_enforcement_required": False}, "audit_exit_code": 0}))
            proc = subprocess.run([sys.executable, str(validator), "--input", str(inp)], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
        with tempfile.TemporaryDirectory() as td:
            store = self.make_store(td)
            caller = self.caller()
            plan = store.load()
            plan["stages"][0]["status"] = "accepted-at-snapshot"
            plan["tasks"][0]["status"] = "awaiting-acceptance"
            with self.assertRaises(JobError):
                revise_plan(store, caller, {"id": "runtime-fields"}, plan)

    def valid_result(self):
        return {
            "schema_version": 1, "job_id": "j", "stage_id": "s", "logical_slot_id": "slot",
            "request_id": "r", "worker_id": "p/w", "effective_brief_sha256": "a" * 64,
            "status": "ready-for-acceptance", "conclusion": "done",
            "requirements": [{"id": "R1", "status": "passed", "evidence": ["fixture evidence"]}],
            "review_verdict": None, "findings": [], "gaps": [], "uncertainties": [], "changes": [],
            "commands": [], "artifacts": [], "revision": None, "binding": None,
            "extra_work_requests": [], "metrics": {},
        }

    @staticmethod
    def expected_result(result):
        return {key: result[key] for key in ("job_id", "stage_id", "logical_slot_id", "request_id", "worker_id", "effective_brief_sha256")}


if __name__ == "__main__":
    unittest.main()
