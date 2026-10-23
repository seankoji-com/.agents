"""Exercise the actual merge helper with isolated GitHub transport stubs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/babysitter/scripts/merge-pr.sh"
HEAD = "a" * 40


@unittest.skipUnless(shutil.which("jq"), "jq required by the shipped helper")
class MergeTest(unittest.TestCase):
    def run_helper(self, mode, extra_args=(), followups=(), followup_modes=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, body in {
                "gh": "#!/bin/sh\nprintf fixture-token",
                "sleep": "#!/bin/sh\nexit 0",
                "curl": '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
assert not any("fixture-token" in arg for arg in a), "credential leaked in argv"
assert "@-" in a, "header must be read from stdin"
assert sys.stdin.read().strip() == "Authorization: bearer fixture-token"
mode = os.environ["MERGE_FIXTURE_MODE"]
def empty_contexts():
    return {"pageInfo":{"hasNextPage":False}, "nodes":[]}
body = json.loads(a[a.index("--data")+1]) if "--data" in a else {}
with open(os.environ["MERGE_FIXTURE_LOG"], "a") as log:
    log.write(json.dumps(body)+"\\n")
state_file = Path(os.environ["MERGE_FIXTURE_LOG"]).with_suffix(".state")
query = body.get("query", "")
code = "200"
if "node(id:" in query:
    sha = "b"*40 if mode == "moves-after-reply" and state_file.exists() else "a"*40
    payload = {"data":{"node":{"id":"T1", "pullRequest":{"id":"OTHER" if mode=="foreign" else "PR1", "headRefOid":sha}}}}
elif query.startswith("query"):
    threads = []
    if mode in ("marker", "preexisting-unresolved", "conflict-threads", "threads-failing", "behind-threads") or (mode in ("flow", "repair-conflict", "repair-failing", "repair-review") and not state_file.exists()):
        threads = [{"id":"T1", "isResolved":False, "comments":{"nodes":[{"body":"[babysitter] fixed"}]}}]
    pr = {"id":"PR1", "state":"OPEN", "headRefOid":"a"*40, "mergeable":"MERGEABLE",
          "mergeStateStatus":"CLEAN", "autoMergeRequest":None,
          "reviewThreads":{"nodes":threads,"pageInfo":{"hasNextPage":mode=="truncated"}},
          "commits":{"nodes":[{"commit":{"statusCheckRollup":{"state":"SUCCESS", "contexts":empty_contexts()}}}]}}
    if mode in ("merged", "closed"): pr = {"state":mode.upper()}
    if mode in ("conflict", "conflict-threads"): pr["mergeable"] = "CONFLICTING"
    if mode == "behind":
        pr["mergeStateStatus"] = "BEHIND"
        if state_file.exists(): pr["headRefOid"] = "b"*40
    if mode == "null": pr = None
    if mode in ("failing", "preexisting-failing", "merged-after-block", "closed-after-block", "threads-failing"): pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["state"] = "FAILURE"
    if mode in ("already-auto", "preexisting-unresolved", "preexisting-failing"): pr["autoMergeRequest"] = {"enabledAt":"fixture-time"}
    rollup, merge_state = {
        "pending": ("PENDING", "BLOCKED"), "expected": ("EXPECTED", "BLOCKED"),
        "pending-dirty": ("PENDING", "DIRTY"), "no-checks": (None, "CLEAN"),
        "state-blocked": ("SUCCESS", "BLOCKED"), "state-unstable": ("SUCCESS", "UNSTABLE"),
        "state-has_hooks": ("SUCCESS", "HAS_HOOKS"), "state-unknown": ("SUCCESS", "UNKNOWN"),
        "review-required": ("SUCCESS", "BLOCKED"), "threads-before-arm": ("PENDING", "BLOCKED"),
    }.get(mode, (0, 0))
    if merge_state:
        pr["mergeStateStatus"] = merge_state
        pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = rollup and {"state":rollup, "contexts":empty_contexts()}
    if mode == "behind-threads":
        pr["mergeStateStatus"] = "BEHIND"
    if mode.startswith("unstable-"):
        # A non-required lint run is red, so GitHub reports UNSTABLE; the required
        # contexts below decide whether the helper may merge.
        pr["mergeStateStatus"] = "UNSTABLE"
        build = {"__typename":"CheckRun", "name":"build", "status":"COMPLETED", "conclusion":"SUCCESS", "isRequired":True}
        status = {"__typename":"StatusContext", "context":"ci/legacy", "state":"SUCCESS", "isRequired":True}
        lint = {"__typename":"CheckRun", "name":"lint", "status":"COMPLETED", "conclusion":"FAILURE", "isRequired":False}
        if mode == "unstable-required-failing": build["conclusion"] = "TIMED_OUT"
        if mode == "unstable-required-pending": build.update(status="IN_PROGRESS", conclusion=None)
        if mode == "unstable-status-expected": status["state"] = "EXPECTED"
        nodes = [lint] if mode == "unstable-zero-required" else [build, status, lint]
        pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = {"state":"FAILURE", "contexts":{
            "pageInfo":{"hasNextPage":mode == "unstable-page-incomplete"}, "nodes":nodes}}
        if mode == "unstable-threads": pr["reviewThreads"]["nodes"] = [{"id":"T9", "isResolved":False}]
        if mode == "unstable-review-required": pr["reviewDecision"] = "REVIEW_REQUIRED"
    if mode in ("bot-changes", "human-changes"):
        pr["mergeStateStatus"] = "BLOCKED"
        pr["reviewDecision"] = "CHANGES_REQUESTED"
        bot = {"login":"coderabbitai", "__typename":"Bot"}
        human = {"login":"octo-reviewer", "__typename":"User"}
        pr["latestReviews"] = {"nodes":[
            {"state":"APPROVED", "author":human if mode == "bot-changes" else bot},
            {"state":"CHANGES_REQUESTED", "author":bot if mode == "bot-changes" else human}]}
    if mode == "review-required": pr["reviewDecision"] = "REVIEW_REQUIRED"
    if mode == "threads-before-arm":
        if state_file.exists(): pr["reviewThreads"]["nodes"] = [{"id":"T1", "isResolved":False}]
        state_file.write_text("queried")
    if mode == "repair-conflict":
        pr["mergeable"] = "CONFLICTING"
        pr["mergeStateStatus"] = "DIRTY"
    if mode == "repair-failing":
        pr["mergeStateStatus"] = "BLOCKED"
        pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["state"] = "FAILURE"
    if mode == "repair-review":
        pr["mergeStateStatus"] = "BLOCKED"
        pr["reviewDecision"] = "CHANGES_REQUESTED"
    if mode in ("behind-then-fresh", "behind-then-green", "behind-then-same"):
        # update-branch lands a new head whose checks have not registered yet.
        pr["mergeStateStatus"] = ("CLEAN" if mode != "behind-then-fresh" else "UNKNOWN") if state_file.exists() else "BEHIND"
        if state_file.exists():
            if mode != "behind-then-same": pr["headRefOid"] = "b"*40
            if mode == "behind-then-fresh": pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"] = None
    if mode in ("merged-after-block", "closed-after-block"):
        if state_file.exists(): pr = {"state":"CLOSED" if mode.startswith("closed") else "MERGED"}
        state_file.write_text("queried")
    if mode == "author-pushed": pr["headRefOid"] = "b"*40
    if mode == "moves-before-merge":
        # A push lands between the gate read and the pre-merge reread.
        if state_file.exists(): pr["headRefOid"] = "b"*40
        state_file.write_text("queried")
    if mode in ("fails-before-merge", "blocked-before-merge"):
        # Same head, but the pre-merge reread shows a new failure or review blocker.
        if state_file.exists():
            if mode == "fails-before-merge":
                pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["state"] = "FAILURE"
            else:
                pr["mergeStateStatus"] = "BLOCKED"
                pr["reviewDecision"] = "CHANGES_REQUESTED"
        state_file.write_text("queried")
    payload = {"data":{"repository":{"pullRequest":pr}}}
elif "addPullRequestReviewThreadReply" in query:
    if mode == "moves-after-reply": state_file.write_text("pushed")
    if mode == "reply-fails":
        payload = {"data":None, "errors":[{"message":"fixture reply refused"}]}
    else:
        payload = {"data":{"addPullRequestReviewThreadReply":{"comment":{"id":"C1"}}}}
elif "resolveReviewThread" in query:
    if mode in ("flow", "repair-conflict", "repair-failing", "repair-review"): state_file.write_text("resolved")
    if mode == "resolution-fails":
        payload = {"data":None, "errors":[{"message":"fixture resolution refused"}]}
    else:
        payload = {"data":{"resolveReviewThread":{"thread":{"id":"OTHER" if mode == "wrong-resolution" else "T1", "isResolved":mode != "resolution-open"}}}}
elif "enablePullRequestAutoMerge" in query:
    payload = {"data":{"enablePullRequestAutoMerge":{"pullRequest":{"autoMergeRequest":{"enabledAt":"fixture-time"}}}}}
elif query:
    payload = {"errors":[{"message":"unexpected mutation"}]}
else:
    if a[-1].endswith("/update-branch"):
        state_file.write_text("updated")
    if mode == "transport": sys.exit(7)
    code = {"race":"409", "unexpected":"500", "method":"405", "forbidden":"403", "invalid":"422"}.get(mode, "200")
    if mode == "method" and body.get("merge_method") == "merge": code = "200"
    payload = {"merged": code == "200" and mode != "false-success"}
Path(a[a.index("-o")+1]).write_text(json.dumps(payload))
print(code, end="")
''',
            }.items():
                path = root / name
                path.write_text(body)
                path.chmod(0o755)
            log = root / "calls.jsonl"
            env = {**os.environ, "PATH": str(root) + os.pathsep + os.environ["PATH"],
                   "MERGE_FIXTURE_MODE": mode, "MERGE_FIXTURE_LOG": str(log)}
            results = []
            all_flags = (extra_args, *followups)
            modes = (mode, *followup_modes) if followup_modes else (mode,) * len(all_flags)
            self.assertEqual(len(modes), len(all_flags))
            for current_mode, flags in zip(modes, all_flags):
                result = subprocess.run(["bash", str(getattr(self, 'script', SCRIPT)), "--repo", "fixture/repo", "--pr", "1", *flags],
                                        env={**env, 'MERGE_FIXTURE_MODE': current_mode},
                                        capture_output=True, text=True, timeout=20)
                results.append(result)

            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return (results if followups else result), calls

    def test_blocked_resolve_merge_flow_exposes_usable_thread_id(self):
        results, calls = self.run_helper("flow", followups=(
            ["--resolve-thread", "T1", "--verified-head", HEAD], []))
        self.assertEqual([r.returncode for r in results], [4, 0, 0])
        self.assertIn("threads=T1", results[0].stdout)
        self.assertIn("RESOLVED", results[1].stdout)
        self.assertIn("MERGED", results[2].stdout)

    def test_terminal_states_are_idempotent(self):
        result, calls = self.run_helper("merged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("via preexisting", result.stdout)
        self.assertEqual(len(calls), 1)
        result, calls = self.run_helper("closed")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=closed", result.stdout)
        self.assertEqual(len(calls), 1)

    def test_behind_timeout_does_not_arm_for_future_commits(self):
        result, calls = self.run_helper("behind")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=behind", result.stdout)
        self.assertIn("automerge=unavailable", result.stdout)
        self.assertFalse(any('enablePullRequestAutoMerge' in c.get('query', '') for c in calls))

    def test_conflict_does_not_arm_for_future_commits(self):
        result, calls = self.run_helper("conflict")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=conflict", result.stdout)
        self.assertIn("automerge=unavailable", result.stdout)
        self.assertEqual(len(calls), 1)

    def test_pending_rollup_arms_automerge_instead_of_merging(self):
        # Seen in practice: an org-admin token merged over a PENDING rollup via the
        # ruleset's implicit "always" bypass. No merge PUT may be sent. A null rollup
        # (checks not registered yet) counts as pending even when GitHub says CLEAN.
        for mode in ("pending", "expected", "no-checks"):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("reason=checks_pending", result.stdout)
                self.assertIn("automerge=armed", result.stdout)
                self.assertFalse(any("merge_method" in c for c in calls))
                self.assertIn("enablePullRequestAutoMerge", calls[-1]["query"])

    def test_not_clean_merge_state_arms_automerge_instead_of_merging(self):
        for state in ("blocked", "unstable", "has_hooks", "unknown"):
            with self.subTest(state=state):
                result, calls = self.run_helper("state-" + state)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("reason=not_clean", result.stdout)
                self.assertIn("mergeStateStatus=" + state.upper(), result.stdout)
                self.assertIn("automerge=armed", result.stdout)
                self.assertFalse(any("merge_method" in c for c in calls))

    def test_not_clean_with_no_auto_neither_merges_nor_arms(self):
        result, calls = self.run_helper("state-blocked", ["--no-auto"])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=not_clean", result.stdout)
        self.assertIn("automerge=unavailable", result.stdout)
        self.assertEqual(len(calls), 1)

    def test_dirty_reports_conflict_before_pending_checks(self):
        result, calls = self.run_helper("pending-dirty")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=conflict", result.stdout)
        self.assertIn("automerge=unavailable", result.stdout)
        self.assertEqual(len(calls), 1)

    def test_clean_with_success_merges_directly(self):
        result, calls = self.run_helper("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED fixture/repo#1 via squash", result.stdout)
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_required_review_is_reported_as_branch_protection(self):
        result, calls = self.run_helper("review-required")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=branch_protection", result.stdout)
        self.assertIn("reviewDecision=REVIEW_REQUIRED", result.stdout)
        self.assertIn("automerge=armed", result.stdout)
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_behind_sync_never_merges_the_fresh_head_in_the_same_run(self):
        result, calls = self.run_helper("behind-then-fresh")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=checks_pending", result.stdout)
        self.assertIn("rollup=NONE", result.stdout)
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_success_pins_head_and_requires_merged_true(self):
        result, calls = self.run_helper("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED", result.stdout)
        self.assertEqual(calls[-1], {"merge_method": "squash", "sha": HEAD})

    def test_reply_marker_cannot_resolve_thread_or_arm_merge(self):
        result, calls = self.run_helper("marker")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=unanswered_threads", result.stdout)
        self.assertEqual(len(calls), 1)

    def test_incomplete_snapshot_cannot_merge(self):
        for mode, code in (("truncated", 4), ("null", 3)):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(len(calls), 1)

    def test_changed_head_never_retries_or_arms_automerge(self):
        result, calls = self.run_helper("race")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=head_changed", result.stdout)
        self.assertEqual(len(calls), 2)

    def test_unknown_outcomes_stop_without_retry(self):
        for mode in ("transport", "unexpected", "false-success"):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertNotIn("MERGED", result.stdout)
                self.assertEqual(len(calls), 2)

    def test_permanent_rejections_are_classified_without_retry_or_automerge(self):
        for mode, reason in (("forbidden", "permission_denied"), ("invalid", "validation_failed")):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("reason=" + reason, result.stdout)
                self.assertIn("automerge=unavailable", result.stdout)
                self.assertEqual(len(calls), 2)

    def test_method_fallback_preserves_checked_head(self):
        result, calls = self.run_helper("method")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c["sha"] for c in calls[1:]], [HEAD, HEAD])

    def test_automerge_checks_head_when_armed(self):
        result, calls = self.run_helper("failing")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("automerge=armed", result.stdout)
        self.assertIn("expectedHeadOid:$sha", calls[-1]["query"])
        self.assertEqual(calls[-1]["variables"]["sha"], HEAD)

    def test_no_auto_arms_nothing_and_still_merges_a_clean_armed_pr(self):
        result, calls = self.run_helper("failing", ["--no-auto"])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn("reason=failing_checks", result.stdout)
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))
        # "leave auto-merge as set": the armed request is left alone and no longer
        # refuses the direct merge of a PR that is already CLEAN.
        result, calls = self.run_helper("already-auto", ["--no-auto"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED fixture/repo#1 via squash", result.stdout)
        self.assertEqual(calls[-1], {"merge_method": "squash", "sha": HEAD})
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_existing_automerge_is_reported_never_refused_or_newly_armed(self):
        # A PR someone else already armed reports its real blocker plus the armed
        # request. Babysitter never stops to make the operator disable it first.
        result, calls = self.run_helper("preexisting-unresolved")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=unanswered_threads", result.stdout)
        self.assertIn("automerge=preexisting", result.stdout)
        self.assertEqual(len(calls), 1)
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))
        result, calls = self.run_helper("preexisting-failing")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=failing_checks", result.stdout)
        self.assertIn("automerge=preexisting", result.stdout)
        self.assertEqual(len(calls), 2)
        # A CLEAN armed PR is merged here rather than left to GitHub's queue.
        result, calls = self.run_helper("already-auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED fixture/repo#1 via squash", result.stdout)

    def test_merge_observed_during_refresh_reports_truth_and_original_blocker(self):
        result, calls = self.run_helper("merged-after-block")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED", result.stdout)
        self.assertIn("prior_blocker=failing_checks", result.stdout)
        self.assertEqual(len(calls), 2)
        result, calls = self.run_helper("closed-after-block")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=closed", result.stdout)
        self.assertIn("prior_blocker=failing_checks", result.stdout)
        self.assertEqual(len(calls), 2)

    def test_arm_always_requires_complete_resolved_threads_even_without_branch_rules(self):
        for mode, reason in (("marker", "unanswered_threads"), ("conflict-threads", "conflict"),
                             ("threads-failing", "unanswered_threads"),
                             ("truncated", "incomplete_review_state")):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, ["--arm-always"])
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("reason=" + reason, result.stdout)
                self.assertIn("automerge=unavailable", result.stdout)
                self.assertFalse(any("merge_method" in c for c in calls))
                self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_arm_always_can_arm_conflicts_with_no_thread_work(self):
        result, calls = self.run_helper("conflict", ["--arm-always"])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("automerge=armed", result.stdout)
        self.assertEqual(calls[-1]["variables"]["sha"], HEAD)
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_arm_always_rechecks_threads_immediately_before_arming(self):
        result, calls = self.run_helper("threads-before-arm", ["--arm-always"])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("automerge=unavailable", result.stdout)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_arm_always_reports_threads_behind_existing_automerge(self):
        result, calls = self.run_helper("preexisting-unresolved", ["--arm-always"])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=unanswered_threads", result.stdout)
        self.assertIn("automerge=preexisting", result.stdout)
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_arm_always_keeps_terminal_guards_and_direct_merge_gate(self):
        result, calls = self.run_helper("race", ["--arm-always"])
        self.assertIn("reason=head_changed", result.stdout)
        self.assertIn("automerge=unavailable", result.stdout)
        result, calls = self.run_helper("success", ["--arm-always"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED", result.stdout)
        for flags in (["--arm-always", "--no-auto"], ["--arm-always", "--resolve-thread", "T1", "--verified-head", HEAD]):
            with self.subTest(flags=flags):
                result = self.run_helper("success", flags)[0]
                self.assertEqual(result.returncode, 2)

    def test_resolution_works_after_quick_pass_armed_automerge(self):
        result, calls = self.run_helper("preexisting-unresolved", ["--resolve-thread", "T1", "--verified-head", HEAD])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESOLVED", result.stdout)
        self.assertIn("resolveReviewThread", calls[-1]["query"])
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_explicit_resolution_checks_owner_and_head_without_merging(self):
        args = ["--resolve-thread", "T1", "--verified-head", HEAD]
        result, calls = self.run_helper("resolve", args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESOLVED", result.stdout)
        self.assertEqual(len(calls), 3)
        self.assertIn("resolveReviewThread", calls[-1]["query"])
        result, calls = self.run_helper("foreign", args)
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertIn("reason=thread_not_on_pr", result.stdout)
        result, calls = self.run_helper("resolve", ["--resolve-thread", "T1", "--verified-head", "b" * 40])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertIn("reason=verified_head_changed", result.stdout)

    def test_expected_head_merges_only_that_head_and_pins_it_server_side(self):
        result, calls = self.run_helper("success", ["--no-auto", "--expected-head", HEAD])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MERGED fixture/repo#1 via squash", result.stdout)
        self.assertEqual(len(calls), 3)  # gate read, pre-merge reread, merge PUT
        self.assertTrue(all(c["query"].startswith("query") for c in calls[:2]))
        self.assertEqual(calls[-1], {"merge_method": "squash", "sha": HEAD})

    def test_land_stage_race_author_push_after_review_is_not_merged(self):
        # Review approved head A and the coordinator reread A; the author pushed B before
        # the helper's own read. Without the pin the helper would merge B.
        unpinned, calls = self.run_helper("author-pushed", ["--no-auto"])
        self.assertEqual(unpinned.returncode, 0, unpinned.stderr)
        self.assertEqual(calls[-1], {"merge_method": "squash", "sha": "b" * 40})
        result, calls = self.run_helper("author-pushed", ["--no-auto", "--expected-head", HEAD])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=expected_head_mismatch", result.stdout)
        self.assertIn("b" * 40, result.stdout)
        self.assertEqual(len(calls), 1)
        self.assertFalse(any("merge_method" in c or "enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_expected_head_mismatch_refuses_before_any_mutation(self):
        other = "b" * 40
        for mode, flags in (("success", ["--no-auto"]), ("success", []), ("pending", []),
                            ("conflict", ["--arm-always"]), ("behind", [])):
            with self.subTest(mode=mode, flags=flags):
                result, calls = self.run_helper(mode, [*flags, "--expected-head", other])
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("reason=expected_head_mismatch", result.stdout)
                self.assertIn("automerge=unavailable", result.stdout)
                self.assertEqual(len(calls), 1)
                self.assertTrue(calls[0]["query"].startswith("query"))

    def test_expected_head_moving_before_the_merge_is_refused(self):
        result, calls = self.run_helper("moves-before-merge", ["--no-auto", "--expected-head", HEAD])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=expected_head_mismatch", result.stdout)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_pre_merge_reread_reapplies_every_gate_at_the_same_head(self):
        """RC2-babysitter-tuneup-01: a fresh failure or review blocker stops the merge."""
        for mode, reason in (("fails-before-merge", "reason=failing_checks"),
                             ("blocked-before-merge", "reason=branch_protection")):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, ["--no-auto", "--expected-head", HEAD])
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn(reason, result.stdout)
                self.assertFalse(any("merge_method" in c for c in calls))

    def test_expected_head_never_updates_a_behind_branch(self):
        result, calls = self.run_helper("behind", ["--expected-head", HEAD])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=behind", result.stdout)
        self.assertEqual(len(calls), 1)  # no update-branch PUT, no arming

    def test_update_only_pins_the_update_and_never_lands_even_a_green_new_head(self):
        result, calls = self.run_helper('behind-then-green', ['--update-only', '--expected-head', HEAD])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('UPDATED fixture/repo#1', result.stdout)
        self.assertIn('head=' + 'b' * 40, result.stdout)
        self.assertEqual([c for c in calls if not c.get('query')], [{'expected_head_sha': HEAD}])
        self.assertFalse(any('mutation' in c.get('query', '') for c in calls))

    def test_update_only_refuses_wrong_head_conflict_and_incompatible_modes(self):
        for mode, flags in (
                ('author-pushed', ['--expected-head', HEAD]),
                ('conflict', ['--expected-head', HEAD]),
                ('behind', []), ('behind', ['--expected-head', HEAD, '--arm-always']),
                ('behind', ['--expected-head', HEAD, '--method', 'merge']),
                ('behind', ['--expected-head', HEAD, '--resolve-thread', 'T1', '--verified-head', HEAD])):
            with self.subTest(mode=mode, flags=flags):
                result, calls = self.run_helper(mode, ['--update-only', *flags])
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(c.get('query', '').startswith('query') for c in calls))

    def test_update_acceptance_without_a_new_head_is_uncertain_and_never_lands(self):
        result, calls = self.run_helper('behind-then-same', ['--update-only', '--expected-head', HEAD])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn('reason=update_pending', result.stdout)
        self.assertIn('retain the reservation as uncertain', result.stdout)
        self.assertNotIn('UPDATED', result.stdout)
        self.assertEqual([c for c in calls if not c.get('query')], [{'expected_head_sha': HEAD}])
        self.assertFalse(any('mutation' in c.get('query', '') for c in calls))

    def test_expected_head_arms_automerge_only_at_that_head(self):
        result, calls = self.run_helper("pending", ["--expected-head", HEAD])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("automerge=armed", result.stdout)
        self.assertEqual(calls[-1]["variables"]["sha"], HEAD)

    def test_expected_head_argument_validation(self):
        for flags in (["--expected-head", "abc"], ["--expected-head", HEAD.upper()],
                      ["--expected-head", HEAD, "--resolve-thread", "T1", "--verified-head", HEAD]):
            with self.subTest(flags=flags):
                result, calls = self.run_helper("success", flags)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])

    def reply_file(self, body):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "reply.md"
        path.write_bytes(body if isinstance(body, bytes) else body.encode())
        return str(path)

    def test_blockers_list_every_condition_from_one_state_read(self):
        for mode, flags, reason, blockers in (
            ("conflict-threads", [], "conflict", "conflict,unanswered_threads:1"),
            ("threads-failing", [], "unanswered_threads", "unanswered_threads:1,failing_checks"),
            ("behind-threads", ["--expected-head", HEAD], "behind", "behind,unanswered_threads:1"),
            ("behind", ["--expected-head", HEAD], "behind", "behind"),
        ):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, flags)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertEqual(result.stdout.count("\n"), 1, result.stdout)
                self.assertTrue(result.stdout.startswith(
                    f"BLOCKED fixture/repo#1 reason={reason} blockers={blockers} detail="), result.stdout)
                self.assertTrue(result.stdout.rstrip().endswith("automerge=unavailable"), result.stdout)
                self.assertEqual(len(calls), 1)
        # --arm-always cannot let a branch without resolution rules skip threads.
        result, calls = self.run_helper("conflict-threads", ["--arm-always"])
        self.assertIn("blockers=conflict,unanswered_threads:1 ", result.stdout)
        self.assertIn("automerge=unavailable", result.stdout)
        self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_every_blocked_line_carries_blockers(self):
        for mode, reason, blockers in (
            ("pending", "checks_pending", "checks_pending,not_clean"),
            ("state-blocked", "not_clean", "not_clean"),
            ("review-required", "branch_protection", "review_required,not_clean"),
            ("race", "head_changed", "head_changed"),
            ("closed", "closed", "closed"),
        ):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, ["--no-auto"])
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn(f"reason={reason} blockers={blockers} detail=", result.stdout)
        result, calls = self.run_helper("success", ["--no-auto", "--resolve-thread", "T1", "--verified-head", "b" * 40])
        self.assertIn("reason=verified_head_changed blockers=verified_head_changed detail=", result.stdout)

    def test_unstable_with_every_required_context_green_merges_the_pinned_head(self):
        for flags in ([], ["--no-auto", "--expected-head", HEAD]):
            with self.subTest(flags=flags):
                result, calls = self.run_helper("unstable-green", flags)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "MERGED fixture/repo#1 via squash merge_state=UNSTABLE\n")
                self.assertEqual(calls[-1], {"merge_method": "squash", "sha": HEAD})
                self.assertIn("isRequired(pullRequestNumber:$number)", calls[0]["query"])
                self.assertFalse(any("enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_unstable_without_verified_required_contexts_is_not_merged(self):
        for mode, reason, needle in (
            ("unstable-required-failing", "failing_checks", "required check(s) red at the head: build"),
            ("unstable-required-pending", "checks_pending", "required check(s) not finished: build"),
            ("unstable-status-expected", "checks_pending", "required check(s) not finished: ci/legacy"),
            ("unstable-page-incomplete", "checks_pending", "more than 100 status contexts"),
            ("unstable-zero-required", "not_clean", "no required contexts to verify"),
            ("unstable-threads", "unanswered_threads", "threads=T9"),
            ("unstable-review-required", "branch_protection", "reviewDecision=REVIEW_REQUIRED"),
        ):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, ["--no-auto"])
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn(f"reason={reason} blockers=", result.stdout)
                self.assertIn(needle, result.stdout)
                self.assertFalse(any("merge_method" in c for c in calls))
                self.assertEqual(len(calls), 1)

    def test_changes_requested_names_the_reviewers_and_marks_bots(self):
        result, calls = self.run_helper("bot-changes", ["--no-auto"])
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=branch_protection blockers=changes_requested,not_clean "
                      "changes_requested_by=coderabbitai[bot] detail=", result.stdout)
        self.assertIn("changes requested by coderabbitai[bot]", result.stdout)
        self.assertIn("not a missing human approval", result.stdout)
        self.assertNotIn("human review is outstanding", result.stdout)
        self.assertIn("latestReviews(first:50)", calls[0]["query"])
        result, calls = self.run_helper("human-changes", ["--no-auto"])
        self.assertIn("changes_requested_by=octo-reviewer detail=", result.stdout)
        self.assertIn("changes requested by octo-reviewer", result.stdout)
        self.assertNotIn("[bot]", result.stdout)

    def test_reply_is_posted_once_after_ownership_checks_and_before_resolving(self):
        body = "[babysitter] Fixed in the verified head.\n\nEvidence: `tests pass`.\n"
        args = ["--resolve-thread", "T1", "--verified-head", HEAD, "--reply-file", self.reply_file(body)]
        result, calls = self.run_helper("resolve", args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"RESOLVED fixture/repo#1 thread=T1 head={HEAD} replied=1\n")
        self.assertEqual(len(calls), 5)
        self.assertTrue(calls[0]["query"].startswith("query"))
        self.assertIn("node(id:", calls[1]["query"])
        self.assertIn("addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id, body:$body})", calls[2]["query"])
        self.assertEqual(calls[2]["variables"], {"id": "T1", "body": body})
        self.assertIn("node(id:", calls[3]["query"])  # the reply must not resolve a different head
        self.assertIn("resolveReviewThread", calls[4]["query"])
        # Without a reply file nothing is posted and the line is unchanged.
        result, calls = self.run_helper("resolve", args[:4])
        self.assertEqual(result.stdout, f"RESOLVED fixture/repo#1 thread=T1 head={HEAD}\n")
        self.assertFalse(any("addPullRequestReviewThreadReply" in c.get("query", "") for c in calls))

    def test_unmarked_reply_gets_the_babysitter_marker_once(self):
        # list-prs.sh ignores [babysitter] replies; an unmarked one would wake the watch and re-dispatch a fixer.
        args = ["--resolve-thread", "T1", "--verified-head", HEAD, "--reply-file", self.reply_file("Answered with evidence.\n")]
        result, calls = self.run_helper("resolve", args)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = next(c for c in calls if "addPullRequestReviewThreadReply" in c.get("query", ""))
        self.assertEqual(reply["variables"]["body"], "[babysitter] Answered with evidence.\n")

    def test_failed_reply_is_not_retried_and_leaves_the_thread_open(self):
        args = ["--resolve-thread", "T1", "--verified-head", HEAD, "--reply-file", self.reply_file("done\n")]
        result, calls = self.run_helper("reply-fails", args)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("thread not resolved", result.stderr)
        self.assertNotIn("RESOLVED", result.stdout)
        self.assertEqual(sum("addPullRequestReviewThreadReply" in c.get("query", "") for c in calls), 1)
        self.assertFalse(any("resolveReviewThread" in c.get("query", "") for c in calls))

    def test_reply_waits_for_thread_ownership_and_verified_head(self):
        reply = self.reply_file("done\n")
        for mode, head, reason in (("foreign", HEAD, "thread_not_on_pr"), ("resolve", "b" * 40, "verified_head_changed")):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, ["--resolve-thread", "T1", "--verified-head", head, "--reply-file", reply])
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertIn("reason=" + reason, result.stdout)
                self.assertFalse(any("addPullRequestReviewThreadReply" in c.get("query", "") for c in calls))

    def test_reply_file_is_validated_before_any_network_call(self):
        resolve = ["--resolve-thread", "T1", "--verified-head", HEAD]
        for name, flags in (
            ("empty", [*resolve, "--reply-file", self.reply_file("")]),
            ("whitespace", [*resolve, "--reply-file", self.reply_file(" \n\t\n")]),
            ("oversized", [*resolve, "--reply-file", self.reply_file(b"x" * 61441)]),
            ("missing", [*resolve, "--reply-file", "/nonexistent/reply.md"]),
            ("no-thread", ["--reply-file", self.reply_file("done\n")]),
        ):
            with self.subTest(name=name):
                result, calls = self.run_helper("resolve", flags)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(calls, [])
        result, calls = self.run_helper("resolve", [*resolve, "--reply-file", self.reply_file(b"x" * 61440)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("replied=1", result.stdout)

    def test_reply_and_resolve_work_with_automerge_armed(self):
        # The old automerge_already_enabled refusal must not come back in resolution mode.
        args = ["--resolve-thread", "T1", "--verified-head", HEAD, "--reply-file", self.reply_file("done\n")]
        result, calls = self.run_helper("preexisting-unresolved", args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESOLVED fixture/repo#1 thread=T1", result.stdout)
        self.assertIn("replied=1", result.stdout)
        self.assertNotIn("automerge_already_enabled", result.stdout + result.stderr)
        self.assertFalse(any("merge_method" in c or "enablePullRequestAutoMerge" in c.get("query", "") for c in calls))

    def test_head_change_after_reply_leaves_thread_open_without_reposting(self):
        args = ["--resolve-thread", "T1", "--verified-head", HEAD,
                "--reply-file", self.reply_file("Fixed with test evidence.\n")]
        result, calls = self.run_helper("moves-after-reply", args)
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("reason=verified_head_changed", result.stdout)
        self.assertIn("the reply was posted but thread not resolved", result.stdout)
        self.assertEqual(sum("addPullRequestReviewThreadReply" in c.get("query", "") for c in calls), 1)
        self.assertFalse(any("resolveReviewThread" in c.get("query", "") for c in calls))
        self.assertFalse(any("merge_method" in c for c in calls))

    def test_resolution_failure_keeps_exact_error_and_never_reports_success(self):
        args = ["--resolve-thread", "T1", "--verified-head", HEAD,
                "--reply-file", self.reply_file("Verified fix.\n")]
        for mode in ("resolution-fails", "resolution-open", "wrong-resolution"):
            with self.subTest(mode=mode):
                result, calls = self.run_helper(mode, args)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("thread resolution failed", result.stderr)
                self.assertIn("the reply was posted; do not post it again", result.stderr)
                if mode == "resolution-fails":
                    self.assertIn("fixture resolution refused", result.stderr)
                self.assertNotIn("RESOLVED", result.stdout)
                self.assertEqual(sum("addPullRequestReviewThreadReply" in c.get("query", "") for c in calls), 1)
                self.assertFalse(any("merge_method" in c for c in calls))

    def test_installed_repair_cycle_resolves_threads_and_rechecks_each_landing_gate(self):
        # Simulated host transitions exercise the shipped helper, not a live model.
        # A conflict repair and passing CI are separate from reply/resolution and approval.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'home'
            home.mkdir()
            prefix = root / 'prefix'
            proc = subprocess.run(
                [sys.executable, str(SCRIPT.parents[3] / 'scripts/install.py'), '--plugin', 'babysitter',
                 '--prefix', str(prefix), '--agents-root', str(root / 'agents')],
                env={**os.environ, 'HOME': str(home), 'XDG_STATE_HOME': str(root / 'state'),
                     'XDG_CONFIG_HOME': str(root / 'config')}, capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            version = Path(json.loads(proc.stdout)['data']['version_dir'])
            relocated = root / 'relocated'
            prefix.rename(relocated)
            self.script = relocated / version.relative_to(prefix) / 'scripts/merge-pr.sh'
            try:
                resolve = ['--resolve-thread', 'T1', '--verified-head', HEAD,
                           '--reply-file', self.reply_file('Fixed and verified at the current head.\n')]
                results, calls = self.run_helper('repair-conflict', ['--no-auto'], followups=(
                    ['--no-auto'], resolve, ['--no-auto'], ['--no-auto'],
                    ['--no-auto', '--expected-head', HEAD]), followup_modes=(
                        'repair-failing', 'repair-failing', 'repair-failing', 'repair-review', 'success'))
            finally:
                del self.script
            self.assertEqual([r.returncode for r in results], [4, 4, 0, 4, 4, 0],
                             '\n'.join(r.stdout + r.stderr for r in results))
            self.assertIn('blockers=conflict,unanswered_threads:1', results[0].stdout)
            self.assertIn('unanswered_threads:1,failing_checks', results[1].stdout)
            self.assertIn('RESOLVED', results[2].stdout)
            self.assertIn('replied=1', results[2].stdout)
            self.assertIn('reason=failing_checks', results[3].stdout)
            self.assertIn('changes_requested', results[4].stdout)
            self.assertIn('MERGED', results[5].stdout)
            mutations = [c for c in calls if not c.get('query', '').startswith('query')]
            self.assertEqual(len(mutations), 3)
            self.assertIn('addPullRequestReviewThreadReply', mutations[0]['query'])
            self.assertIn('resolveReviewThread', mutations[1]['query'])
            self.assertEqual(mutations[2], {'merge_method': 'squash', 'sha': HEAD})


if __name__ == "__main__":
    unittest.main()
