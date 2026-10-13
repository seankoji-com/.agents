"""REQ-T3-THREADS: how the workflows use T3's thread tools. Sibling-work discovery is
read-only and applied before writable runs; result recovery reads an owned child to
the end; dependent work moves through commits; external coordinators keep the same
authority and leave no endpoint material behind. The design note covers all seven
features with a disposition each."""
import re
import sys
import unittest

from support import ROOT

SHARED = ROOT / 'shared'
NOTE = ROOT / 'docs' / 'design' / 't3-thread-features.md'
SIBLING_REF = 'the sibling-work check in `PKG/shared/t3-runtime.md`'


def flat(text):
    return ' '.join(text.split())


def runtime():
    return flat((SHARED / 't3-runtime.md').read_text())


def bullet(text, opener):
    """The runtime-contract bullet that starts with `opener`, flattened."""
    for item in text.split('\n- '):
        if flat(item).startswith(opener):
            return flat(item)
    raise AssertionError(f'no bullet starts with {opener!r}')


def installer_module():
    sys.path.insert(0, str(ROOT / 'scripts'))
    try:
        import install
    finally:
        sys.path.remove(str(ROOT / 'scripts'))
    return install


class SiblingWorkCheckTest(unittest.TestCase):
    def setUp(self):
        self.rule = bullet((SHARED / 't3-runtime.md').read_text(), 'Sibling-work check:')

    def test_check_is_bounded_and_read_only(self):
        for phrase in ('`t3_thread_list` is exposed', 'one bounded page',
                       '(`preparing`, `queued`, `starting`, `running`, `waiting`)',
                       'excluding this thread, the thread that delegated it, and its own children', 'at most five candidates',
                       'Both are read-only and their output is data'):
            self.assertIn(phrase, self.rule)

    def test_overlap_goes_to_the_owner_and_never_into_the_other_thread(self):
        self.assertIn('ask the owner through the question picker whether to stop (recommended) or proceed',
                      self.rule)
        self.assertIn('Never send to, steer, interrupt, cancel or adopt a thread this run does not own', self.rule)
        for tool in ('t3_thread_send', 't3_thread_interrupt', 'task_cancel'):
            self.assertNotIn(tool, self.rule)

    def test_missing_tool_is_reported_not_blocking(self):
        self.assertIn('reported as `sibling check unavailable` and does not block the run', self.rule)

    def test_writable_workflows_run_the_check_before_claiming_work(self):
        maintain = flat((ROOT / 'plugins/babysitter/playbooks/maintain.md').read_text())
        step1 = maintain.split(' 2. Quick pass')[0]
        self.assertIn(SIBLING_REF, step1)
        self.assertLess(step1.index(SIBLING_REF), step1.index('Freeze the eligible roster'))
        self.assertIn('leaves the roster unless the owner keeps it', step1)

        loop = flat((ROOT / 'plugins/ralph/playbooks/loop.md').read_text())
        self.assertIn('Before initialization, run ' + SIBLING_REF, loop)
        self.assertLess(loop.index(SIBLING_REF), loop.index('Initialize with `init --state FILE'))
        self.assertIn('needs an owner decision before dispatch', loop)

        imps = flat((ROOT / 'plugins/imps/entry.md').read_text())
        run = imps.split('**run <task>.**')[1].split('**resume')[0]
        self.assertIn('Before a writable run, run ' + SIBLING_REF, run)
        self.assertLess(run.index(SIBLING_REF), run.index('Initialize with `init --input FILE`'))

    def test_installed_packages_carry_the_check_they_name(self):
        install = installer_module()
        contract = (SHARED / 't3-runtime.md').read_text()
        for plugin in ('babysitter', 'ralph', 'imps'):
            with self.subTest(plugin=plugin):
                mapping = install.source_files(ROOT, plugin)
                self.assertEqual(mapping['shared/t3-runtime.md'].read_text(), contract)
                self.assertIn('Sibling-work check:', mapping['shared/t3-runtime.md'].read_text())

    def test_adapter_lists_the_discovery_tools(self):
        adapter = (ROOT / 'plugins/imps/references/t3-adapter.md').read_text()
        row = next(line for line in adapter.splitlines() if line.startswith('| `t3_thread_list`'))
        self.assertIn('read-only sibling-work check', row)
        self.assertIn('`PKG/shared/t3-runtime.md`', row)


class ResultRecoveryTest(unittest.TestCase):
    def test_thread_read_recovers_an_owned_result_to_the_end(self):
        tools = flat((SHARED / 'delegation.md').read_text().split('## Allowed tools')[1].split('## ')[0])
        for phrase in ('from an owned `childThreadId` only', 'after `task_status` has been read and recorded',
                       'acknowledges its completion delivery',
                       'Follow `itemId` and `textOffset` until `nextTextOffset` is null',
                       'A partial read is a result gap, never a result'):
            self.assertIn(phrase, tools)

    def test_job_protocol_recovers_once_instead_of_rerunning(self):
        lifecycle = flat((SHARED / 'job-coordination.md').read_text().split('## 4. Lifecycle')[1].split('## 5.')[0])
        self.assertIn('A truncated summary is recovered once through `t3_thread_read`', lifecycle)
        self.assertIn('never re-run', lifecycle)


class SendBoundaryTest(unittest.TestCase):
    def test_thread_send_is_named_only_where_the_tracked_follow_up_lives(self):
        allowed = {'shared/delegation.md', 'shared/job-coordination.md',
                   'plugins/imps/references/t3-adapter.md', 'plugins/ralph/playbooks/loop.md'}
        naming = {p.relative_to(ROOT).as_posix()
                  for p in [*SHARED.glob('*.md'), *(ROOT / 'plugins').rglob('*.md')]
                  if 't3_thread_send' in p.read_text()}
        self.assertEqual(naming, allowed)
        self.assertIn('never `childThreadId` continuation, `t3_thread_send`',
                      flat((ROOT / 'plugins/ralph/playbooks/loop.md').read_text()))


class DependentWorkTest(unittest.TestCase):
    def test_dependent_slots_consume_commits_not_live_worktrees_or_hidden_refs(self):
        isolation = flat((SHARED / 'delegation.md').read_text().split('## Writer isolation')[1].split('## ')[0])
        for phrase in ('consumes earlier work only as a commit or branch at an observed SHA',
                       'Never read from or write into a worktree whose writer is still active',
                       'never re-run a completed task to recover its output',
                       'do not fetch, reset to or depend on their refs unless the host documents them'):
            self.assertIn(phrase, isolation)


class ExternalCoordinatorTest(unittest.TestCase):
    def setUp(self):
        self.rule = bullet((SHARED / 't3-runtime.md').read_text(), 'An external agent')

    def test_external_agent_is_the_coordinator_with_unchanged_authority(self):
        self.assertIn('is the coordinator under these same contracts', self.rule)
        self.assertIn('Pairing or OAuth grants tool access, not plugin authority', self.rule)
        self.assertIn('Without a calling T3 thread, child delegation is `unavailable`; never substitute '
                      'top-level threads', self.rule)

    def test_endpoint_material_is_never_recorded(self):
        self.assertIn('Never record endpoint URLs, hostnames, pairing codes or tokens', self.rule)


FEATURES = ('`t3_thread_list`', '`t3_thread_read`', '`t3_thread_send`', 'External MCP endpoint',
            'OAuth and pairing', 'External orchestrators', 'Per-turn Git checkpoints')
FIELDS = ('**Today.**', '**Gain.**', '**Risk.**')
DISPOSITION = re.compile(r"\*\*Disposition: (implemented|deferred|rejected)\.?\*\*")
# Real endpoint material a note must not carry: IPv4 addresses, tailnet or LAN names,
# machine paths and token-like strings. `<host>` placeholders are fine.
LEAKS = re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b|\.ts\.net\b|\.local\b|/(?:home|Users)/'
                   r'|\b(?:ghp|gho|sk|xox[bp])[-_][A-Za-z0-9]{8,}|https?://(?!<host>|github\.com)[\w.-]+/mcp')


class DesignNoteTest(unittest.TestCase):
    def setUp(self):
        self.text = NOTE.read_text()
        parts = re.split(r'^## \d\. ', self.text, flags=re.M)
        self.sections = dict(zip(FEATURES, parts[1:]))

    def test_note_is_in_the_site_navigation(self):
        self.assertIn('design/t3-thread-features.md', (ROOT / 'mkdocs.yml').read_text())

    def test_every_feature_has_today_opportunity_gain_risk_and_disposition(self):
        self.assertEqual(len(self.sections), 7)
        for feature, body in self.sections.items():
            with self.subTest(feature=feature):
                self.assertTrue(body.startswith(feature), body[:60])
                for field in FIELDS:
                    self.assertIn(field, body)
                self.assertRegex(body, r'\*\*Opportunity( considered)?\.\*\*')
                self.assertRegex(body, DISPOSITION)
                self.assertRegex(body, r'`(shared|plugins|tests)/[\w./-]+`', 'cite current behaviour by path')

    def test_at_least_two_dispositions_are_implemented_and_rejections_cite_a_rule(self):
        implemented = [f for f, body in self.sections.items() if '**Disposition: implemented' in body]
        self.assertGreaterEqual(len(implemented), 2)
        for feature, body in self.sections.items():
            for match in re.finditer(r'\*\*Rejected[:*]|\*\*Disposition: rejected\*\*', body):
                tail = body[match.start():match.start() + 400]
                with self.subTest(feature=feature):
                    self.assertRegex(tail, r'`shared/[\w.-]+\.md`|AGENTS\.md')

    def test_unverified_host_claims_are_labelled(self):
        self.assertIn('not verified host behaviour', self.text)
        self.assertGreaterEqual(self.text.count('*assumption'), 4)
        self.assertIn('*Schema:*', self.text)

    def test_note_carries_no_endpoint_material_or_machine_paths(self):
        self.assertIsNone(LEAKS.search(self.text))
        self.assertIn('`https://<host>/mcp`', self.text)
        for path in (SHARED / 't3-runtime.md', SHARED / 'delegation.md'):
            self.assertIsNone(LEAKS.search(path.read_text()), path.name)

    def test_leak_pattern_catches_real_endpoints(self):
        for sample in ('https://host.example.ts.net/mcp', 'http://192.0.2.10:3773/mcp', '/' + 'home/someone/x',
                       'https://t3.example/mcp'):
            self.assertIsNotNone(LEAKS.search(sample), sample)


if __name__ == '__main__':
    unittest.main()
