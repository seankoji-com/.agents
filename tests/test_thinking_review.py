"""Public CLI and instruction-contract regressions. No live models or GitHub writes.

Instruction checks detect missing guards, not whether a model obeys them. The same
command scenarios run against the source and a scratch-prefix installed package.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/elephant-goldfish"


class ReviewCommands:
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="thinking-review-test-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "thinking"
        self.topic = self.root / "topic"
        self.state("init", "topic", "--output-type", "implementation")
        self.discovery = "# Discovery\nPrevent duplicate charges; credentials remain an owner gate.\n"
        self.write("discovery.md", self.discovery)
        self.write("spec.md", "# Rubric\n[REQ-ONCE] No duplicate charge.\n")

    def command(self, script, *args, ok=True):
        result = subprocess.run([sys.executable, str(self.scripts / script), "--root", str(self.root), *args],
                                cwd=self.scratch.name, capture_output=True, text=True,
                                env={key: value for key, value in os.environ.items() if key != "T3_PLUGIN_ROOT"})
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        return result

    def state(self, *args, ok=True):
        return json.loads(self.command("thinking_state.py", *args, ok=ok).stdout)

    def render(self, *args, ok=True):
        return self.command("render_handoff.py", "topic", *args, ok=ok)

    def write(self, name, content):
        (self.topic / name).write_text(content, encoding="utf-8")

    def accept(self, *, decision="accepted", digest=None, statement=None):
        return self.state("review", "topic", "--decision", decision, "--scope", "finalise-brief",
                          "--discovery-sha256", digest or hashlib.sha256(self.discovery.encode()).hexdigest(),
                          "--evidence-ref", "fixture:user-message:review-1",
                          "--operator-statement", statement or "I accept this discovery as presented.")

    def assert_held(self, reason):
        resolved = self.state("resolve", "topic")
        listed = self.state("list")["topics"][0]
        for state in (resolved, listed):
            self.assertEqual(state["next_phase"], "discovery_review")
            self.assertIn(reason, state["hold_reason"])
            self.assertFalse(state["execution_authorized"])
        gate = self.state("gate", "topic", "--require", "discovery,spec,handoff", ok=False)
        self.assertIn(reason, gate["error"])
        self.assertIn(reason, self.render(ok=False).stderr)
        self.assertIn(reason, self.render("--stdout", ok=False).stderr)

    def test_missing_malformed_stale_and_other_content_receipts_hold_all_commands(self):
        self.write("handoff.md", "A stale final-looking brief")
        original = json.loads((self.topic / "meta.json").read_text())
        for receipt in (None, [], "accepted", {},
                        {"status": "awaiting_operator_discovery_review"}):
            with self.subTest(receipt=receipt):
                meta = dict(original)
                if receipt is not None:
                    meta["review"] = receipt
                self.write("meta.json", json.dumps(meta))
                self.assert_held("missing" if receipt is None else "malformed")
        self.write("meta.json", json.dumps(original))
        self.accept()
        valid = json.loads((self.topic / "meta.json").read_text())
        for key, value in (("scope", "implementation"), ("operator_statement", " "),
                           ("evidence_ref", ""), ("recorded_at", None),
                           ("recorded_at", "2026-99-99T00:00:00Z"), ("schema", True), ("schema", 7)):
            with self.subTest(key=key):
                meta = dict(valid, review=dict(valid["review"], **{key: value}))
                self.write("meta.json", json.dumps(meta))
                self.assert_held("malformed")
        valid["review"]["discovery_sha256"] = "0" * 64
        self.write("meta.json", json.dumps(valid))
        self.assert_held("changed")

    def test_accepted_content_progresses_and_edits_reopen_review(self):
        self.write("spec.md", "")
        self.assertEqual(self.accept()["next_phase"], "spec")
        self.write("spec.md", "[REQ-ONCE] No duplicate charge.")
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "handoff")
        self.state("gate", "topic", "--require", "discovery,spec")
        self.render()
        self.render("--check")
        self.state("gate", "topic", "--require", "discovery,spec,handoff")
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "complete")
        self.write("discovery.md", self.discovery + "Use the official API.\n")
        self.assert_held("changed")
        self.render("--check", ok=False)

    def test_review_command_rejects_wrong_hash_empty_evidence_and_set_shortcuts(self):
        base = ["review", "topic", "--decision", "accepted", "--scope", "finalise-brief",
                "--discovery-sha256", "0" * 64, "--evidence-ref", "fixture:user-message:1",
                "--operator-statement", "I accept this discovery."]
        self.assertIn("hash differs", self.state(*base, ok=False)["error"])
        base[base.index("--discovery-sha256") + 1] = hashlib.sha256(self.discovery.encode()).hexdigest()
        for flag in ("--operator-statement", "--evidence-ref"):
            args = list(base)
            args[args.index(flag) + 1] = " "
            self.assertIn("nonempty", self.state(*args, ok=False)["error"])
        for pair in ('review.status=accepted', 'review={"status":"accepted"}'):
            self.state("set", "topic", pair, ok=False)
        self.assertNotIn("review", self.state("resolve", "topic")["meta"])

    def test_requested_draft_is_non_executable_and_never_complete(self):
        self.write("spec.md", "<!-- thinking:draft -->\nDRAFT. Non-executable.\nProposed [REQ-ONCE].")
        self.state("gate", "topic", "--require", "discovery,spec", "--draft")
        self.render("--draft")
        self.render("--draft", "--check")
        text = (self.topic / "handoff.draft.md").read_text()
        self.assertIn("DRAFT. Non-executable.", text)
        self.assertNotIn("t3-plugins prompt imps", text)
        self.assertFalse((self.topic / "handoff.md").exists())
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "discovery_review")
        self.accept()
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "spec")
        self.render(ok=False)
        self.state("gate", "topic", "--require", "discovery,spec", ok=False)

    def test_legacy_completion_and_stale_final_provenance_cannot_complete(self):
        self.write("handoff.md", "Old handoff")
        self.assert_held("missing")
        self.accept()
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "handoff")
        self.render()
        self.write("spec.md", "[REQ-API] Use the official API.")
        state = self.state("resolve", "topic")
        self.assertEqual(state["next_phase"], "handoff")
        self.assertIn("provenance", state["hold_reason"])
        self.state("gate", "topic", "--require", "discovery,spec,handoff", ok=False)
        self.render("--check", ok=False)

    def test_owner_override_is_scoped_and_does_not_claim_acceptance_or_execution(self):
        state = self.accept(decision="owner_override",
                            statement="Skip discovery acceptance and finalise only this brief.")
        self.assertEqual(state["review"]["status"], "owner_override")
        self.assertEqual(state["review"]["scope"], "finalise-brief")
        self.assertFalse(state["execution_authorized"])
        self.render()
        text = (self.topic / "handoff.md").read_text()
        self.assertIn("Review status: owner_override", text)
        self.assertIn("separate user instruction is required", text)

    def test_provenance_is_independent_of_current_review_readiness(self):
        self.accept()
        self.render()
        meta = json.loads((self.topic / "meta.json").read_text())
        del meta["review"]
        self.write("meta.json", json.dumps(meta))
        self.assertIn("authority not verified", self.render("--check").stdout)
        self.assert_held("missing")

    def test_refining_requirement_and_old_reminders_never_grant_execution(self):
        self.accept()
        self.render()
        self.state("set", "topic", "unrelated_production_authorized=true",
                   'scheduled_prompt=Continue implementation', 'feature_answer=Use official API')
        self.write("discovery.md", self.discovery + "Use official API, as clarified on resume.")
        self.assert_held("changed")
        state = self.state("set", "topic", 'execution_request.scope=Implement retry policy in this repo',
                           'execution_request.evidence_ref=fixture:user-message:transition-1',
                           'execution_request.operator_statement=Leave thinking and implement the retry policy in this repo')
        self.assertEqual(state["meta"]["execution_request"]["scope"], "Implement retry policy in this repo")
        self.assertFalse(state["execution_authorized"], "receipt storage itself grants no authority")

    def test_final_handoff_preserves_named_blocker_and_hold_instruction(self):
        self.write("discovery.md", self.discovery + "Credential gate: owner Operator; next action supply a scoped key.")
        self.accept(digest=hashlib.sha256((self.topic / "discovery.md").read_bytes()).hexdigest())
        self.render()
        text = (self.topic / "handoff.md").read_text()
        self.assertIn("owner Operator; next action supply a scoped key", text)
        self.assertIn("Hold work", text)
        self.assertIn("Do not invent credentials, widen access, or increase a budget", text)

    def test_manifest_tampering_is_consistently_rejected(self):
        self.accept()
        self.render()
        path = self.topic / "handoff.manifest.json"
        original = json.loads(path.read_text())
        for field, value in (("status", "draft"), ("requirement_ids", []),
                             ("handoff_sha256", "0" * 64), ("schema", 1)):
            with self.subTest(field=field):
                path.write_text(json.dumps(dict(original, **{field: value})))
                self.assertEqual(self.state("resolve", "topic")["next_phase"], "handoff")
                self.assertEqual(self.state("list")["topics"][0]["next_phase"], "handoff")
                self.state("gate", "topic", "--require", "discovery,spec,handoff", ok=False)
                self.render("--check", ok=False)

    def test_draft_marker_in_quoted_notes_is_inert(self):
        self.write("spec.md", "# Rubric\nThe draft marker is `<!-- thinking:draft -->`; [REQ-ONCE] remains final.")
        self.accept()
        self.render()
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "complete")


class TestSourceReview(ReviewCommands, unittest.TestCase):
    scripts = PLUGIN / "scripts"


class TestInstalledReview(ReviewCommands, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = tempfile.TemporaryDirectory(prefix="thinking-installed-test-")
        cls.addClassCleanup(cls.installation.cleanup)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"),
                                 "--plugin", "elephant-goldfish", "--prefix", cls.installation.name],
                                capture_output=True, text=True, cwd=ROOT)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.scripts = Path(json.loads(result.stdout)["data"]["version_dir"]) / "scripts"


class TestThinkingInstructionContract(unittest.TestCase):
    def test_interview_and_boundary_scenarios_remain_in_the_shipped_playbook(self):
        text = (PLUGIN / "playbooks/thinking.md").read_text()
        cases = {
            "Feature-selection interview": ("current workaround", "present it for review"),
            "New example": ("Update discovery", "reopen review"),
            "Draft request": ("non-executable drafts", "does not accept discovery"),
            "Stop request": ("stops the interview", "Do not", "acceptance"),
            "Requirement change on resume": ("refines discovery", "scheduled", "unrelated production", "permission"),
            "Deliberate transition": ("new instruction", "Record its source and exact scope"),
        }
        scenarios = text.split("## Regression scenarios", 1)[1]
        for name, terms in cases.items():
            with self.subTest(name=name):
                item = next(part for part in scenarios.split("\n- ") if part.startswith(name))
                for term in terms:
                    self.assertIn(term, item)
        for term in ("actual decisions", "success/failure examples", "material tradeoffs",
                     "no minimum question count", "Feature answers, silence, model summaries",
                     "compaction", "implementation children, imps runs", "cannot measure interview quality"):
            self.assertIn(term, text)
        for template in ("handoff.implementation.md", "handoff.research.md"):
            body = (PLUGIN / "templates" / template).read_text()
            self.assertNotIn("no opportunity to ask follow-up", body)
            self.assertNotIn("do not stop to ask", body)
            for term in ("licence, budget, identity, credential, or authorisation gates", "owner", "next action"):
                self.assertIn(term, body)


if __name__ == "__main__":
    unittest.main()
