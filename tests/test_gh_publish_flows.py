"""elephant-goldfish publishing against a scripted `gh`: creating the Issue or
Discussion, choosing a category, posting to either, and the errors GitHub returns
with a zero exit status. No network; every `gh` call goes through a fake `run`."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/elephant-goldfish/scripts/gh_publish.py"
spec = importlib.util.spec_from_file_location("gh_publish_flows", SCRIPT)
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)

CATEGORIES = [{"id": "C-ann", "name": "Announcements"}, {"id": "C-gen", "name": "General"},
              {"id": "C-ideas", "name": "Ideas"}]


class FakeGh:
    """Answers `gh` argv by its first words; records every call."""

    def __init__(self, categories=CATEGORIES, issue_output="https://github.com/o/r/issues/12"):
        self.calls = []
        self.categories = categories
        self.issue_output = issue_output

    def __call__(self, cmd, stdin=None):
        self.calls.append((cmd, stdin))
        if cmd[:3] == ["gh", "issue", "create"]:
            return self.issue_output
        if cmd[:3] == ["gh", "issue", "comment"]:
            return "https://github.com/o/r/issues/12#issuecomment-1"
        if cmd[:3] == ["gh", "repo", "view"]:
            return "o/r"
        query = next(arg for arg in cmd if arg.startswith("query="))
        if "discussionCategories" in query:
            return json.dumps({"data": {"repository": {"id": "R-1", "discussionCategories": {"nodes": self.categories}}}})
        if "createDiscussion" in query:
            return json.dumps({"data": {"createDiscussion": {"discussion": {
                "id": "D-1", "number": 5, "url": "https://github.com/o/r/discussions/5"}}}})
        if "addDiscussionComment" in query:
            return json.dumps({"data": {"addDiscussionComment": {"comment": {"url": "https://github.com/o/r/discussions/5#c1"}}}})
        raise AssertionError(f"unexpected gh call {cmd}")


class PublishFlowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.topic = self.root / "topic"
        self.topic.mkdir()
        self.meta = self.topic / "meta.json"
        self.meta.write_text(json.dumps({"title": "Topic", "output_type": "spec"}))
        (self.topic / "spec.md").write_text("The spec")
        gh_on_path = patch.object(gp, "require_gh")
        gh_on_path.start()
        self.addCleanup(gh_on_path.stop)

    def invoke(self, fake, handler, **fields):
        args = argparse.Namespace(root=str(self.root), slug="topic", dry_run=False, **fields)
        out = io.StringIO()
        with patch.object(gp, "run", fake), contextlib.redirect_stdout(out):
            code = handler(args)
        return code, json.loads(out.getvalue())

    def ensure(self, fake, mode, repo="o/r", category=None):
        return self.invoke(fake, gp.cmd_ensure, mode=mode, repo=repo, category=category)

    def post(self, fake):
        return self.invoke(fake, gp.cmd_post, artifact="spec.md")

    def test_issue_is_created_once_and_its_url_found_among_other_output(self):
        fake = FakeGh(issue_output="A new release of gh is available\nhttps://github.com/o/r/issues/12\n")
        code, receipt = self.ensure(fake, "issue")
        self.assertEqual((code, receipt["status"], receipt["number"]), (0, "created", 12))
        self.assertEqual(json.loads(self.meta.read_text())["github"]["url"], "https://github.com/o/r/issues/12")
        code, receipt = self.ensure(fake, "issue")
        self.assertEqual(receipt["status"], "exists")
        self.assertEqual(sum(1 for cmd, _ in fake.calls if cmd[:3] == ["gh", "issue", "create"]), 1)
        code, receipt = self.post(fake)
        self.assertEqual(receipt["status"], "posted")
        cmd, body = fake.calls[-1]
        self.assertEqual(cmd[:4], ["gh", "issue", "comment", "12"])
        self.assertIn("The spec", body)

    def test_issue_output_without_a_url_is_an_error_and_records_nothing(self):
        with self.assertRaisesRegex(gp.PublishError, "no issue URL"):
            self.ensure(FakeGh(issue_output="something went sideways"), "issue")
        self.assertNotIn("github", json.loads(self.meta.read_text()))

    def test_discussion_prefers_ideas_then_posts_to_the_discussion(self):
        fake = FakeGh()
        code, receipt = self.ensure(fake, "discussion")
        self.assertEqual((receipt["category"], receipt["node_id"], receipt["number"]), ("Ideas", "D-1", 5))
        created = next(cmd for cmd, _ in fake.calls if any("createDiscussion" in a for a in cmd))
        self.assertIn("c=C-ideas", created)
        self.assertIn("-f", created)
        code, receipt = self.post(fake)
        self.assertEqual(receipt["url"], "https://github.com/o/r/discussions/5#c1")
        self.assertTrue(any("d=D-1" in cmd for cmd, _ in fake.calls))

    def test_discussion_category_choice(self):
        with patch.object(gp, "run", FakeGh()):
            self.assertEqual(gp.repo_ids("o/r", "announcements"), ("R-1", "C-ann", "Announcements"))
            with self.assertRaisesRegex(gp.PublishError, "available: Announcements, General, Ideas"):
                gp.repo_ids("o/r", "Polls")
        with patch.object(gp, "run", FakeGh(categories=[{"id": "C-q", "name": "Q&A"}])):
            self.assertEqual(gp.repo_ids("o/r", None)[2], "Q&A")
        with patch.object(gp, "run", FakeGh(categories=[])):
            with self.assertRaisesRegex(gp.PublishError, "enable Discussions"):
                gp.repo_ids("o/r", None)

    def test_graphql_errors_with_a_zero_exit_surface_githubs_message(self):
        answer = json.dumps({"data": {"repository": None}, "errors": [{"message": "Could not resolve to a Repository"}]})
        with patch.object(gp, "run", return_value=answer):
            with self.assertRaisesRegex(gp.PublishError, "Could not resolve to a Repository"):
                gp.repo_ids("o/missing", None)
        with patch.object(gp, "run", return_value=json.dumps({"data": {"repository": None}})):
            with self.assertRaisesRegex(gp.PublishError, "not found or not accessible"):
                gp.repo_ids("o/missing", None)

    def test_ensure_needs_a_real_mode_and_dry_run_writes_nothing(self):
        with self.assertRaisesRegex(gp.PublishError, "explicit --mode"):
            self.ensure(FakeGh(), "none")
        fake = FakeGh()
        args = argparse.Namespace(root=str(self.root), slug="topic", dry_run=True, mode="discussion", repo=None, category=None)
        with patch.object(gp, "run", fake), contextlib.redirect_stdout(io.StringIO()) as out:
            gp.cmd_ensure(args)
        self.assertEqual(json.loads(out.getvalue())["repo"], "o/r")
        self.assertEqual([cmd[:3] for cmd, _ in fake.calls], [["gh", "repo", "view"]])
        self.assertNotIn("github", json.loads(self.meta.read_text()))

    def test_post_before_ensure_and_oversized_bodies_are_refused(self):
        meta = json.loads(self.meta.read_text())
        meta["github"] = {"mode": "issue", "repo": "o/r"}
        self.meta.write_text(json.dumps(meta))
        with self.assertRaisesRegex(gp.PublishError, "run `ensure` first"):
            self.post(FakeGh())
        (self.topic / "spec.md").write_text("x" * gp.MAX_BODY)
        with self.assertRaisesRegex(gp.PublishError, "over GitHub's"):
            gp.body_for(self.topic / "spec.md", "topic")

    def test_main_maps_errors_to_exit_codes(self):
        with patch.object(gp, "detect_repo", side_effect=gp.EnvError("no gh")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(gp.main(["--root", str(self.root), "detect-repo"]), 2)
        self.assertIn("no gh", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(gp.main(["--root", str(self.root), "post", "topic", "notes.md"]), 1)
        self.assertIn("local-only", err.getvalue())

    def test_run_reports_a_missing_binary_and_a_failing_command(self):
        with self.assertRaisesRegex(gp.EnvError, "not found on PATH"):
            gp.run(["definitely-not-a-real-binary-t3"])
        with self.assertRaisesRegex(gp.PublishError, "failed: boom"):
            gp.run(["sh", "-c", "echo boom >&2; exit 3"])


if __name__ == "__main__":
    unittest.main()
