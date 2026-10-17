"""Exercise list-prs.sh review-state fields against an offline curl stub."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/babysitter/scripts/list-prs.sh"

CURL = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
assert sys.stdin.read().strip() == "Authorization: bearer fixture-token"
body = json.loads(a[a.index("--data") + 1])
with open(os.environ["LIST_FIXTURE_LOG"], "a") as log:
    log.write(json.dumps(body) + "\\n")
Path(a[a.index("-o") + 1]).write_text(os.environ["LIST_FIXTURE_RESPONSE"])
print("200", end="")
'''


def thread(index, resolved=False, outdated=False):
    return {"isResolved": resolved, "isOutdated": outdated,
            "comments": {"nodes": [{"databaseId": 1000 + index, "body": "finding"}]}}


def pull(number, threads, has_next=False, total=None, decision=None, latest=()):
    return {
        "number": number, "title": "t", "url": f"https://github.com/fixture/repo/pull/{number}",
        "state": "OPEN", "isDraft": False, "isCrossRepository": False, "mergeable": "MERGEABLE",
        "mergeStateStatus": "BLOCKED", "author": {"login": "fixture"}, "headRefName": "h",
        "baseRefName": "main", "baseRef": {"target": {"oid": "b" * 40}},
        "repository": {"nameWithOwner": "fixture/repo"}, "comments": {"nodes": []},
        "reviews": {"nodes": []}, "reviewDecision": decision,
        "latestReviews": {"nodes": list(latest)},
        "reviewThreads": {"totalCount": len(threads) if total is None else total,
                          "pageInfo": {"hasNextPage": has_next}, "nodes": threads},
        "commits": {"nodes": [{"commit": {"oid": "a" * 40, "statusCheckRollup": None}}]},
    }


@unittest.skipUnless(shutil.which("jq"), "jq required by the shipped helper")
class ListPrsReviewStateTest(unittest.TestCase):
    def run_helper(self, response, *args):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in {"gh": "#!/bin/sh\nprintf fixture-token", "sleep": "#!/bin/sh\nexit 0",
                               "curl": CURL}.items():
                (root / name).write_text(body)
                (root / name).chmod(0o755)
            log = root / "calls.jsonl"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "LIST_FIXTURE_LOG": str(log), "LIST_FIXTURE_RESPONSE": json.dumps(response)}
            result = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True,
                                    text=True, timeout=20)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def search(self, *pulls):
        return {"data": {"viewer": {"login": "fixture"},
                         "search": {"issueCount": len(pulls), "nodes": list(pulls)}}}

    def test_review_thread_page_is_100_with_completeness_and_total(self):
        many = [thread(i, resolved=i % 2 == 0, outdated=i % 5 == 0) for i in range(100)]
        response = self.search(
            pull(1, many, has_next=True, total=155),
            pull(2, [thread(1), thread(2, resolved=True)]),
        )
        result, calls = self.run_helper(response, "--repo", "fixture/repo")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([(r["number"], r["review_threads_complete"], r["review_thread_total"],
                           r["unresolved_threads"]) for r in rows],
                         [(1, False, 155, 50), (2, True, 2, 1)])
        self.assertEqual(rows[0]["unresolved_outdated_threads"], 10)
        query = calls[0]["query"]
        self.assertIn("reviewThreads(first: 100)", query)
        self.assertNotIn("reviewThreads(first: 20)", query)
        self.assertIn("totalCount", query)
        self.assertIn("pageInfo { hasNextPage }", query)
        self.assertIn("comments(last: 5)", query)

    def test_review_decision_and_changes_requested_by(self):
        latest = (
            {"state": "CHANGES_REQUESTED", "author": {"login": "coderabbitai", "__typename": "Bot"}},
            {"state": "CHANGES_REQUESTED", "author": {"login": "octo-reviewer", "__typename": "User"}},
            {"state": "CHANGES_REQUESTED", "author": {"login": "dependabot[bot]", "__typename": "Bot"}},
            {"state": "APPROVED", "author": {"login": "approver", "__typename": "User"}},
            {"state": "CHANGES_REQUESTED", "author": None},
        )
        response = self.search(pull(1, [], decision="CHANGES_REQUESTED", latest=latest), pull(2, []))
        result, calls = self.run_helper(response, "--repo", "fixture/repo")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows[0]["review_decision"], "CHANGES_REQUESTED")
        self.assertEqual(rows[0]["changes_requested_by"],
                         ["coderabbitai[bot]", "dependabot[bot]", "ghost", "octo-reviewer"])
        self.assertEqual((rows[1]["review_decision"], rows[1]["changes_requested_by"]), (None, []))
        self.assertIn("reviewDecision", calls[0]["query"])
        self.assertIn("latestReviews(first: 50) { nodes { state author { login __typename } } }", calls[0]["query"])

    def test_sweep_page_defaults_to_100_and_accepts_50(self):
        result, calls = self.run_helper(self.search(), "--org", "fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0]["variables"]["limit"], 100)
        result, calls = self.run_helper(self.search(), "--org", "fixture", "--limit", "50")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0]["variables"]["limit"], 50)
        result, calls = self.run_helper(self.search(), "--org", "fixture", "--limit", "101")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_single_pr_mode_reports_the_same_fields(self):
        response = {"data": {"viewer": {"login": "fixture"}, "repository": {
            "pullRequest": pull(7, [thread(1)], decision="REVIEW_REQUIRED")}}}
        result, calls = self.run_helper(response, "--repo", "fixture/repo", "--pr", "7")
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual((row["review_threads_complete"], row["review_thread_total"], row["unresolved_threads"],
                          row["review_decision"], row["changes_requested_by"]),
                         (True, 1, 1, "REVIEW_REQUIRED", []))


if __name__ == "__main__":
    unittest.main()
