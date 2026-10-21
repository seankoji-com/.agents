#!/usr/bin/env python3
"""Public IMPS gate with admission/receipt checks around the format-neutral core."""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
args = sys.argv[1:]
if args[:1] == ['doctor']:
    os.execv(sys.executable, [sys.executable, str(HERE / 'scripts/doctor.py'), *args[1:]])
if args[:1] == ['plan-review']:
    os.execv(sys.executable, [sys.executable, str(HERE / 'scripts/plan_review.py'), *args[1:]])
ROOT = next((p for p in (HERE, HERE.parent.parent) if (p / 'core/cli.py').is_file()), None)
if ROOT is None:
    sys.exit('no usable core/cli.py beside ' + str(HERE) + ' or in its source checkout')
sys.path.insert(0, str(ROOT))
from core import cli, planning, records, store, report, recipe
from core.fsutil import read_json
from core.errors import Prohibited
from core.jobs.store import canonical
from shared import imps_planning as imps
from shared import planning_review as review

original_execute = cli.execute


def execute(a):
    try:
        package = Path(a.plugin_dir)
        root = Path(a.state_root).expanduser().absolute() if a.state_root else store.env_state_root('imps')
        if a.op == 'init':
            data = cli.read_input(a)
            context = data.pop('imps', None)
            review.need(isinstance(context, dict), 'imps admission context required before gate initialization')
            record = imps.initial(data, context, package)
            record['state_root'] = str(root)
            state = planning.build(data, read_json(package / 'config.json'), state_root=root, plugin=cli.plugin_info(a))
            state['notes'].append({'text': imps.NOTE + canonical(review.seal(record)).decode(),
                                   'recorded_at': store.now_iso()})
            run = store.RunStore(root, store.new_run_id()); run.create(state)
            return run.run_id, {'run_dir': str(run.run_dir), 'phase': 'active', 'state_root': str(root)}
        if a.op == 'status':
            run = store.RunStore(root, a.run_id)
            with run.locked():
                state = run.load()
                if any(n['text'].startswith(imps.NOTE) for n in state['notes']):
                    imps.run_record(state)
                    state['planning_review_status'] = 'recorded-unvalidated'
                else:
                    state['planning_review_status'] = 'legacy-unreviewed'
                return run.run_id, state
        if a.op in ('validate', 'report', 'recipe-stamp', 'finalize'):
            run = store.RunStore(root, a.run_id)
            with run.locked():
                state = run.load()
                if a.op == 'finalize':
                    desc = cli.read_input(a)
                    record = imps.run_record(state); context = record['context']
                    review.need(context['admission']['operation'] in imps.FINAL and desc['kind'] == 'synthesis',
                                'final integrated synthesis only')
                    review.need(desc['admission'] == context['admission'] and
                        desc['document']['path'] == context['output_path'] and desc['requirements'] ==
                        {r['id']: r['text'] for r in state['brief']['requirements']}, 'final output/criteria differs from run')
                    review.need(desc.get('job_file') == context.get('job_file'), 'final producing job differs from run')
                    imps.validate(desc, package)
                else:
                    imps.validate_run(state, package)
                    ev = cli.validate(state, root, run.run_dir)
                    if a.op == 'validate':
                        return run.run_id, ev
                    if a.op == 'report':
                        built = report.build(state, ev)
                        return run.run_id, {'report': built, 'paths': report.write(run.run_dir, built)}
                    if not (a.recipe and a.feature and a.requirement):
                        raise Prohibited('recipe_args', 'pass --recipe, --feature and --requirement')
                    record = imps.run_record(state)
                    review.need(record['context']['admission']['operation'] == 'verification-init' and
                        Path(a.recipe).resolve() == Path(record['context']['recipe_file']).resolve(),
                        'stamp target must be this run\'s reviewed recipe')
                    review.need(ev['outcome'] == 'completed', 'recipe stamping requires current completed evidence')
                    state['phase'] = 'completed'
                    return run.run_id, recipe.stamp(Path(a.recipe), state, run.run_dir, a.feature, a.requirement)
            if a.op == 'finalize':
                state, result = run.mutate(lambda state: records.apply(state, root, run.run_dir, 'note',
                    {'text': imps.NOTE + 'final:' + canonical(desc).decode()}))
                return run.run_id, {'phase': state['phase'], 'result': result}
        if a.op == 'note':
            review.need(not cli.read_input(a)['text'].startswith(imps.NOTE), 'reserved imps admission note')
        return original_execute(a)
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        raise Prohibited('imps_planning', str(exc)) from exc


cli.OPS = (*cli.OPS, 'finalize')
cli.execute = execute
if not any(arg == '--plugin-dir' or arg.startswith('--plugin-dir=') for arg in args):
    args += ['--plugin-dir', str(HERE)]
raise SystemExit(cli.main(args))
