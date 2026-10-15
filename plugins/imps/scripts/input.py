#!/usr/bin/env python3
"""Classify an imps request and read checklist claims. Never execute file content."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

OPERATIONS = {'doctor', 'run', 'resume', 'status', 'cancel', 'verification-init',
              'blast-radius', 'audit', 'issues', 'prs', 'checklist', 'discussion'}
ALIASES = {'imps': 'run', 'imp-agency': 'audit', 'issue-mode': 'issues'}


def checklist(path):
    path = Path(path).expanduser().resolve(strict=True)
    items = []
    current = None
    fenced = False
    fence_char = None
    fence_length = 0
    for number, line in enumerate(path.read_text().splitlines(), 1):
        fence = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence:
            char, length = fence[1][0], len(fence[1])
            if not fenced:
                fenced, fence_char, fence_length = True, char, length
            elif char == fence_char and length >= fence_length:
                fenced = False
            continue
        if fenced:
            continue
        match = re.match(r'^\s*[-*+] \[([ xX])\]\s+(.+)$', line)
        if match:
            current = {'line': number, 'checked': match[1].lower() == 'x', 'claim': match[2],
                       'verify': None, 'done_when': None, 'warnings': []}
            items.append(current)
            continue
        detail = re.match(r'^\s+(?:[-*+]\s+)?(Verify|Done when):\s*(.*)$', line)
        if detail and current:
            key = 'verify' if detail[1] == 'Verify' else 'done_when'
            if current[key] is not None:
                current['warnings'].append('duplicate ' + detail[1])
            else:
                current[key] = detail[2]
        elif line.strip() and not line[0].isspace():
            current = None
    for item in items:
        if not item['checked']:
            for key in ('verify', 'done_when'):
                if not item[key]:
                    item['warnings'].append('missing ' + key)
        item['actionable'] = not item['checked'] and not item['warnings']
    return {'path': str(path), 'items': items,
            'warnings': [] if items else ['no checklist items found']}


def discussion(text):
    bare = re.fullmatch(r'discussion\s+#?([1-9][0-9]*)', text)
    if bare:
        return {'number': int(bare[1]), 'repository': None}
    url = urlsplit(text)
    match = re.fullmatch(r'/([^/]+)/([^/]+)/discussions/([1-9][0-9]*)/?', url.path)
    if url.scheme == 'https' and url.netloc == 'github.com' and match:
        return {'number': int(match[3]), 'repository': match[1] + '/' + match[2],
                'url': 'https://github.com' + url.path.rstrip('/')}
    return None


def issue_set(text):
    if text.startswith('{'):
        value = json.loads(text)
        if not isinstance(value, dict) or set(value) - {'issues', 'holdingBranch'}:
            raise ValueError('issue input accepts only issues and holdingBranch')
        numbers = value.get('issues')
        branch = value.get('holdingBranch')
        if branch is not None and (not isinstance(branch, str) or not branch.strip()):
            raise ValueError('holdingBranch must be a nonempty string')
    elif re.fullmatch(r'#?[1-9][0-9]*(?:\s+#?[1-9][0-9]*)*', text):
        numbers = [int(n.lstrip('#')) for n in text.split()]
        branch = None
    else:
        raise ValueError('issues requires issue numbers or an issue-set JSON object')
    if (not isinstance(numbers, list) or not 1 <= len(numbers) <= 200
            or any(type(n) is not int or n <= 0 for n in numbers)):
        raise ValueError('issues must contain 1 to 200 positive integers')
    return {'issues': list(dict.fromkeys(numbers)), 'holding_branch': branch}


def route(text):
    if not isinstance(text, str):
        raise ValueError('text must be a string')
    text = re.sub(r'^(?:\$|/)?t3-imps(?:\s+|$)', '', text.strip(), count=1)
    # Only a standalone flag opts in, never a mention inside task prose or a path.
    panel = bool(re.search(r'(?<!\S)--personas(?!\S)', text))
    text = re.sub(r'(?<!\S)--personas(?!\S)', '', text).strip()
    if not text:
        return {'operation': None, 'arguments': '', 'personas': panel, 'picker': True}
    parts = text.split(maxsplit=1)
    first = parts[0].removeprefix('/imps:')
    operation = ALIASES.get(first, first)
    explicit = operation in OPERATIONS
    args = parts[1] if len(parts) > 1 else ''
    if first == 'imps' and args == 'run':
        args = ''
    if explicit and operation != 'run':
        result = {'operation': operation, 'arguments': args, 'personas': panel}
        if operation == 'checklist':
            result['checklist'] = checklist(args)
        elif operation == 'issues':
            result.update(issue_set(args))
        elif operation == 'discussion':
            result['discussion'] = discussion('discussion ' + args) or discussion(args)
            if not result['discussion']:
                raise ValueError('discussion requires a GitHub Discussion URL or a positive number')
        return result
    task = args if explicit else text
    if not task:
        return {'operation': 'run', 'arguments': '', 'personas': panel, 'needsArgument': True}
    result = {'operation': 'run', 'arguments': task, 'personas': panel}
    if re.fullmatch(r'#?[1-9][0-9]*(?:\s+#?[1-9][0-9]*)*', task) or task.startswith('{"issues"'):
        result.update(operation='issues', **issue_set(task))
    elif discussion(task):
        result.update(operation='discussion', discussion=discussion(task))
    elif task.endswith('.md') and Path(task).expanduser().is_file():
        result.update(operation='checklist', checklist=checklist(task))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='JSON file containing {"text": "request"}')
    args = parser.parse_args()
    try:
        request = json.loads(Path(args.input).read_text())
        if not isinstance(request, dict) or 'text' not in request:
            raise ValueError('request must contain text')
        print(json.dumps({'ok': True, 'data': route(request['text'])}))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
