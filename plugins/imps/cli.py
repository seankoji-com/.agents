#!/usr/bin/env python3
"""Run the core CLI for this plugin, wherever it is laid out: `core/` sits beside
this file in an installed version and two levels up in a source checkout. Every
argument is passed through; `--plugin-dir` defaults to this directory."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

args = sys.argv[1:]
if not any(arg == '--plugin-dir' or arg.startswith('--plugin-dir=') for arg in args):
    args += ['--plugin-dir', str(HERE)]
problems = []
for cli in (HERE / 'core' / 'cli.py', HERE.parent.parent / 'core' / 'cli.py'):
    if not cli.is_file():
        continue
    if not os.access(cli, os.R_OK):
        problems.append(f'{cli}: not readable')
        continue
    try:
        os.execv(sys.executable, [sys.executable, str(cli), *args])
    except OSError as exc:
        problems.append(f'{cli}: {exc}')
sys.exit('no usable core/cli.py beside ' + str(HERE) + ' or in its source checkout'
         + (': ' + '; '.join(problems) if problems else ''))
