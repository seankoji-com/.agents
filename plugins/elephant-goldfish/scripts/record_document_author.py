#!/usr/bin/env python3
"""Record the coordinator lineage for the current elephant.md hash."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('document', help='path to elephant.md')
    parser.add_argument('--capabilities', required=True, help='fresh orchestrator_capabilities JSON')
    args = parser.parse_args()
    document = Path(args.document)
    capabilities = Path(args.capabilities)
    if document.is_symlink() or not document.is_file() or capabilities.is_symlink() or not capabilities.is_file():
        parser.error('document and capabilities must be regular files')
    root = next((p for p in Path(__file__).resolve().parents if (p / 'shared/document_authors.py').is_file()), None)
    if root is None:
        parser.error('shared document-author helpers are unavailable')
    sys.path.insert(0, str(root))
    from shared.document_authors import append_author
    from core.jobs.store import digest
    sidecar = document.parent / 'document-authors.json'
    if sidecar.is_symlink():
        parser.error('document author records may not be a symlink')
    records = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.exists() else {}
    if not isinstance(records, dict):
        parser.error('document author records must be an object')
    raw = document.read_bytes()
    updated = append_author(records, raw, json.loads(capabilities.read_text(encoding='utf-8')),
                            document_path=document)
    temporary = sidecar.with_name(sidecar.name + '.tmp')
    temporary.write_text(json.dumps(updated, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temporary, sidecar)
    print(json.dumps({'document': str(document), 'sha256': digest(raw), 'authors': updated[digest(raw)]}))


if __name__ == '__main__':
    main()
