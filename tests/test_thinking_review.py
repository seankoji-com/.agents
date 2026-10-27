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
from tests.thinking_plan_review_fixtures import ThinkingPlanFixture, init_selection_args

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/elephant-goldfish"


class ReviewCommands:
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="thinking-review-test-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name) / "thinking"
        self.plan_fixture = ThinkingPlanFixture(Path(self.scratch.name) / 'plan-fixture')
        self.capabilities = Path(self.scratch.name) / 'capabilities.json'
        self.capabilities.write_bytes((ROOT / 'tests/fixtures/t3/capabilities.json').read_bytes())
        self.topic = self.root / "topic"
        self.state("init", "topic", "--output-type", "implementation")
        self.discovery = "# Discovery\nPrevent duplicate charges; credentials remain an owner gate.\n"
        self.write("discovery.md", self.discovery)
        self.write("spec.md", "# Rubric\n[REQ-ONCE] No duplicate charge.\n")

    def command(self, script, *args, ok=True, input_text=None):
        result = subprocess.run([sys.executable, str(self.scripts / script), "--root", str(self.root), *args],
                                cwd=self.scratch.name, capture_output=True, text=True,
                                env=self.plan_fixture.box.env,
                                input=input_text)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        return result

    def state(self, *args, ok=True, input_text=None):
        if args[0] == "init":
            args = (*args, *init_selection_args(self.scratch.name, args[1]))
        return json.loads(self.command("thinking_state.py", *args, ok=ok, input_text=input_text).stdout)

    def render(self, *args, ok=True):
        if ok and '--check' not in args and '--draft' not in args:
            self.review_plan()
        return self.command("render_handoff.py", "topic", "--capabilities", str(self.capabilities), *args, ok=ok)

    def review_plan(self):
        if not self.state('resolve', 'topic')['plan_review']['ready']:
            self.plan_fixture.approve(self.scripts, self.root, 'topic')

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
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "plan_review")
        self.review_plan()
        self.state("gate", "topic", "--require", "discovery,spec")
        self.render()
        self.render("--check")
        self.state("gate", "topic", "--require", "discovery,spec,handoff")
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "delivery")
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
        self.assertNotIn("imps run Read thinking/", text)
        self.assertFalse((self.topic / "handoff.md").exists())
        # The draft's author record names the draft file and never repoints handoff.md.
        records = json.loads((self.topic / "document-authors.json").read_text())
        draft_hash = hashlib.sha256(text.encode()).hexdigest()
        draft_path = str((self.topic / "handoff.draft.md").resolve())
        self.assertEqual(records[draft_hash]["document_path"], draft_path)
        self.assertEqual(records["_document_paths"][draft_path]["sha256"], draft_hash)
        self.assertNotIn(str((self.topic / "handoff.md").resolve()), records["_document_paths"])
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "discovery_review")
        self.accept()
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "spec")
        self.render(ok=False)
        self.state("gate", "topic", "--require", "discovery,spec", ok=False)

    def test_legacy_completion_and_stale_final_provenance_cannot_complete(self):
        self.write("handoff.md", "Old handoff")
        self.assert_held("missing")
        self.accept()
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "plan_review")
        self.render()
        self.write("spec.md", "[REQ-API] Use the official API.")
        state = self.state("resolve", "topic")
        self.assertEqual(state["next_phase"], "plan_review")
        self.assertIn("plan review", state["hold_reason"])
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

    def test_replacing_review_receipt_reopens_handoff_without_changing_provenance(self):
        self.accept()
        self.render()
        for decision, statement in (("owner_override", "Finalise only this brief without claiming discovery acceptance."),
                                    ("accepted", "I accept this discovery as presented."),
                                    ("accepted", "I accept this discovery; this is a replacement evidence statement.")):
            with self.subTest(decision=decision, statement=statement):
                state = self.accept(decision=decision, statement=statement)
                self.assertEqual(state["next_phase"], "plan_review")
                self.assertIn("owner discovery decision changed", state["hold_reason"])
                self.assertEqual(self.state("list")["topics"][0]["next_phase"], "plan_review")
                self.state("gate", "topic", "--require", "discovery,spec,handoff", ok=False)
                self.render("--check")  # Source/output provenance is still intact.
                self.render()
                self.state("gate", "topic", "--require", "discovery,spec,handoff")
                self.assertIn(f"Review status: {decision}.", (self.topic / "handoff.md").read_text())
                self.assertEqual(self.state("resolve", "topic")["next_phase"], "delivery")

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
        self.assertTrue(state["has_execution_request"])
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
        self.assertEqual(self.state("resolve", "topic")["next_phase"], "delivery")

    def test_standalone_draft_status_after_heading_or_bom_holds_final_output(self):
        self.accept()
        for content in ("# Spec\n<!-- thinking:draft -->\n[REQ-ONCE] Proposed.",
                        "\ufeff<!-- thinking:draft -->\n[REQ-ONCE] Proposed.",
                        "# Spec\nDRAFT. Non-executable.\n[REQ-ONCE] Proposed.",
                        "\ufeff# Spec\nDRAFT. Non-executable.\n[REQ-ONCE] Proposed."):
            with self.subTest(content=content):
                self.write("spec.md", content)
                self.assertEqual(self.state("resolve", "topic")["next_phase"], "spec")
                self.assertEqual(self.state("list")["topics"][0]["next_phase"], "spec")
                self.state("gate", "topic", "--require", "discovery,spec", ok=False)
                self.render(ok=False)
                self.render("--stdout", ok=False)

    def test_code_fenced_draft_examples_are_inert(self):
        self.accept()
        examples = ("```markdown\n<!-- thinking:draft -->\nDRAFT. Non-executable.\n```",
                    "~~~markdown\n<!-- thinking:draft -->\nDRAFT. Non-executable.\n~~~",
                    "````markdown\n```\n<!-- thinking:draft -->\n```\n````",
                    "    <!-- thinking:draft -->\n    DRAFT. Non-executable.")
        for example in examples:
            with self.subTest(example=example):
                self.write("spec.md", "# Rubric\nExample only:\n" + example + "\n[REQ-ONCE] Final criterion.")
                self.render()
                self.assertEqual(self.state("resolve", "topic")["next_phase"], "delivery")

    def test_malformed_topic_does_not_hide_healthy_topics(self):
        self.state("init", "bad", "--output-type", "research")
        bad = self.root / "bad"
        initial = (bad / "meta.json").read_bytes()
        variants = (b'{not json', b'[]', b'{"published":null}')
        for meta in variants:
            with self.subTest(meta=meta):
                (bad / "meta.json").write_bytes(meta)
                topics = {row["slug"]: row for row in self.state("list")["topics"]}
                self.assertEqual(topics["bad"]["next_phase"], "topic_repair")
                self.assertIsNone(topics["bad"]["has_execution_request"])
                self.assertFalse(topics["bad"]["review"]["ready"])
                self.assertEqual(topics["topic"]["next_phase"], "discovery_review")
        (bad / "meta.json").write_bytes(initial)
        (bad / "discovery.md").write_bytes(b'\xff')
        topics = {row["slug"]: row for row in self.state("list")["topics"]}
        self.assertEqual(topics["bad"]["next_phase"], "topic_repair")
        self.assertFalse(topics["bad"]["has_execution_request"])
        self.assertIn("malformed topic", topics["bad"]["hold_reason"])
        self.assertEqual(topics["topic"]["next_phase"], "discovery_review")
        self.state("resolve", "bad", ok=False)

    def test_review_refuses_draft_discovery_before_recording_any_receipt(self):
        self.write("discovery.md", "# Discovery\n<!-- thinking:draft -->\nProposed problem.")
        digest = hashlib.sha256((self.topic / "discovery.md").read_bytes()).hexdigest()
        result = self.state("review", "topic", "--decision", "accepted", "--scope", "finalise-brief",
                            "--discovery-sha256", digest, "--evidence-ref", "fixture:user-message:1",
                            "--operator-statement", "I accept the discovery.", ok=False)
        self.assertIn("draft discovery", result["error"])
        state = self.state("resolve", "topic")
        self.assertEqual(state["next_phase"], "discovery")
        self.assertNotIn("review", state["meta"])

    def test_inline_backtick_spans_do_not_hide_later_draft_status(self):
        self.accept()
        for inline in ("```x``` is inline code in prose.", "```a`b"):
            with self.subTest(inline=inline):
                self.write("spec.md", "# Spec\n" + inline +
                           "\n<!-- thinking:draft -->\nDRAFT. Non-executable.\n[REQ-ONCE] Proposed.")
                self.assertEqual(self.state("resolve", "topic")["next_phase"], "spec")
                self.assertEqual(self.state("list")["topics"][0]["next_phase"], "spec")
                self.state("gate", "topic", "--require", "discovery,spec", ok=False)
                self.render(ok=False)
                self.render("--stdout", ok=False)

    def test_statement_file_and_stdin_preserve_shell_text_as_data(self):
        statement = "--I accept this discovery. Keep `literal` and $(touch must-not-exist) as text.\n"
        path = Path(self.scratch.name) / "operator-statement.txt"
        path.write_text(statement)
        base = ("review", "topic", "--decision", "accepted", "--scope", "finalise-brief",
                "--discovery-sha256", hashlib.sha256(self.discovery.encode()).hexdigest(),
                "--evidence-ref", "fixture:user-message:1", "--operator-statement-file")
        for source in (str(path), "-"):
            with self.subTest(source=source):
                state = self.state(*base, source, input_text=statement if source == "-" else None)
                self.assertEqual(state["meta"]["review"]["operator_statement"], statement)
                self.assertFalse((Path(self.scratch.name) / "must-not-exist").exists())
        self.state(*base, "-", input_text=" \n", ok=False)
        self.state(*base, str(path.parent / "absent.txt"), ok=False)


class TestSourceReview(ReviewCommands, unittest.TestCase):
    scripts = PLUGIN / "scripts"


class TestInstalledReview(ReviewCommands, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installation = tempfile.TemporaryDirectory(prefix="thinking-installed-test-")
        cls.addClassCleanup(cls.installation.cleanup)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"),
                                 "--plugin", "elephant-goldfish", "--prefix", cls.installation.name,
                                 "--agents-root", str(Path(cls.installation.name) / "managed-agents")],
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
