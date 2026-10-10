#!/usr/bin/env python3
"""Subprocess-level command-surface tests for offload_sidecar.py: the CLI
`status` subcommand and the MCP stdio JSON-RPC loop in `main()`.

Distinct from test_offload_sidecar.py, which loads the module in-process via
importlib and unit-tests its pure functions — this file spawns the script as
a real subprocess (`subprocess.run([sys.executable, ...])`) to exercise the
process boundary itself: argv parsing, stdin/stdout line framing, and the
sys.argv -> cmd_status()/handle_message() -> exit-code/stdout wiring, none
of which the in-process tests touch.

Every subprocess in this file is spawned with a minimal, explicit `env=`
(never inherited from the ambient environment) that neutralizes real
external effects: OLLAMA_HOST points at a loopback port nothing listens on
(so gather_status() fails fast with "connection refused" instead of hanging
or reaching a real LAN host), the three OLLAMA_*TIMEOUT knobs are pinned
small, AGY_BIN points at a path that can't exist (so shutil.which() fails
fast instead of finding a real `agy`), and AGY_QUOTA_STATE is redirected
into a tempdir so quota state never touches ~/.local/state/offload-sidecar.
See _subprocess_env() below — every subprocess.run call site in this file
goes through it.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_DIR = os.path.normpath(
    os.path.join(_HERE, "..", "plugins", "offload-sidecar")
)
_SCRIPT_PATH = os.path.join(_PLUGIN_DIR, "scripts", "offload_sidecar.py")
_MCP_JSON_PATH = os.path.join(_PLUGIN_DIR, ".mcp.json")
_PLUGIN_JSON_PATH = os.path.join(_PLUGIN_DIR, ".claude-plugin", "plugin.json")
_MARKETPLACE_JSON_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "..", ".claude-plugin", "marketplace.json")
)


def _subprocess_env(quota_dir, extra=None):
    """Minimal, explicit environment for a subprocess spawn — built from
    scratch (not a copy of os.environ) so nothing ambient (a real
    OLLAMA_HOST, AGY_BIN, etc. set in the maintainer's own shell) can leak
    into what the test actually exercises."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "OLLAMA_HOST": "http://127.0.0.1:1",
        "OLLAMA_STATUS_TIMEOUT": "1",
        "OLLAMA_TIMEOUT": "1",
        "OLLAMA_FAST_TIMEOUT": "1",
        "AGY_BIN": "/nonexistent/offload-sidecar-test-agy",
        "AGY_QUOTA_STATE": os.path.join(quota_dir, "quota.json"),
    }
    if extra:
        env.update(extra)
    return env


def _run_script(args, quota_dir, input_text=None, env_extra=None, cwd=None, timeout=15):
    return subprocess.run(
        [sys.executable, _SCRIPT_PATH] + args,
        input=input_text,
        capture_output=True,
        text=True,
        env=_subprocess_env(quota_dir, env_extra),
        cwd=cwd,
        timeout=timeout,
    )


class CliStatusSubcommandTest(unittest.TestCase):
    """Item 1: `python3 offload_sidecar.py status` as a real subprocess.
    Proves the sys.argv -> cmd_status() -> sys.exit() wiring, not
    gather_status()'s own logic (already covered in-process elsewhere)."""

    def test_status_exits_1_and_reports_unreachable_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_script(["status"], tmp)
        # OLLAMA_HOST is an unreachable loopback port under the pinned env,
        # so gather_status() reports the host down and all_ok is False —
        # cmd_status() must exit 1, not 0.
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIn("offload-sidecar status:", proc.stdout)
        self.assertIn("[deep tier]", proc.stdout)
        self.assertIn("reachable:         no", proc.stdout)


class McpStdioLoopTest(unittest.TestCase):
    """Item 2: the MCP stdio JSON-RPC loop in main(), spawned with no argv
    and fed line-delimited JSON on stdin."""

    def _rpc_lines(self, stdout_text):
        return [json.loads(line) for line in stdout_text.splitlines() if line.strip()]

    def test_initialize_ping_tools_list(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        ]
        stdin_text = "".join(json.dumps(m) + "\n" for m in messages)
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_script([], tmp, input_text=stdin_text)
        self.assertEqual(proc.returncode, 0)
        responses = self._rpc_lines(proc.stdout)
        self.assertEqual(len(responses), 3)

        init = responses[0]
        self.assertEqual(init["id"], 1)
        self.assertEqual(init["result"]["serverInfo"]["name"], "offload-sidecar")
        self.assertIn("protocolVersion", init["result"])

        ping = responses[1]
        self.assertEqual(ping["id"], 2)
        self.assertEqual(ping["result"], {})

        tools_list = responses[2]
        self.assertEqual(tools_list["id"], 3)
        tool_names = [t["name"] for t in tools_list["result"]["tools"]]
        self.assertEqual(tool_names, ["process_local_file"])

    def test_notification_gets_no_response(self):
        # notifications/initialized has no id — the loop must not emit a
        # response line for it. Bracket it with a ping so we can prove the
        # loop actually processed the notification line (rather than never
        # reading it) instead of just processing the ping alone.
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]
        stdin_text = "".join(json.dumps(m) + "\n" for m in messages)
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_script([], tmp, input_text=stdin_text)
        self.assertEqual(proc.returncode, 0)
        responses = self._rpc_lines(proc.stdout)
        # Exactly two responses (the two pings) — the notification produced
        # zero lines, not an empty/null line.
        self.assertEqual([r["id"] for r in responses], [1, 2])

    def test_malformed_json_line_then_recovery(self):
        stdin_text = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
            + "\n"
            + "{this is not valid json\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            + "\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_script([], tmp, input_text=stdin_text)
        self.assertEqual(proc.returncode, 0)
        responses = self._rpc_lines(proc.stdout)
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0], {"jsonrpc": "2.0", "id": 1, "result": {}})
        parse_err = responses[1]
        self.assertIsNone(parse_err["id"])
        self.assertEqual(parse_err["error"]["code"], -32700)
        self.assertEqual(parse_err["error"]["message"], "parse error")
        # The loop kept running after the malformed line: the ping sent
        # after it was still answered.
        self.assertEqual(responses[2], {"jsonrpc": "2.0", "id": 2, "result": {}})

    def test_unknown_method_with_id_is_method_not_found(self):
        messages = [{"jsonrpc": "2.0", "id": 9, "method": "totally/bogus"}]
        stdin_text = "".join(json.dumps(m) + "\n" for m in messages)
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_script([], tmp, input_text=stdin_text)
        self.assertEqual(proc.returncode, 0)
        responses = self._rpc_lines(proc.stdout)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 9)
        self.assertEqual(responses[0]["error"]["code"], -32601)

    def test_unknown_method_without_id_is_silent(self):
        # No id at all -> treated as an unknown notification, same silence
        # as notifications/initialized. Bracket with pings, same reasoning
        # as test_notification_gets_no_response.
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "totally/bogus/notification"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]
        stdin_text = "".join(json.dumps(m) + "\n" for m in messages)
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_script([], tmp, input_text=stdin_text)
        self.assertEqual(proc.returncode, 0)
        responses = self._rpc_lines(proc.stdout)
        self.assertEqual([r["id"] for r in responses], [1, 2])


class McpToolsCallDeterministicOpTest(unittest.TestCase):
    """Item 3: one tools/call -> process_local_file round trip on a
    deterministic operation, with the path-containment guard handled
    explicitly (both input_path and output_path, and the subprocess's
    resolved root, must agree — see resolve_root()/_check_within_root()) so
    the call actually exercises the operation instead of silently returning
    an isError-shaped rejection."""

    def _load_operations(self):
        # In-process introspection only (no subprocess): find a
        # kind="deterministic" operation with no external-tool dependency,
        # by reading the OPERATIONS dict from the real module. This does
        # not execute main() or any network/subprocess code — the module's
        # top level only defines functions/dicts.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "offload_sidecar_intro", _SCRIPT_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.OPERATIONS

    def test_json_format_round_trip(self):
        operations = self._load_operations()
        op = operations["json_format"]
        self.assertEqual(op["kind"], "deterministic")

        with tempfile.TemporaryDirectory() as tmp:
            input_path = os.path.join(tmp, "in.json")
            output_path = os.path.join(tmp, "out.json")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write('{"b": 2, "a": 1}')

            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "process_local_file",
                    "arguments": {
                        "operation": "json_format",
                        "input_path": input_path,
                        "output_path": output_path,
                        "params": {"sort_keys": True},
                    },
                },
            }
            stdin_text = json.dumps(request) + "\n"
            # Both routes to resolve_root() pinned at the same tempdir: cwd
            # (the process's own cwd fallback) and SIDECAR_ROOT (the env
            # override resolve_root() reads first) — belt and suspenders so
            # this doesn't silently resolve to some other root.
            proc = _run_script(
                [],
                tmp,
                input_text=stdin_text,
                env_extra={"SIDECAR_ROOT": tmp},
                cwd=tmp,
            )

            self.assertEqual(proc.returncode, 0)
            lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            response = lines[0]["result"]

            # Not just "did I get a well-formed response" — isError must be
            # false, i.e. this was not the path-containment guard (or any
            # other error) firing silently underneath a structurally valid
            # envelope.
            self.assertFalse(response["isError"])
            payload = json.loads(response["content"][0]["text"])
            self.assertEqual(payload["status"], "success")
            # realpath on both sides: the server realpath()s output_path
            # internally (e.g. /tmp -> /private/tmp on macOS), and that
            # normalization is not itself under test here.
            self.assertEqual(
                os.path.realpath(payload["output_path"]), os.path.realpath(output_path)
            )

            # The transformed content is not in the RPC payload —
            # deterministic handlers write it to output_path on disk. Read
            # it separately (still inside the tempdir's lifetime) and
            # assert it's the actually-correct transform (sort_keys=True
            # reorders b,a -> a,b), not just "a file exists".
            with open(output_path, "r", encoding="utf-8") as f:
                written = json.load(f)
            self.assertEqual(written, {"a": 1, "b": 2})
            with open(output_path, "r", encoding="utf-8") as f:
                raw = f.read()
            self.assertEqual(list(json.loads(raw).keys()), ["a", "b"])


class OperationCoverageContractTest(unittest.TestCase):
    """Item 5: every operation in offload_sidecar.py's OPERATIONS dict must
    have at least one test exercising its success path — this is a meta-test
    that enumerates OPERATIONS and checks for coverage gaps so a newly-added
    operation without a corresponding test fails here first."""

    def _operations_from_script(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "offload_sidecar_ops", _SCRIPT_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.OPERATIONS

    def test_every_operation_family_has_known_coverage(self):
        # This test documents which operations have explicit test coverage
        # vs which need it. New operations must be added to the covered set.
        ops = self._operations_from_script()
        all_names = set(ops.keys()) | {"split_file", "merge_files"}

        # Operations with at least one success-path or validator test in
        # either test file. Kept honest: grep for the operation name in
        # the test files and confirm it's exercised, not just referenced.
        covered = {
            # Deterministic — tested via DeterministicOperationsTest or
            # HandleProcessLocalFileTest success roundtrips
            "dedupe_lines",
            "sort_lines",
            "filter_lines",
            "base64_decode",
            "base64_encode",
            "hash_file",
            "strip_ansi_codes",
            "normalize_log_timestamps",
            "extract_fields",
            "json_format",
            "plist_to_json",
            "sqlite_to_json",
            # Format conversions
            "jsonl_to_json",
            "json_to_jsonl",
            "csv_to_json",
            "json_to_csv",
            "toml_to_json",
            "xml_to_json",
            "html_to_text",
            # Line/file ops
            "slice_lines",
            "regex_replace",
            "text_stats",
            "json_digest",
            "json_to_yaml",  # has validator test + deterministic path
            "xlsx_extract",  # tested in NewDeterministicOpsTest
            "merge_files",
            "split_file",
            # LLM — validators tested in ValidatorsTest / HandleProcessLocalFileTest
            "extract_json",
            "convert_format",
            "clean_text",
            "yaml_to_json",
            "redact_secrets",
            "summarize",
            # Digest family — prompt/validator contract
            "triage_ci_log",
            "summarize_test_run",
            "triage_service_log",
            "digest_task_output",
            "digest_review_comments",
            "security_scan_digest",
            # Drafting family
            "draft_commit_message",
            "draft_pr_body",
            "changelog_from_commits",
            "html_extract",
            # Media family
            "describe_image",
            "verify_screenshot",
            "pdf_to_structured",
        }

        missing = all_names - covered
        self.assertEqual(
            missing,
            set(),
            f"Operations without known test coverage: {sorted(missing)}. "
            "Add tests and update the `covered` set in this test.",
        )

    def test_every_deterministic_operation_has_success_path_test(self):
        """Subset check: every deterministic operation must have a success-path
        test in test_offload_sidecar.py. This catches ops added to OPERATIONS
        whose validators are tested but whose actual transform path isn't."""
        ops = self._operations_from_script()
        det_ops = sorted(k for k, v in ops.items() if v["kind"] == "deterministic")

        # A bare mention or coverage-set entry is not a transform invocation.
        # Require a direct call in a test method that also asserts a result.
        called = set()
        for filename in ("test_offload_sidecar.py", "test_offload_sidecar_cli.py"):
            with open(os.path.join(_HERE, filename), encoding="utf-8") as stream:
                tree = ast.parse(stream.read())
            for method in ast.walk(tree):
                if not isinstance(method, ast.FunctionDef) or not method.name.startswith("test_"):
                    continue
                calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute)]
                if any(node.func.attr.startswith("assert") for node in calls):
                    called.update(node.func.attr for node in calls)
        # json_format is exercised through the real subprocess/MCP boundary.
        # Resolve the callable test, rather than accepting a name in source text.
        self.assertTrue(callable(getattr(McpToolsCallDeterministicOpTest, 'test_json_format_round_trip')))
        called.add(ops['json_format']['transform'].__name__)
        missing = [name for name in det_ops if ops[name]["transform"].__name__ not in called]
        self.assertEqual(missing, [], f"Deterministic transforms without asserted test calls: {missing}")



if __name__ == '__main__':
    unittest.main()
