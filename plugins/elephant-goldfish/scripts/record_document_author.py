#!/usr/bin/env python3
"""Record the coordinator lineage for the current elephant.md hash."""
import argparse
import json
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
    from shared.document_authors import append_author, locked_author_records
    from core.jobs.store import digest
    try:
        caps = json.loads(capabilities.read_text(encoding='utf-8'))
        with locked_author_records(document.parent) as (records, save):
            raw = document.read_bytes()
            updated = append_author(records, raw, caps, document_path=document)
            save(updated)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f'{parser.prog}: error: cannot record document author: {exc}\n')
    print(json.dumps({'document': str(document), 'sha256': digest(raw), 'authors': updated[digest(raw)]}))


if __name__ == '__main__':
    main()
