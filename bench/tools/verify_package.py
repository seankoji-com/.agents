#!/usr/bin/env python3
"""Verify an installed imps package against its install manifest.

Prints the manifest's version, source commit, sha256 and file count, and fails if any
listed file is missing, differs, or if an unlisted file is present. Run it before and
after a benchmark to show the package did not change.

Usage: python3 bench/tools/verify_package.py VERSION_DIR
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def verify(version_dir: Path) -> dict:
    manifest_path = version_dir / 'install-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    listed = {f['path']: f['sha256'] for f in manifest['files']}
    problems = []
    for rel, digest in sorted(listed.items()):
        path = version_dir / rel
        if not path.is_file():
            problems.append(f'missing {rel}')
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f'changed {rel}')
    present = {p.relative_to(version_dir).as_posix() for p in version_dir.rglob('*') if p.is_file()}
    problems += [f'unlisted {rel}' for rel in sorted(present - set(listed) - {'install-manifest.json'})
                 if '__pycache__' not in rel]
    return {'ok': not problems, 'version': manifest.get('version'), 'source_commit': manifest.get('source_commit'),
            'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(), 'files': len(listed),
            'problems': problems}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    report = verify(Path(sys.argv[1]))
    print(json.dumps(report, indent=2))
    sys.exit(0 if report['ok'] else 1)
