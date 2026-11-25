"""Issue-status decision table and in-memory board transitions. No network access."""
import importlib.util
from contextlib import redirect_stdout, redirect_stderr
from importlib.machinery import SourceFileLoader
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    loader = SourceFileLoader(Path(relative).stem, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = load('skills/ship/scripts/issue_status.py')


class FakeBoard:
    """In-memory stand-in for GitHub: mutations land here and nowhere else."""

    def __init__(self, projects=None, fields=None, issues=None, items=None,
                 operator='seankoji', prs=None, fail_items=None, fail_projects=None,
                 config=None):
        self.projects = [{'id': 'P1', 'number': 1, 'title': 'Board'}] \
            if projects is None else projects
        self.fields = fields if fields is not None else {'P1': [{
            'id': 'F1', 'name': 'Status', 'options': [
                {'id': 'O1', 'name': 'Backlog'},
                {'id': 'O2', 'name': 'In Progress'},
                {'id': 'O3', 'name': 'In Review'},
                {'id': 'O4', 'name': 'Done'},
            ]}]}
        self.issues = issues if issues is not None else {
            1: {'id': 'I1', 'number': 1, 'assignees': []}}
        self.board = items if items is not None else {'P1': []}
        self.operator_login = operator
        self.prs = prs or {}
        self.fail_items = fail_items
        self.fail_projects = fail_projects
        self.config = config or {}
        self.calls = []

    def repo_projects(self, owner, name):
        if self.fail_projects:
            raise RuntimeError(self.fail_projects)
        return self.projects

    def project_fields(self, project_id):
        return self.fields[project_id]

    def issue(self, owner, name, number):
        if number not in self.issues:
            raise status.Gap(f'issue #{number} not found')
        return self.issues[number]

    def items(self, project_id):
        if self.fail_items:
            raise RuntimeError(self.fail_items)
        return self.board[project_id]

    def add_item(self, project_id, content_id):
        item = {'id': f'T{content_id}', 'number': self.issues[int(content_id[1:])]['number'],
                'status': None}
        self.board[project_id].append(item)
        return item['id']

    def set_status(self, project_id, item_id, field_id, option_id):
        names = {o['id']: o['name'] for o in self.fields[project_id][0]['options']}
        for item in self.board[project_id]:
            if item['id'] == item_id:
                item['status'] = names[option_id]
                return
        raise AssertionError(f'item {item_id} missing')

    def assign(self, owner, name, number, login):
        self.issues[number]['assignees'].append(login)

    def project_config(self, owner, name):
        return self.config

    def operator(self):
        return self.operator_login

    def closing_issues(self, owner, name, number):
        return self.prs[number]


def run(argv, board):
    output = io.StringIO()
    errors = io.StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = status.main(argv, client=board)
    return code, output.getvalue(), errors.getvalue()


class DecisionTable(unittest.TestCase):
    def test_forward_only_matrix(self):
        cases = {
            'start': {None: 'In Progress', 'Backlog': 'In Progress',
                      'In Progress': None, 'In Review': None, 'Done': None},
            'pr': {None: 'In Review', 'Backlog': 'In Review',
                   'In Progress': 'In Review', 'In Review': None, 'Done': None},
            'done': {None: 'Done', 'Backlog': 'Done', 'In Progress': 'Done',
                     'In Review': 'Done', 'Done': None},
        }
        for transition, expected in cases.items():
            for current, target in expected.items():
                with self.subTest(transition=transition, current=current):
                    self.assertEqual(status.decide(current, transition), target)

    def test_custom_names_keep_forward_only_order(self):
        names = {'start': 'In progress', 'pr': 'In review', 'done': 'Released'}
        self.assertEqual(status.decide(None, 'start', names), 'In progress')
        self.assertEqual(status.decide('In progress', 'pr', names), 'In review')
        self.assertEqual(status.decide('In review', 'done', names), 'Released')
        self.assertIsNone(status.decide('Released', 'done', names))

    def test_status_names_match_case_insensitively(self):
        fields = [{'id': 'F', 'name': 'status', 'options': [
            {'id': 'A', 'name': 'in progress'}, {'id': 'B', 'name': 'in review'},
            {'id': 'C', 'name': 'done'}]}]
        for transition in status.TRANSITIONS:
            field, option = status.status_option(fields, status.TRANSITIONS[transition])
            self.assertEqual(field['id'], 'F')
            self.assertEqual(option['name'].casefold(),
                             status.TRANSITIONS[transition].casefold())

    def test_project_selection_never_guesses(self):
        one = [{'id': 'P1', 'number': 1, 'title': 'One'}]
        two = one + [{'id': 'P2', 'number': 2, 'title': 'Two'}]
        self.assertEqual(status.choose_project(one), one[0])
        self.assertEqual(status.choose_project(two, 2)['id'], 'P2')
        for projects, number, message in (([], None, 'no linked project'),
                                          (two, None, 'ambiguous linked projects'),
                                          (one, 9, 'linked project #9 not found')):
            with self.subTest(projects=projects, number=number), \
                    self.assertRaises(status.Gap) as gap:
                status.choose_project(projects, number)
            self.assertIn(message, str(gap.exception))


class Transitions(unittest.TestCase):
    def test_start_assigns_once_and_adds_the_item(self):
        board = FakeBoard()
        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1'], board)
        self.assertEqual(code, 0)
        self.assertEqual(board.issues[1]['assignees'], ['seankoji'])
        self.assertEqual(board.board['P1'][0]['status'], 'In Progress')
        self.assertIn('In Progress', output)
        self.assertIn('assigned @seankoji', output)

        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1'], board)
        self.assertEqual(code, 0)
        self.assertEqual(board.issues[1]['assignees'], ['seankoji'])
        self.assertIn('skipped (already In Progress)', output)

    def test_existing_assignee_is_never_reassigned(self):
        board = FakeBoard(issues={1: {'id': 'I1', 'number': 1, 'assignees': ['someone']}})
        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1'], board)
        self.assertEqual(code, 0)
        self.assertEqual(board.issues[1]['assignees'], ['someone'])
        self.assertEqual(board.board['P1'][0]['status'], 'In Progress')
        self.assertNotIn('assigned @', output)

    def test_unverified_operator_leaves_assignment_but_moves_status(self):
        board = FakeBoard(operator=None)
        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1'], board)
        self.assertEqual(code, 0)
        self.assertEqual(board.issues[1]['assignees'], [])
        self.assertEqual(board.board['P1'][0]['status'], 'In Progress')
        self.assertIn('operator unverified', output)

    def test_done_is_not_regressed(self):
        board = FakeBoard(items={'P1': [{'id': 'T1', 'number': 1, 'status': 'Done'}]})
        commands = (
            ['start', '--repo', 'o/r', '--issue', '1'],
            ['pr', '--repo', 'o/r', '--issue', '1'],
            ['done', '--repo', 'o/r', '--issue', '1', '--verified', 'release v1'],
        )
        for argv in commands:
            with self.subTest(transition=argv[0]):
                code, output, _ = run(argv, board)
                self.assertEqual(code, 0)
                self.assertIn('skipped (already Done)', output)
        self.assertEqual(board.board['P1'][0]['status'], 'Done')

    def test_pr_moves_only_closing_issues(self):
        board = FakeBoard(
            issues={n: {'id': f'I{n}', 'number': n, 'assignees': ['seankoji']}
                    for n in (1, 2, 3)},
            items={'P1': [{'id': f'T{n}', 'number': n, 'status': 'Backlog'}
                          for n in (1, 2, 3)]},
            prs={9: [1, 2]})
        code, output, _ = run(['pr', '--repo', 'o/r', '--pr', '9'], board)
        self.assertEqual(code, 0)
        fixed = {item['number']: item['status'] for item in board.board['P1']}
        self.assertEqual(fixed, {1: 'In Review', 2: 'In Review', 3: 'Backlog'})
        self.assertEqual(output.count('In Review'), 2)

    def test_pr_without_closing_issues_is_untracked(self):
        board = FakeBoard(prs={9: []})
        code, output, _ = run(['pr', '--repo', 'o/r', '--pr', '9'], board)
        self.assertEqual(code, 0)
        self.assertIn('untracked (closes no issues)', output)
        self.assertEqual(board.board['P1'], [])

    def test_direct_publish_skips_in_review(self):
        board = FakeBoard()
        run(['start', '--repo', 'o/r', '--issue', '1'], board)
        self.assertEqual(board.board['P1'][0]['status'], 'In Progress')
        code, output, _ = run(['done', '--repo', 'o/r', '--issue', '1',
                               '--verified', 'https://example.test/deploy/1'], board)
        self.assertEqual(code, 0)
        self.assertEqual(board.board['P1'][0]['status'], 'Done')
        self.assertIn('verified https://example.test/deploy/1', output)
        self.assertNotIn('In Review', output)
        self.assertNotIn('In Review', [i['status'] for i in board.board['P1']])

    def test_done_requires_evidence(self):
        board = FakeBoard()
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as exited:
            status.main(['done', '--repo', 'o/r', '--issue', '1'], client=board)
        self.assertEqual(exited.exception.code, 2)
        self.assertIn('--verified', errors.getvalue())
        self.assertEqual(board.board['P1'], [])

    def test_dry_run_changes_nothing(self):
        board = FakeBoard()
        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1', '--dry-run'], board)
        self.assertEqual(code, 0)
        self.assertIn('In Progress (dry run)', output)
        self.assertEqual(board.issues[1]['assignees'], [])
        self.assertEqual(board.board['P1'], [])

    def test_repository_config_maps_real_option_names(self):
        board = FakeBoard(
            fields={'P1': [{'id': 'F1', 'name': 'Status', 'options': [
                {'id': 'O1', 'name': 'Todo'},
                {'id': 'O2', 'name': 'In progress'},
                {'id': 'O3', 'name': 'In review'},
                {'id': 'O4', 'name': 'Released'}]}]},
            issues={7: {'id': 'I7', 'number': 7, 'assignees': []}},
            prs={9: [7]},
            config={'start': 'In progress', 'pr': 'In review', 'done': 'Released'})
        run(['start', '--repo', 'o/r', '--issue', '7'], board)
        self.assertEqual(board.board['P1'][0]['status'], 'In progress')
        run(['pr', '--repo', 'o/r', '--pr', '9'], board)
        self.assertEqual(board.board['P1'][0]['status'], 'In review')
        code, output, _ = run(['done', '--repo', 'o/r', '--issue', '7',
                               '--verified', 'release 1'], board)
        self.assertEqual(code, 0)
        self.assertEqual(board.board['P1'][0]['status'], 'Released')
        self.assertIn('Released', output)
        self.assertNotIn('Done', output)

    def test_invalid_config_is_reported_without_failing(self):
        board = FakeBoard(config={'done': []})
        code, output, _ = run(['done', '--repo', 'o/r', '--issue', '1',
                               '--verified', 'v1'], board)
        self.assertEqual(code, 0)
        self.assertIn('invalid issue-status config', output)
        self.assertEqual(board.board['P1'], [])

    def test_missing_board_field_option_and_permission_are_reported(self):
        cases = (
            (FakeBoard(projects=[]), 'no linked project'),
            (FakeBoard(fields={'P1': [{'id': 'F', 'name': 'Priority', 'options': []}]}),
             'no single-select Status field'),
            (FakeBoard(fields={'P1': [{'id': 'F', 'name': 'Status',
                                      'options': [{'id': 'A', 'name': 'In Progress'}]}]}),
             'missing Status option Done'),
            (FakeBoard(fail_items='permission denied'), 'status update failed'),
            (FakeBoard(fail_projects='permission denied'), 'permission denied'),
        )
        for board, message in cases:
            with self.subTest(message=message):
                code, output, errors = run(
                    ['done', '--repo', 'o/r', '--issue', '1', '--verified', 'v1'], board)
                self.assertEqual(code, 0, errors)
                self.assertIn(message, output)

    def test_ambiguous_project_needs_explicit_number(self):
        board = FakeBoard(projects=[
            {'id': 'P1', 'number': 1, 'title': 'One'},
            {'id': 'P2', 'number': 2, 'title': 'Two'}])
        board.fields = {'P2': board.fields['P1']}
        board.board = {'P1': board.board['P1'], 'P2': []}
        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1'], board)
        self.assertEqual(code, 0)
        self.assertIn('ambiguous linked projects', output)
        code, output, _ = run(['start', '--repo', 'o/r', '--issue', '1', '--project', '2'],
                              board)
        self.assertEqual(code, 0)
        self.assertIn('In Progress', output)


class HelperSurface(unittest.TestCase):
    def test_help_runs_from_foreign_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(ROOT / 'skills/ship/scripts/issue_status.py'), '--help'],
                cwd=tmp, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--verified', result.stdout)
        self.assertIn('OWNER/REPO', result.stdout)


if __name__ == '__main__':
    unittest.main()
