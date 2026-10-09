#!/usr/bin/env python3
"""Workflow-state CLI. Every invocation prints exactly one JSON object on stdout:

  {"schema_version": 1, "ok": true,  "op": ..., "run_id": ..., "data": {...}}
  {"schema_version": 1, "ok": false, "op": ..., "run_id": ..., "error": {"code", "message", "details"}}

Exit codes: 0 ok, 2 invalid input/schema/version, 3 ownership or stale
generation, 4 prohibited by state/authorization/prerequisites, 5 environment/IO.
Diagnostics go to stderr only. Nothing here runs gate commands or calls a model."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep installed package directories exactly as the manifest lists them

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
    __package__ = 'core'

from core import acceptance, engine, planning, recipe, records, report, store  # noqa: E402
from core.blockers import active as active_blockers  # noqa: E402
from core.errors import CoreError, Environment, InvalidInput, Prohibited, Conflict  # noqa: E402
from core.fsutil import read_json  # noqa: E402

ENVELOPE_VERSION = 1
CLI_PATH = Path(__file__).absolute()
OPS = ('init', 'status', 'claim', 'release', 'recover', 'next', 'record', 'validate', 'report', 'unblock',
       'recipe-scaffold', 'recipe-check', 'recipe-stamp')
NO_STATE = ('recipe-scaffold', 'recipe-check')


def plugin_info(args) -> dict | None:
    directory = Path(args.plugin_dir).absolute() if args.plugin_dir else CLI_PATH.parent.parent
    manifest = directory / 'plugin.json'
    if not manifest.is_file():
        if args.plugin_dir:
            raise InvalidInput('plugin_dir', f'{directory} has no plugin.json')
        return None
    data = read_json(manifest)
    entry = directory / data.get('entry', 'entry.md')
    version = data['version']
    installed = directory / 'install-manifest.json'
    if installed.is_file():
        version = read_json(installed).get('version', version)
    return {'name': data['name'], 'version': version, 'entry': str(entry), 'package_dir': str(directory),
            'defaults': str(directory / data['defaults']) if data.get('defaults') else None}


def state_root(args, plugin) -> Path:
    if args.state_root:
        return Path(args.state_root).expanduser().absolute()
    root = store.env_state_root(plugin['name'] if plugin else None)
    if root is None:
        raise InvalidInput('state_root', 'pass --state-root or --plugin-dir (no installed plugin.json found)')
    return root


def read_input(args):
    if args.json is not None:
        text = args.json
    elif args.input == '-':
        text = sys.stdin.read()
    elif args.input:
        try:
            text = Path(args.input).read_text()
        except OSError as exc:
            raise InvalidInput('input_unreadable', f'cannot read {args.input}: {exc.strerror}') from exc
    else:
        raise InvalidInput('input_missing', 'pass --input <file|-> or --json <object>')
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidInput('invalid_json', f'input is not JSON: {exc.msg}', {'line': exc.lineno}) from exc


def make_ctx(args, root: Path, run_store=None, owner=None) -> engine.Ctx:
    run_dir = run_store.run_dir if run_store else root
    return engine.Ctx(state_root=root, run_dir=run_dir, cli_path=CLI_PATH,
                      parent_thread_id=args.parent_thread_id or os.environ.get('T3_PARENT_THREAD_ID') or None,
                      owner=owner, at=store.now_iso())


def summary(state: dict, owner: dict | None) -> dict:
    return {
        'phase': state['phase'], 'resume_phase': state.get('resume_phase'), 'generation': state['generation'],
        'mode': state['execution']['mode'], 'isolation': state['execution'].get('isolation'),
        'endstate': state['authorization']['endstate'], 'repo': state['repo'],
        'owner': None if not owner else {'token': owner['token'], 'claimed_at': owner['claimed_at'],
                                         'deadline': owner['deadline'], 'invocation': owner.get('invocation')},
        'budget': state['budget'], 'counters': state.get('counters'),
        'tasks': [{'id': t['id'], 'kind': t.get('kind'), 'status': t['status'],
                   'host_task_ids': [r['task_id'] for r in t.get('rounds') or [] if r.get('task_id')]}
                  for t in state.get('tasks', [])],
        'blockers': active_blockers(state),
        'parent_thread_id': state['host'].get('parent_thread_id'),
        'plugin': state['plugin'],
    }


def op_init(args, plugin, root):
    plan = read_input(args)
    if plugin is None:
        raise InvalidInput('plugin_dir', 'init needs plugin metadata: pass --plugin-dir')
    defaults = read_json(Path(plugin['defaults'])) if plugin.get('defaults') else {}
    run_id = store.new_run_id()
    state = planning.build(plan, defaults, state_root=root,
                           plugin={k: plugin[k] for k in ('name', 'version', 'entry', 'package_dir')})
    run = store.RunStore(root, run_id)
    state = run.create(state)
    return run_id, {'run_dir': str(run.run_dir), 'generation': state['generation'], 'phase': state['phase'],
                    'tasks': [t['id'] for t in state['tasks']], 'state_root': str(root)}


def _run(args, root):
    if not args.run_id:
        raise InvalidInput('run_id', 'pass --run-id')
    return store.RunStore(root, args.run_id)


def op_status(args, plugin, root):
    run = _run(args, root)
    return run.run_id, summary(run.load(), run.owner())


def op_claim(args, plugin, root):
    run = _run(args, root)
    invocation = {'parent_thread_id': args.parent_thread_id, 'label': args.invocation}
    owner = run.claim(invocation)
    state = run.load()
    return run.run_id, {'token': owner['token'], 'generation': state['generation'], 'deadline': owner['deadline'],
                        'budget': state['budget']}


def op_release(args, plugin, root):
    run = _run(args, root)
    return run.run_id, run.release(args.token)


def op_recover(args, plugin, root):
    run = _run(args, root)
    return run.run_id, run.recover(args.token, args.confirmed_dead)


def op_next(args, plugin, root):
    run = _run(args, root)
    state = run.load()
    owner = run.owner()
    ctx = make_ctx(args, root, run, owner)
    data = engine.next_actions(ctx, state)
    data['owned'] = owner is not None
    return run.run_id, data


def op_record(args, plugin, root):
    run = _run(args, root)
    if args.kind not in records.HANDLERS:
        raise InvalidInput('record_kind', f'--kind must be one of {sorted(records.HANDLERS)}')
    payload = read_input(args)
    owner = run.owner()
    ctx = make_ctx(args, root, run, owner)
    state, result = run.mutate(args.token, args.expect_generation,
                               lambda working, own: records.apply(ctx, working, args.kind, payload))
    return run.run_id, {'generation': state['generation'], 'phase': state['phase'], 'result': result}


def op_validate(args, plugin, root):
    run = _run(args, root)
    state = run.load()
    ctx = make_ctx(args, root, run, run.owner())
    ev = acceptance.evaluate(state, root, run.run_dir)
    return run.run_id, {k: ev[k] for k in ('ready', 'status', 'missing', 'failed', 'stale', 'counts',
                                           'requirements', 'checks', 'review', 'binding')}


def op_report(args, plugin, root):
    run = _run(args, root)
    state = run.load()
    ctx = make_ctx(args, root, run, run.owner())
    built = report.build(ctx, state)
    paths = report.write(ctx, built)
    return run.run_id, {'report': built, 'paths': paths}


def _decision(state, blocker, args):
    decision = args.decision
    if decision != blocker['resume']['decision']:
        raise Prohibited('decision_mismatch', f'blocker {blocker["id"]} resolves with {blocker["resume"]["decision"]}')
    task_ids = blocker['task_ids']
    if decision == 'raise-repair-limit':
        value = int(args.value)
        if value <= state['policy']['repair_limit']:
            raise InvalidInput('value', 'new repair limit must exceed the current one')
        state['policy']['repair_limit'] = value
    elif decision == 'raise-budget':
        value = int(args.value)
        if not state['budget']['seconds'] < value <= 86400:
            raise InvalidInput('value', 'new budget must exceed the current one and stay within 86400')
        state['budget']['seconds'] = value
    elif decision == 'set-endstate':
        if args.value not in ('local',):
            raise InvalidInput('value', 'v1 can only fall back to the local endstate')
        state['authorization']['endstate'] = args.value
    elif decision == 'adopt-parent':
        for task in state['tasks']:
            for item in task.get('rounds') or []:
                if item.get('task_id') and not item.get('terminal'):
                    item['terminal'] = True
                    item['abandoned'] = 'operator confirmed stopped when adopting a new parent thread'
                    task['status'] = 'pending'
        state['host']['previous_parent_thread_ids'] = state['host'].get('previous_parent_thread_ids', []) + [
            state['host'].get('parent_thread_id')]
        state['host']['parent_thread_id'] = args.value
    elif decision in ('retry-task', 'retry-integration'):
        task = engine.task_by_id(state, args.task_id or (task_ids[0] if task_ids else ''))
        if task is None:
            raise InvalidInput('task_id', 'unknown task')
        if decision == 'retry-task':
            task.update(status='pending', correction_used=False, blocker_id=None,
                        next_round={'purpose': 'initial', 'context': None}, unavailable_targets=[])
        else:
            task.update(status='accepted', blocker_id=None)
    elif decision == 'retry-cancel':
        for task in state['tasks']:
            for item in task.get('rounds') or []:
                if item.get('task_id') in task_ids and not item.get('terminal'):
                    item['cancel'] = None
    elif decision == 'retry':
        for task in state['tasks']:
            if task['id'] in task_ids:
                task.update(unavailable_targets=[], blocker_id=None)
                if task['status'] == 'blocked':
                    task['status'] = 'pending'
                if task.get('kind') == 'review' and task['status'] == 'unavailable':
                    task['status'] = 'pending'
        if blocker['code'] == 'capability_unavailable':
            state['capabilities'] = None
        if blocker['code'] == 'provider_unavailable' and not task_ids:
            for task in state['tasks']:
                if task.get('kind') == 'review' and task['status'] == 'unavailable':
                    task['unavailable_targets'] = []
            state['capabilities'] = None


def op_unblock(args, plugin, root):
    run = _run(args, root)
    if not args.blocker_id or not args.decision:
        raise InvalidInput('unblock_args', 'pass --blocker-id and --decision from the blocker resume command')
    found = {}

    def check(state):
        ctx = make_ctx(args, root, run, None)
        if args.decision == 'adopt-parent':
            ctx.parent_thread_id = args.value
        current = active_blockers(state) + [b for b in [engine.next_actions(ctx, state).get('blocked')] if b]
        match = next((b for b in current if b['id'] == args.blocker_id), None)
        if match is None:
            raise Conflict('stale_blocker', 'that blocker is no longer current; run status again',
                           {'current': [b['id'] for b in current]})
        found['blocker'] = match

    def change(state):
        blocker = found['blocker']
        _decision(state, blocker, args)
        for item in state.get('blockers', []):
            if item['id'] == blocker['id'] or (set(item['task_ids']) & set(blocker['task_ids']) and item['status'] == 'active'):
                item['status'] = 'resolved'
                item['resolved_by'] = args.decision
        if state['phase'] == 'blocked' and not active_blockers(state):
            from core import transitions
            transitions.unblock(state, store.now_iso(), f'operator decision {args.decision}')
        return {'resolved': blocker['id'], 'decision': args.decision, 'phase': state['phase']}

    owner = run.owner()
    if owner and args.token:
        state, result = run.mutate(args.token, run.load()['generation'],
                                   lambda working, own: (check(working), change(working))[1])
    else:
        state, result = run.mutate_unowned(check, change)
    return run.run_id, dict(result, generation=state['generation'])


def op_recipe_scaffold(args, plugin, root):
    facts = read_input(args)
    template_dir = Path(args.template_dir) if args.template_dir else (
        Path(plugin['package_dir']) / 'templates' if plugin else None)
    if template_dir is None or not args.repo:
        raise InvalidInput('recipe_args', 'pass --repo and --template-dir (or --plugin-dir)')
    return None, recipe.scaffold(facts, template_dir, Path(args.repo))


def op_recipe_check(args, plugin, root):
    if not args.recipe:
        raise InvalidInput('recipe_args', 'pass --recipe <recipe.json>')
    return None, recipe.check(Path(args.recipe))


def op_recipe_stamp(args, plugin, root):
    run = _run(args, root)
    if not (args.recipe and args.feature and args.requirement):
        raise InvalidInput('recipe_args', 'pass --recipe, --feature and --requirement')
    return run.run_id, recipe.stamp(Path(args.recipe), run.load(), run.run_dir, args.feature, args.requirement)


HANDLERS = {'init': op_init, 'status': op_status, 'claim': op_claim, 'release': op_release, 'recover': op_recover,
            'next': op_next, 'record': op_record, 'validate': op_validate, 'report': op_report,
            'unblock': op_unblock, 'recipe-scaffold': op_recipe_scaffold, 'recipe-check': op_recipe_check,
            'recipe-stamp': op_recipe_stamp}


def parser() -> argparse.ArgumentParser:
    parse = argparse.ArgumentParser(prog='cli.py', description=__doc__.split('\n')[0])
    parse.add_argument('op', choices=OPS)
    parse.add_argument('--state-root')
    parse.add_argument('--plugin-dir')
    parse.add_argument('--run-id')
    parse.add_argument('--token')
    parse.add_argument('--expect-generation', type=int)
    parse.add_argument('--input')
    parse.add_argument('--json')
    parse.add_argument('--kind')
    parse.add_argument('--parent-thread-id')
    parse.add_argument('--invocation')
    parse.add_argument('--confirmed-dead', action='store_true')
    parse.add_argument('--blocker-id')
    parse.add_argument('--decision')
    parse.add_argument('--value')
    parse.add_argument('--task-id')
    parse.add_argument('--recipe')
    parse.add_argument('--feature')
    parse.add_argument('--requirement')
    parse.add_argument('--template-dir')
    parse.add_argument('--repo')
    return parse


def main(argv=None) -> int:
    parse = parser()
    run_id = None
    op = None
    try:
        try:
            args = parse.parse_args(argv)
        except SystemExit as exc:
            if exc.code == 0:
                raise
            raise InvalidInput('usage', 'invalid arguments; see --help on stderr') from None
        op = args.op
        run_id = args.run_id
        plugin = plugin_info(args)
        root = state_root(args, plugin) if op not in NO_STATE else None
        run_id, data = HANDLERS[op](args, plugin, root)
        print(json.dumps({'schema_version': ENVELOPE_VERSION, 'ok': True, 'op': op, 'run_id': run_id, 'data': data},
                         ensure_ascii=False))
        return 0
    except CoreError as exc:
        print(json.dumps({'schema_version': ENVELOPE_VERSION, 'ok': False, 'op': op, 'run_id': run_id,
                          'error': exc.to_json()}, ensure_ascii=False))
        print(f'{exc.code}: {exc.message}', file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        error = Environment('io_error', str(exc))
        print(json.dumps({'schema_version': ENVELOPE_VERSION, 'ok': False, 'op': op, 'run_id': run_id,
                          'error': error.to_json()}))
        print(f'io_error: {exc}', file=sys.stderr)
        return error.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
