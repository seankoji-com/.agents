#!/usr/bin/env python3
"""Scan one authorized JSON, JSONC or TOML config for broad-permission pointers.

Config values are omitted. Key pointers may still be private: keep output
host-local. Restrictive branches (`deny`, `ask`) inside permission blocks are
excluded, and prompt-suppression policies are reported separately from
access-widening permissions. This heuristic does not evaluate precedence,
arbitrary regexes or full provider semantics.
"""
import argparse
import importlib
import json
import re
import sys
from pathlib import Path

ALLOW_LIST_KEYS = frozenset({'allow', 'allowedtools', 'allowlist'})
RESTRICTIVE_BRANCH_KEYS = frozenset({'deny', 'denylist', 'blocked', 'disallow', 'ask'})
BYPASS_PLAIN_KEYS = frozenset({
    'bypasspermissions',
    'dangerouslyskippermissions',
    'skippermissions',
    'autoapprove',
    'trustall',
    'yolo',
    'allowall',
})
BYPASS_EXACT_KEYS = frozenset({
    'chat.tools.global.autoApprove',
    'chat.tools.autoApprove',
})
SANDBOX_PERMISSIVE = frozenset({'dangerfullaccess', 'off', 'none', 'disabled'})
MODE_PERMISSIVE = frozenset({
    'bypasspermissions',
    'fullaccess',
    'allowall',
    'yolo',
    'unrestricted',
})
MODE_KEYS = frozenset({'defaultmode', 'permissionmode', 'runtimemode'})
APPROVAL_POLICY_KEYS = frozenset({'approvalpolicy', 'askforapproval'})
PROMPT_MODE_KEYS = frozenset({'defaultmode', 'permissionmode'})
VSCODE_TERMINAL_KEY = 'chat.tools.terminal.autoApprove'
VSCODE_REGEX = re.compile(r'^/(.+)/([dgimsuvy]*)$')
VSCODE_NONEMPTY_CATCHALLS = frozenset({
    '.+', '^.+$', '.+$', '^.+',
    r'[\s\S]+', r'^[\s\S]+$', r'[\s\S]+$', r'^[\s\S]+',
})


class TomlUnsupportedError(ValueError):
    """Raised when scanning a .toml file on Python < 3.11 without tomllib."""


def _load_tomllib():
    if sys.version_info < (3, 11) or 'tomllib' not in sys.stdlib_module_names:
        return None
    return importlib.import_module('tomllib')


def _reject_constant(_token):
    raise ValueError('nonstandard JSON constant')


def strip_jsonc(text):
    """Strip JSONC comments and valid trailing commas without altering strings."""
    no_comments = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            no_comments.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
        elif ch == '"':
            in_string = True
            no_comments.append(ch)
            i += 1
        elif ch == '/' and i + 1 < n and text[i + 1] == '/':
            i += 2
            while i < n and text[i] not in '\r\n':
                i += 1
        elif ch == '/' and i + 1 < n and text[i + 1] == '*':
            end = text.find('*/', i + 2)
            if end == -1:
                raise ValueError('unterminated block comment')
            # Preserve token separation so `tr/* gap */ue` stays invalid.
            no_comments.append(' ')
            i = end + 2
        else:
            no_comments.append(ch)
            i += 1

    stage = ''.join(no_comments)
    cleaned = []
    in_string = False
    escape = False
    last_sig = None
    i = 0
    n = len(stage)
    while i < n:
        ch = stage[i]
        if in_string:
            cleaned.append(ch)
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
                last_sig = '"'
            i += 1
        elif ch == '"':
            in_string = True
            cleaned.append(ch)
            i += 1
        elif ch == ',':
            j = i + 1
            while j < n and stage[j] in ' \t\r\n':
                j += 1
            next_sig = stage[j] if j < n else None
            if (next_sig in (']', '}') and last_sig is not None
                    and last_sig not in ('[', '{', ',', ':')):
                i += 1
                continue
            cleaned.append(ch)
            last_sig = ','
            i += 1
        else:
            cleaned.append(ch)
            if ch not in ' \t\r\n':
                last_sig = ch
            i += 1
    return ''.join(cleaned)


def parse_config(text, suffix='.json'):
    """Parse JSON, JSONC or TOML text into Python data without echoing values."""
    text = text.removeprefix('\ufeff')
    if suffix.lower() == '.toml':
        mod = _load_tomllib()
        if mod is None:
            raise TomlUnsupportedError('TOML scanning requires Python 3.11+')
        return mod.loads(text)
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError:
        return json.loads(strip_jsonc(text), parse_constant=_reject_constant)


def _norm_key(key):
    return re.sub(r'[-_\s]+', '', key.lower())


def _escape_pointer(token):
    return token.replace('~', '~0').replace('/', '~1')


def is_opencode_wildcard(value):
    """Match OpenCode whole-value glob wildcards verbatim (whitespace is literal)."""
    return value in ('*', '**')


def is_vscode_catchall(key):
    """Match bounded VS Code terminal catch-all keys per convertAutoApproveEntryToRegex."""
    match = VSCODE_REGEX.fullmatch(key)
    if not match:
        return False
    pattern, flags = match.groups()
    if pattern == '.*':
        return True
    cleaned = flags.replace('g', '')
    if len(cleaned) != len(set(cleaned)) or ('u' in cleaned and 'v' in cleaned):
        return False
    return pattern in VSCODE_NONEMPTY_CATCHALLS


def _count_leaves(node):
    if isinstance(node, dict):
        return sum(_count_leaves(child) for child in node.values())
    if isinstance(node, list):
        return sum(_count_leaves(child) for child in node)
    return 1


def scan(value):
    leaves = 0
    broad_pointers, broad_seen = [], set()
    prompt_pointers, prompt_seen = [], set()
    findings = []

    def record(pointer, category):
        if category == 'prompt_suppression':
            if pointer not in prompt_seen:
                prompt_seen.add(pointer)
                prompt_pointers.append(pointer)
                findings.append({'pointer': pointer, 'category': category})
        elif pointer not in broad_seen:
            broad_seen.add(pointer)
            broad_pointers.append(pointer)
            findings.append({'pointer': pointer, 'category': category})

    def scan_scalar_key(key, node, pointer):
        nk = _norm_key(key)
        if isinstance(node, bool):
            if node is True and (nk in BYPASS_PLAIN_KEYS or key in BYPASS_EXACT_KEYS):
                record(pointer, 'bypass_flag')
        elif isinstance(node, str):
            nv = _norm_key(node)
            if nk == 'sandboxmode' and nv in SANDBOX_PERMISSIVE:
                record(pointer, 'permissive_mode')
            elif nk in MODE_KEYS and nv in MODE_PERMISSIVE:
                record(pointer, 'permissive_mode')
            elif ((nk in APPROVAL_POLICY_KEYS and nv == 'never')
                  or (nk in PROMPT_MODE_KEYS and nv == 'dontask')):
                record(pointer, 'prompt_suppression')

    def scan_allow_list(node, pointer):
        nonlocal leaves
        if isinstance(node, list):
            for idx, item in enumerate(node):
                if isinstance(item, str):
                    leaves += 1
                    if '*' in item or item.strip().lower() in ('allow', 'always'):
                        record(f'{pointer}/{idx}', 'wildcard_or_allow')
                else:
                    leaves += _count_leaves(item)
        elif isinstance(node, str):
            leaves += 1
            if '*' in node or node.strip().lower() in ('allow', 'always'):
                record(pointer, 'wildcard_or_allow')
        else:
            leaves += _count_leaves(node)

    def scan_permission_container(node, pointer):
        nonlocal leaves
        if isinstance(node, str):
            leaves += 1
            if node.lower() in ('allow', 'always') or is_opencode_wildcard(node):
                record(pointer, 'wildcard_or_allow')
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                leaves += _count_leaves(item)
                if (isinstance(item, dict)
                        and isinstance(item.get('action'), str)
                        and isinstance(item.get('resource'), str)
                        and isinstance(item.get('effect'), str)
                        and item['effect'] == 'allow'
                        and is_opencode_wildcard(item['resource'])):
                    record(f'{pointer}/{idx}/resource', 'wildcard_or_allow')
        elif isinstance(node, dict):
            for key, child in node.items():
                nk = _norm_key(key)
                child_ptr = f'{pointer}/{_escape_pointer(key)}'
                if nk in RESTRICTIVE_BRANCH_KEYS:
                    leaves += _count_leaves(child)
                elif nk in ALLOW_LIST_KEYS:
                    scan_allow_list(child, child_ptr)
                elif (nk in BYPASS_PLAIN_KEYS or key in BYPASS_EXACT_KEYS
                      or nk == 'sandboxmode' or nk in MODE_KEYS
                      or nk in APPROVAL_POLICY_KEYS):
                    if isinstance(child, (dict, list)):
                        leaves += _count_leaves(child)
                    else:
                        leaves += 1
                        scan_scalar_key(key, child, child_ptr)
                elif isinstance(child, str):
                    leaves += 1
                    if child.lower() in ('allow', 'always') or is_opencode_wildcard(child):
                        record(child_ptr, 'wildcard_or_allow')
                elif isinstance(child, dict):
                    for selector, outcome in child.items():
                        sel_ptr = f'{child_ptr}/{_escape_pointer(selector)}'
                        if isinstance(outcome, str):
                            leaves += 1
                            if (is_opencode_wildcard(selector)
                                    and (outcome.lower() in ('allow', 'always')
                                         or is_opencode_wildcard(outcome))):
                                record(sel_ptr, 'wildcard_or_allow')
                        else:
                            leaves += _count_leaves(outcome)
                else:
                    leaves += _count_leaves(child)
        else:
            leaves += 1

    def scan_vscode_terminal(node, pointer):
        nonlocal leaves
        leaves += _count_leaves(node)
        if not isinstance(node, dict):
            return
        for selector, entry in node.items():
            if (is_vscode_catchall(selector)
                    and (entry is True
                         or (isinstance(entry, dict) and entry.get('approve') is True))):
                record(f'{pointer}/{_escape_pointer(selector)}', 'wildcard_or_allow')

    def walk(node, pointer=''):
        nonlocal leaves
        if isinstance(node, dict):
            for key, child in node.items():
                child_ptr = f'{pointer}/{_escape_pointer(key)}'
                nk = _norm_key(key)
                if key == VSCODE_TERMINAL_KEY:
                    scan_vscode_terminal(child, child_ptr)
                elif nk in ('permission', 'permissions'):
                    scan_permission_container(child, child_ptr)
                elif nk in ALLOW_LIST_KEYS:
                    scan_allow_list(child, child_ptr)
                elif (nk in BYPASS_PLAIN_KEYS or key in BYPASS_EXACT_KEYS
                      or nk == 'sandboxmode' or nk in MODE_KEYS
                      or nk in APPROVAL_POLICY_KEYS):
                    if isinstance(child, (dict, list)):
                        leaves += _count_leaves(child)
                    else:
                        leaves += 1
                        scan_scalar_key(key, child, child_ptr)
                elif isinstance(child, (dict, list)):
                    walk(child, child_ptr)
                else:
                    leaves += 1
                    scan_scalar_key(key, child, child_ptr)
        elif isinstance(node, list):
            for idx, child in enumerate(node):
                walk(child, f'{pointer}/{idx}')
        else:
            leaves += 1

    walk(value)
    return {
        'leaves': leaves,
        'broad_permission_pointers': broad_pointers,
        'prompt_policy_pointers': prompt_pointers,
        'findings': findings,
        'limit': 'heuristic only; no precedence, regex or provider semantics evaluated',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    try:
        raw = args.file.read_text(encoding='utf-8')
        result = scan(parse_config(raw, args.file.suffix))
    except TomlUnsupportedError:
        parser.exit(2, 'TOML scanning requires Python 3.11+; input values omitted.\n')
    except (OSError, ValueError, RecursionError):
        parser.exit(2, 'Cannot read valid bounded config; input values omitted.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10+ required')
    main()
