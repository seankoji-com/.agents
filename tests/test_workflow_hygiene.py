"""Workflow scripts read event and step values from the environment.

A `${{ ... }}` expression inside a `run:` block is spliced into the shell source before
bash parses it, so a crafted tag, branch, or input becomes code. Values go through
`env:` and are quoted as ordinary variables instead.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = re.compile(r'^(\s*(?:- )?)run:\s*(.*)$')


def run_scripts(text: str):
    """Every `run:` script in a workflow: single-line, `|` literal, or `>` folded."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = RUN.match(line)
        if not match:
            continue
        indent, value = len(match.group(1)), match.group(2)  # the column of `run:` itself
        if not value.startswith(('|', '>')):
            yield value
            continue
        body = []
        for following in lines[i + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        yield '\n'.join(body)


class WorkflowHygieneTest(unittest.TestCase):
    def test_no_expressions_inside_run_scripts(self):
        offenders = [workflow.name for workflow in sorted((ROOT / '.github' / 'workflows').glob('*.yml'))
                     for script in run_scripts(workflow.read_text()) if '${{' in script]
        self.assertEqual(offenders, [])

    def test_every_run_form_is_scanned(self):
        sample = ('steps:\n  - run: echo ${{ a }}\n  - name: x\n    run: >\n      echo ${{ b }}\n'
                  '  - run: |\n      echo ${{ c }}\n    env:\n      X: ${{ d }}\n')
        self.assertEqual([s.strip() for s in run_scripts(sample)], ['echo ${{ a }}', 'echo ${{ b }}', 'echo ${{ c }}'])

if __name__ == '__main__':
    unittest.main()
