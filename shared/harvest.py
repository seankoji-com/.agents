#!/usr/bin/env python3
"""Screen harvest drafts and bind destination receipts to exactly the approved text."""
from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from learning_store import Unavailable, digest, validate_entry


def screen(text, key, label, docs_domain=None):
    """Conservative identifier screen; human review still decides whether text is public."""
    allowed = {'github.com'}
    if docs_domain:
        if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', docs_domain.lower()):
            raise Unavailable('public docs domain must be a hostname')
        allowed.add(docs_domain.lower())
    reasons = set()
    if any(value and value.lower() in text.lower() for value in (key, label)):
        reasons.add('project identity')
    # Unix, drive-letter and UNC paths, including paths within prose and quotes.
    if re.search(r'(?<![\w:/])/[^\s/]|(?<!\w)[a-zA-Z]:[\\/]|\\\\[^\s]+|(?<!:)//[^\s/]', text):
        reasons.add('absolute path')
    if re.search(r'[\w.+-]+@[\w.-]+', text):
        reasons.add('email or SSH remote')
    if re.search(r'\b(?:ssh|git)://|\b[^\s/:]+@[^\s:]+:|\b[\w.-]+:[\w.-]+(?:/[\w./-]+)?', text):
        reasons.add('git remote')
    for url in re.findall(r'https?://[^\s<>"\)]+', text):
        parsed = urlsplit(url)
        if parsed.hostname not in allowed:
            reasons.add('hostname')
        if parsed.hostname == 'github.com' and parsed.path.rstrip('/').removesuffix('.git') != '/seankoji-com/t3-plugins':
            reasons.add('git remote')
    # Repo slugs and remote URLs. Only the public upstream slug may be shared.
    for slug in re.findall(r'(?<![\w/.-])([\w.-]+/[\w.-]+)(?:\.git)?\b', text):
        if slug != 'seankoji-com/t3-plugins':
            reasons.add('repository slug or relative path')
    for host in re.findall(r'(?<![\w.-])(?:[a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+', text):
        if host.lower() not in allowed:
            reasons.add('hostname or IPv4')
    if re.search(r'\b(?:localhost|hostname\s*[:=]\s*\S+|host\s*[:=]\s*\S+)\b', text, re.I):
        reasons.add('hostname')
    # Includes compressed, bracketed, IPv4-mapped and scoped IPv6.
    for token in re.findall(r'[0-9a-fA-F:.%]+', text):
        if ':' not in token:
            continue
        try:
            ipaddress.ip_address(token.split('%')[0])
            reasons.add('IPv6')
        except ValueError:
            pass
    return sorted(reasons)


def validate_drafts(drafts):
    if not isinstance(drafts, list) or not drafts:
        raise Unavailable('harvest needs at least one draft')
    seen = set()
    for draft in drafts:
        if not isinstance(draft, dict) or set(draft) != {'entry_id', 'destination', 'title', 'body'}:
            raise Unavailable('drafts have entry_id, destination, title and body only')
        pair = draft['entry_id'], draft['destination']
        if draft['destination'] not in ('upstream', 'agents') or pair in seen:
            raise Unavailable('invalid or duplicate destination')
        seen.add(pair)
        for field in ('entry_id', 'title', 'body'):
            if not isinstance(draft[field], str) or not draft[field].strip():
                raise Unavailable('empty harvest draft')
    return seen


def prepare(loaded, drafts, docs_domain=None):
    """Return only screened text. A rejected draft must never be shown as ready for approval."""
    pairs = validate_drafts(drafts)
    entries = {entry['id']: entry for entry in loaded['data']['entries']}
    if any(entry_id not in entries for entry_id, _ in pairs):
        raise Unavailable('draft names an unknown learning')
    failures = []
    for draft in drafts:
        reasons = screen(draft['title'] + '\n' + draft['body'], loaded['key'], loaded['label'], docs_domain)
        if reasons:
            failures.append({'entry_id': draft['entry_id'], 'destination': draft['destination'], 'reasons': reasons})
    if failures:
        return {'status': 'blocked', 'screen': failures}
    payload = {'format_version': 1, 'drafts': drafts, 'docs_domain': docs_domain,
               'entries': {entry_id: digest(entries[entry_id]) for entry_id, _ in pairs}}
    return {'status': 'draft', 'draft': payload, 'shown_digest': digest(payload)}


def check_approval(draft, shown_digest, owner_reply):
    validate_drafts(draft['drafts'])
    if digest(draft) != shown_digest or owner_reply != 'approve ' + shown_digest:
        raise Unavailable('owner approval must match exactly the drafts shown; ask again after any edit')
    return shown_digest


def verify_for_publication(loaded, draft, shown_digest, owner_reply):
    check_approval(draft, shown_digest, owner_reply)
    prepared = prepare(loaded, draft['drafts'], draft.get('docs_domain'))
    if prepared['status'] != 'draft' or prepared['shown_digest'] != shown_digest:
        raise Unavailable('draft or source changed since approval; prepare and ask again')
    return draft['drafts']


def apply_receipts(entries, proposal):
    draft = proposal['draft']
    check_approval(draft, proposal['shown_digest'], proposal['owner_reply'])
    pairs = validate_drafts(draft['drafts'])
    originals = {entry['id']: entry for entry in entries}
    for entry_id, _ in pairs:
        if entry_id not in originals or digest(originals[entry_id]) != draft['entries'].get(entry_id):
            raise Unavailable('learning changed after drafts were shown; prepare and ask again')
    result = []
    receipts = proposal.get('receipts', [])
    receipt_pairs = set()
    for receipt in receipts:
        pair = receipt['entry_id'], receipt['destination']
        if pair not in pairs or pair in receipt_pairs:
            raise Unavailable('receipt has an unapproved or duplicate destination')
        receipt_pairs.add(pair)
        url = urlsplit(receipt['url'])
        expected = ('seankoji-com/t3-plugins/issues' if pair[1] == 'upstream'
                    else proposal.get('project_slug', '') + '/pull')
        if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment
                or not re.fullmatch('/' + re.escape(expected) + r'/[1-9]\d*', url.path)):
            raise Unavailable('receipt URL does not match its approved destination')
    for entry in entries:
        entry_id = entry['id']
        revised = dict(entry, destinations=dict(entry.get('destinations', {})))
        destinations = {dest for eid, dest in pairs if eid == entry_id}
        if destinations:
            # Recover partial publication by preparing remaining destinations again.
            for dest in destinations:
                revised['destinations'].setdefault(dest, None)
            for receipt in receipts:
                if receipt['entry_id'] == entry_id:
                    revised['destinations'][receipt['destination']] = receipt['url']
            if revised['destinations'] and all(revised['destinations'].values()):
                continue
        validate_entry(revised)
        result.append(revised)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input.read_text())
        result = prepare(data['loaded'], data['drafts'], data.get('docs_domain'))
        # Drafts contain no identity labels or paths. Results stay in a private local file.
        from learning_store import directory, atomic_file
        with directory(args.output.absolute().parent, True) as fd:
            atomic_file(fd, args.output.name, json.dumps(result, indent=2).encode())
        print(json.dumps({'status': result['status'], 'output': str(args.output)}))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'unavailable', 'reason': str(exc)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
