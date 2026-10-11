#!/usr/bin/env python3
"""Evidence gate CLI. Each invocation prints one JSON envelope.

Exit codes: 0 success, 2 input/version, 3 conflict, 4 prohibited, 5 environment.
This CLI never runs verification commands, models, Git mutations or cleanup.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
    __package__ = 'core'

from core import acceptance, planning, recipe, records, report, store
from core.errors import CoreError, Environment, InvalidInput, Prohibited
from core.fsutil import read_json

SUBMISSIONS = ('check', 'evidence', 'review', 'child', 'waive', 'note', 'policy', 'remote', 'cancel')
OPS = ('init', 'status', 'snapshot', 'validate', 'report', *SUBMISSIONS,
       'recipe-scaffold', 'recipe-check', 'recipe-stamp')


def plugin_info(args):
    directory = Path(args.plugin_dir).absolute() if args.plugin_dir else Path(__file__).absolute().parent.parent
    if not args.plugin_dir and not (directory / 'plugin.json').is_file():
        directory = directory / 'plugins' / 'imps'
    meta = read_json(directory / 'plugin.json')
    version = meta['version']
    if (directory / 'install-manifest.json').is_file():
        version = read_json(directory / 'install-manifest.json')['version']
    return {'name': meta['name'], 'version': version, 'entry': str(directory / meta['entry']),
            'package_dir': str(directory), 'defaults': str(directory / meta['defaults'])}


def read_input(args):
    if args.json is not None:
        return json.loads(args.json)
    if args.input == '-':
        return json.load(sys.stdin)
    if not args.input:
        raise InvalidInput('input_missing', 'pass --input FILE or --json OBJECT')
    return read_json(Path(args.input))


def validate(state, root, run_dir):
    """The only readiness computation, shared by validate and report."""
    result = acceptance.evaluate(state, root, run_dir)
    confirmed, reason = acceptance.remote_confirmed(state, result['binding'])
    result.update(remote_confirmed=confirmed, remote_reason=reason)
    result['outcome'] = ('cancelled' if state['phase'] == 'cancelled' else 'completed'
                         if result['ready'] and confirmed else 'blocked' if result['failed']
                         else 'in_progress')
    return result


def execute(args):
    plugin = plugin_info(args)
    if args.op == 'recipe-scaffold':
        if not args.repo:
            raise InvalidInput('recipe_args', 'pass --repo')
        templates = Path(args.template_dir or Path(plugin['package_dir']) / 'templates')
        return None, recipe.scaffold(read_input(args), templates, Path(args.repo))
    if args.op == 'recipe-check':
        if not args.recipe:
            raise InvalidInput('recipe_args', 'pass --recipe')
        return None, recipe.check(Path(args.recipe))
    root = Path(args.state_root).expanduser().absolute() if args.state_root else store.env_state_root(plugin['name'])
    if args.op == 'init':
        state = planning.build(read_input(args), read_json(Path(plugin['defaults'])), state_root=root, plugin=plugin)
        run = store.RunStore(root, store.new_run_id())
        run.create(state)
        return run.run_id, {'run_dir': str(run.run_dir), 'phase': 'active', 'state_root': str(root)}
    if not args.run_id:
        raise InvalidInput('run_id', 'pass --run-id')
    run = store.RunStore(root, args.run_id)
    if args.op in SUBMISSIONS:
        payload = {} if args.op == 'cancel' else read_input(args)
        state, result = run.mutate(lambda state: records.apply(state, root, run.run_dir, args.op, payload))
        return run.run_id, {'phase': state['phase'], 'result': result}
    # Reads and reports use the same lock as writes so they see one whole transaction.
    with run.locked():
        state = run.load()
        if args.op == 'status':
            return run.run_id, state
        if args.op == 'snapshot':
            return run.run_id, acceptance.binding(state, root)
        ev = validate(state, root, run.run_dir)
        if args.op == 'validate':
            return run.run_id, ev
        if args.op == 'report':
            built = report.build(state, ev)
            return run.run_id, {'report': built, 'paths': report.write(run.run_dir, built)}
        if not (args.recipe and args.feature and args.requirement):
            raise InvalidInput('recipe_args', 'pass --recipe, --feature and --requirement')
        if ev['outcome'] != 'completed':
            raise Prohibited('stale_evidence', 'recipe stamping requires current completed evidence')
        # Completion is derived, never accepted from a submission or stored as authority.
        state['phase'] = 'completed'
        return run.run_id, recipe.stamp(Path(args.recipe), state, run.run_dir, args.feature, args.requirement)


def parser():
    parse = argparse.ArgumentParser(prog='cli.py', description=__doc__.split('\n')[0])
    parse.add_argument('op', choices=OPS)
    for option in ('state-root', 'plugin-dir', 'run-id', 'input', 'json', 'recipe', 'feature', 'requirement',
                   'template-dir', 'repo'):
        parse.add_argument('--' + option)
    return parse


def main(argv=None):
    op = run_id = None
    try:
        try:
            args = parser().parse_args(argv)
        except SystemExit as exc:
            if exc.code == 0:
                raise
            raise InvalidInput('usage', 'invalid arguments; see --help on stderr') from None
        op, run_id = args.op, args.run_id
        run_id, data = execute(args)
        print(json.dumps({'schema_version': 1, 'ok': True, 'op': op, 'run_id': run_id, 'data': data}))
        return 0
    except CoreError as exc:
        error = exc
    except (ValueError, json.JSONDecodeError) as exc:
        error = InvalidInput('invalid_input', str(exc))
    except OSError as exc:
        error = Environment('io_error', str(exc))
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        error = Environment('internal_error', f'{type(exc).__name__}: {exc}')
    print(json.dumps({'schema_version': 1, 'ok': False, 'op': op, 'run_id': run_id, 'error': error.to_json()}))
    print(f'{error.code}: {error.message}', file=sys.stderr)
    return error.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
