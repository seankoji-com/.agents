#!/usr/bin/env python3
"""Launch packaged imps, warning when user snapshots differ from this package."""
import os
from pathlib import Path
import sys

import catalog
import install


def main():
    prefix = Path(os.environ.get('AGENTS_PREFIX', '~/.local/share/agents')).expanduser()
    current = prefix / 'imps' / 'current'
    if current.exists() or current.is_symlink():
        try:
            manifest = install.load_manifest(current / install.MANIFEST)
            matches = catalog.snapshot_matches_bundle(manifest, 'imps')
        except (OSError, ValueError, KeyError, install.InstallError):
            matches = False
        if not matches:
            print('imps: installed snapshot differs from this CLI package; '
                  'run agents start imps, then its doctor operation. '
                  'No installed files were changed.', file=sys.stderr)
    cli = catalog.ROOT / 'plugins' / 'imps' / 'cli.py'
    os.execv(sys.executable, [sys.executable, str(cli), *sys.argv[1:]])


if __name__ == '__main__':
    main()
