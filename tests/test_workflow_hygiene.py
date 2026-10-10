"""Workflow scripts read event and step values from the environment.

A `${{ ... }}` expression inside a `run:` block is spliced into the shell source before
bash parses it, so a crafted tag, branch, or input becomes code. Values go through
`env:` and are quoted as ordinary variables instead.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_BLOCK = re.compile(r'^(\s*)run: \|\n((?:\1  .*\n|\s*\n)*)', re.M)


class WorkflowHygieneTest(unittest.TestCase):
    def test_no_expressions_inside_run_blocks(self):
        offenders = []
        for workflow in sorted((ROOT / '.github' / 'workflows').glob('*.yml')):
            for match in RUN_BLOCK.finditer(workflow.read_text()):
                if '${{' in match.group(2):
                    offenders.append(workflow.name)
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
