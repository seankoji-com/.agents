#!/usr/bin/env python3
"""Source-only infrastructure bootstrap and isolated candidate self-test."""
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
if sys.version_info < (3, 10):
    sys.exit('agents requires Python 3.10+; run self-install with an explicit supported interpreter')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
if sys.argv[1:] == ['self-test']:
    from source_runtime.bootstrap import self_test
    print(json.dumps(self_test()))
else:
    from source_runtime.cli import main
    raise SystemExit(main(infrastructure_source=ROOT))
