"""Immutable system symlinks (macOS /var, /tmp) versus swappable links, and JSON depth limits.

macOS keeps per-user temporary directories below /var, and /var is a root-owned link to
private/var in the root-owned, 0755 /. Every no-symlink-component check must accept such a
link and still refuse one a non-root user could swap. These tests build the macOS shape in a
temporary directory and report root ownership and modes for it through os.stat/os.lstat;
the checks themselves run unpatched and open the real link.
"""
import contextlib
import importlib.util
import json
import os
import random
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'bench' / 'v2' / 'tools'))
sys.path.insert(0, str(ROOT / 'bench' / 'container'))
sys.path.insert(0, str(ROOT))

from core.jobs.results import ResultError, parse_result  # noqa: E402
from core.jobs.store import (MAX_JSON_DEPTH, JobError, Store, _directory_fd, _regular,  # noqa: E402
                             json_depth, strict_load, trusted_link)
from shared import job_acceptance, job_coordinator, worker_registry  # noqa: E402
import learning_store  # noqa: E402
import skills  # noqa: E402
import driver  # noqa: E402

_spec = importlib.util.spec_from_file_location('align_under_test', ROOT / 'plugins/agent-tuneup/scripts/align.py')
align = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(align)

REAL_STAT, REAL_LSTAT = os.stat, os.lstat

# Scenario: (link uid, parent uid, parent mode, grandparent mode). Only the first is safe.
TRUSTED = (0, 0, 0o755, 0o755)
REJECTED = {
    'user-owned link': (os.getuid() or 1000, 0, 0o755, 0o755),
    'group-writable parent': (0, 0, 0o775, 0o755),
    'world-writable sticky parent': (0, 0, 0o1777, 0o755),
    'user-owned parent': (0, os.getuid() or 1000, 0o755, 0o755),
    'writable directory above the parent': (0, 0, 0o755, 0o1777),
}


def _with(info, uid=None, perm=None):
    values = list(info[:10])
    if uid is not None:
        values[4] = uid
    if perm is not None:
        values[0] = stat.S_IFMT(info.st_mode) | perm
    return os.stat_result(values)


@contextlib.contextmanager
def macos_layout(scenario):
    """temp/system/var -> ../private/var, like macOS /var -> private/var.

    temp/system and every ancestor are reported as root-owned directories; the scenario
    decides the link owner, the parent's owner and mode, and the grandparent's mode."""
    link_uid, parent_uid, parent_mode, grandparent_mode = scenario
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        (base / 'private' / 'var' / 'spool' / 'u').mkdir(parents=True, mode=0o700)
        (base / 'system').mkdir()
        link = base / 'system' / 'var'
        link.symlink_to(Path('..') / 'private' / 'var')
        parent = link.parent
        dirs = {str(path): (0, 0o755) for path in parent.parents}
        dirs[str(parent.parent)] = (0, grandparent_mode)
        dirs[str(parent)] = (parent_uid, parent_mode)

        def fake_stat(path, *, dir_fd=None, follow_symlinks=True):
            info = REAL_STAT(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            if dir_fd is not None or isinstance(path, int):
                return info
            key = os.path.abspath(os.fspath(path))
            if key == str(link) and not follow_symlinks:
                return _with(info, uid=link_uid)
            if key in dirs:
                uid, perm = dirs[key]
                return _with(info, uid=uid, perm=perm)
            return info

        def fake_lstat(path, *, dir_fd=None):
            return fake_stat(path, dir_fd=dir_fd, follow_symlinks=False)

        with mock.patch.object(os, 'stat', fake_stat), mock.patch.object(os, 'lstat', fake_lstat):
            yield base, link


class TrustedLinkRuleTests(unittest.TestCase):
    def test_root_link_in_root_0755_parent_is_trusted_and_every_swappable_link_is_not(self):
        with macos_layout(TRUSTED) as (_base, link):
            self.assertTrue(trusted_link(link))
            self.assertFalse(trusted_link(link.parent), 'a directory is not a link')
            self.assertFalse(trusted_link(link.parent / '..' / 'system' / 'var'), 'parent traversal is refused')
        for label, scenario in REJECTED.items():
            with self.subTest(scenario=label), macos_layout(scenario) as (_base, link):
                self.assertFalse(trusted_link(link))

    @unittest.skipIf(os.getuid() == 0, 'needs a non-root owner for the user-controlled directory')
    def test_root_owned_link_below_a_user_controlled_directory_is_refused(self):
        with macos_layout(TRUSTED) as (_base, link):
            inner = link / 'spool' / 'u' / 'inner'
            inner.symlink_to(link / 'spool')
            real_lstat = os.lstat
            with mock.patch.object(os, 'lstat', lambda p, **kw: _with(real_lstat(p, **kw), uid=0)):
                self.assertFalse(trusted_link(inner))
                with self.assertRaisesRegex(JobError, 'symlink in job state path: .*inner'):
                    Store(inner / 'state', 'job-1').locked()


class CheckSiteTests(unittest.TestCase):
    """Each no-symlink-component check accepts the trusted layout and refuses the rest."""

    def assert_rule(self, allowed, refused, errors):
        with macos_layout(TRUSTED) as (base, link):
            allowed(base, link)
        for label, scenario in REJECTED.items():
            with self.subTest(scenario=label), macos_layout(scenario) as (base, link):
                with self.assertRaises(errors):
                    refused(base, link)

    def test_job_store_lock_and_descriptor_walk(self):
        def run(_base, link):
            fd = Store(link / 'spool' / 'u' / 'state', 'job-1').locked()
            os.close(fd)
            return True

        def allowed(base, link):
            self.assertTrue(run(base, link))
            self.assertTrue((base / 'private/var/spool/u/state/job-1/job.lock').is_file())
            os.close(_directory_fd(link / 'spool' / 'u'))
        self.assert_rule(allowed, run, JobError)

        def refused_walk(_base, link):
            os.close(_directory_fd(link / 'spool' / 'u'))
        for label, scenario in REJECTED.items():
            with self.subTest(walk=label), macos_layout(scenario) as (base, link):
                with self.assertRaises(OSError):
                    refused_walk(base, link)

    def test_worker_artifact_read_through_the_job_directory(self):
        def run(_base, link):
            job_dir = link / 'spool' / 'u' / 'job'
            (job_dir / 'artifacts' / 'tasks' / 't1').mkdir(parents=True)
            data = b'{"x":1}'
            (job_dir / 'artifacts' / 'tasks' / 't1' / 'a.json').write_bytes(data)
            return _regular(job_dir / 'artifacts' / 'tasks' / 't1' / 'a.json')

        self.assert_rule(lambda base, link: self.assertEqual(run(base, link), b'{"x":1}'), run, OSError)

    def test_registry_path_walk(self):
        def run(_base, link):
            root = link / 'spool' / 'u' / 'agents'
            worker_registry.ensure_no_symlink_path(root / 'imps' / 'worker.md', root)

        self.assert_rule(run, run, worker_registry.RegistryError)

    def test_pin_probe_path(self):
        def run(_base, link):
            probe = job_coordinator._write_probe({'job_id': 'j'}, link / 'spool' / 'u' / 'state')
            self.assertTrue(probe.is_file())
            probe.unlink()

        # The descriptor walk that creates the root refuses the link before the path check does.
        self.assert_rule(run, run, (JobError, OSError))

    def test_reviewed_document_path(self):
        def run(base, link):
            (base / 'private/var/spool/u/doc.md').write_bytes(b'doc')
            store = types.SimpleNamespace(path=base / 'elsewhere')
            job = {'policy': {'max_artifact_bytes': 1024}}
            return job_acceptance.reviewed_document_bytes(store, job, str(link / 'spool' / 'u' / 'doc.md'))

        self.assert_rule(lambda base, link: self.assertEqual(run(base, link), b'doc'), run,
                         job_acceptance.AcceptanceError)

    def test_learning_store_descriptor_walk(self):
        def run(_base, link):
            with learning_store.directory(link / 'spool' / 'u' / 'learn', create=True) as fd:
                self.assertTrue(stat.S_ISDIR(os.fstat(fd).st_mode))

        self.assert_rule(run, run, OSError)

    def test_skill_adapter_path(self):
        def run(_base, link):
            return skills.safe_path(link / 'spool' / 'u' / 'skills')

        self.assert_rule(lambda base, link: self.assertEqual(run(base, link), link / 'spool/u/skills'), run,
                         ValueError)

    def test_agent_tuneup_path_and_parent_walk(self):
        def run(_base, link):
            target = align.checked_path(str(link / 'spool' / 'u' / 'settings.json'))
            os.close(align.open_parent(target))

        def refused_walk(_base, link):
            os.close(align.open_parent(link / 'spool' / 'u' / 'settings.json'))
        self.assert_rule(run, run, ValueError)
        self.assert_rule(run, refused_walk, OSError)



class PrefixSpellingTests(unittest.TestCase):
    """macOS CI: a prefix claimed as /var/... must match the same directory spelled /private/var/..."""

    def test_claim_and_ownership_agree_across_symlinked_spellings(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real = base / 'private' / 'prefix'
            real.mkdir(parents=True)
            link = base / 'var'
            link.symlink_to(base / 'private')
            root = base / 'registry'
            worker_registry._claim_installation_locked(root, 'id-1', link / 'prefix')
            worker_registry.assert_owned_locator(root, 'id-1', real)
            worker_registry.assert_owned_locator(root, 'id-1', link / 'prefix')
            other = base / 'other'
            other.mkdir()
            with self.assertRaises(worker_registry.RegistryError):
                worker_registry.assert_owned_locator(root, 'id-1', other)

class JsonDepthTests(unittest.TestCase):
    """An explicit nesting limit, independent of the interpreter's recursion behaviour."""

    def nested(self, depth):
        return '[' * depth + ']' * depth

    def test_strict_load_uses_parsed_containers_instead_of_rescanning_evidence_strings(self):
        value = {'evidence': ['quoted \\" { [ ] } ' * 10000, {'nested': [[]]}]}
        raw = json.dumps(value)
        with mock.patch('core.jobs.store.json_depth', side_effect=AssertionError('second text scan')):
            self.assertEqual(strict_load(raw), value)

    def test_decoded_depth_matches_text_depth_for_mixed_containers_and_escaped_strings(self):
        rng = random.Random(91)
        scalars = [None, True, False, 0, -2.5, '', 'quotes " and \\ and [{]}', '\u96ea\U0001f600']
        for _ in range(250):
            value = rng.choice(scalars)
            for level in range(rng.randrange(40)):
                value = rng.choice(([value, [], {}], {f'level{level}':value, 'quoted { key':rng.choice(scalars)}))
            raw = json.dumps(value, ensure_ascii=rng.choice([True, False]))
            depth = json_depth(raw)
            with self.subTest(depth=depth), mock.patch('core.jobs.store.MAX_JSON_DEPTH', depth):
                self.assertEqual(strict_load(raw), value)
            if depth:
                with self.subTest(rejected_depth=depth), mock.patch('core.jobs.store.MAX_JSON_DEPTH', depth - 1):
                    with self.assertRaisesRegex(JobError, 'nesting exceeds maximum depth'):
                        strict_load(raw)

    def test_strict_load_limit_is_explicit_and_strings_cannot_hide_or_fake_depth(self):
        self.assertEqual(len(json.dumps(strict_load(self.nested(MAX_JSON_DEPTH)))), 2 * MAX_JSON_DEPTH)
        for text in (self.nested(MAX_JSON_DEPTH + 1), '{"a":' * 600 + '1' + '}' * 600, self.nested(100000)):
            with self.subTest(size=len(text)), self.assertRaisesRegex(JobError, 'invalid JSON'):
                strict_load(text)
        self.assertEqual(strict_load('["' + '[' * 5000 + '{\\"' + '"]'), ['[' * 5000 + '{"'])
        self.assertEqual(json_depth('["]]]\\\\", {"a": ["[[", "\\"{"]}]'), 3)

    def test_limit_holds_where_json_parses_deep_input_without_recursion_error(self):
        # Python 3.14 on some platforms parses 100000 levels; emulate that parser here.
        def deep_parse(text, **_kwargs):
            value = []
            for _ in range(text.count('[') - 1):
                value = [value]
            return value
        with mock.patch('core.jobs.store.json.loads', deep_parse), self.assertRaisesRegex(JobError, 'invalid JSON'):
            strict_load(self.nested(100000))

    def test_worker_result_and_bench_canary_share_the_limit(self):
        deep = '{"a":' + self.nested(MAX_JSON_DEPTH) + '}'
        with self.assertRaisesRegex(ResultError, 'invalid JSON'):
            parse_result(deep.encode(), {})
        self.assertEqual(driver.MAX_JSON_DEPTH, MAX_JSON_DEPTH)
        self.assertIsNone(driver.parse_canary_result(deep))
        self.assertEqual(driver.parse_canary_result('{"a":"' + '[' * 900 + '"}'), {'a': '[' * 900})
        self.assertIsNotNone(driver.parse_canary_result('{"a":' + self.nested(MAX_JSON_DEPTH - 1) + '}'))


if __name__ == '__main__':
    unittest.main()
