#!/usr/bin/env python3
"""Focus-group chooser admission and consumption of separate, pinned planning receipts.

This helper never dispatches, chooses a model, or accepts review by assertion.
"""
import argparse
import json
from pathlib import Path
import sys

PKG = Path(__file__).resolve().parents[1]
RUNTIME = next(p for p in (PKG, PKG.parents[1]) if (p / 'shared/adopter_planning.py').is_file())
sys.path.insert(0, str(RUNTIME))
from core.jobs.store import _atomic, _regular, canonical, strict_load
from shared import adopter_planning as adopter, model_selection as models, planning_review as review

REQUIREMENTS = {
    'FG-PLAN': 'The editable persona/model matrix and protocol answer the original product decision without claiming human demand.',
    'FG-AUTHORITY': 'Exact revision approval, per-role sharing, budgets, fresh children and isolated journeys are feasible and bounded.',
    'FG-REVIEW': 'The analyst and distinct-lineage fidelity reviewer retain evidence, dissent, identity and honest completion boundaries.'}


def equal_target(a, b):
    return all(a.get(k, {} if k == 'options' else None) == b.get(k, {} if k == 'options' else None)
               for k in ('providerInstanceId', 'model', 'options', 'runtimeMode'))


def admission(record):
    review.need(isinstance(record, dict) and record.get('plugin') == 'focus-group', 'focus-group upfront selection required')
    adopter.continuation(record, invocation_id=record['invocation_id'])
    return record


def choices(plan, record):
    selected = admission(record)['selection']
    # Per-role names preserve the matrix. A generic work target cannot replace a cell.
    roles = {'workhorse': (None, 2, True), 'analysis': (plan['analysis'], 2, True)}
    roles.update({f'participant-{n:02d}': (target, 1, False)
                  for n, target in enumerate(plan['participant_models'], 1)})
    for role, (target, minimum, judgement) in roles.items():
        floor = selected['profiles']['roles'].get(role, {})
        review.need(floor.get('minimum', -1) >= minimum and (not judgement or floor.get('judgement') is True),
                    'focus-group role floor missing: ' + role)
        chosen = models.dispatch(selected, role=role)
        if target is not None:
            review.need(chosen['execution'] == 'child' and equal_target(chosen['target'], target),
                        'selected role differs from approved matrix: ' + role)
    fidelity = [s for s in selected['review_panel'] if s['slot_id'] == 'fidelity']
    review.need(len(fidelity) == 1 and fidelity[0]['required'] and fidelity[0].get('independent', True),
                'required independent fidelity choice missing')
    floor = selected['profiles']['roles'].get(fidelity[0]['role'], {})
    review.need(floor.get('minimum', -1) >= 2 and floor.get('judgement') is True, 'fidelity judgement floor missing')
    chosen = models.dispatch(selected, role=fidelity[0]['role'], slot_id='fidelity')
    review.need(chosen['execution'] == 'child' and equal_target(chosen['target'], plan['review']),
                'fidelity choice differs from approved reviewer')
    return selected


def descriptor(study, revision):
    row = study.read(f'planning/{revision}/descriptor.json')
    review.need(isinstance(row, dict), 'study revision has no planning descriptor')
    return row


def validate_descriptor(desc):
    review.need(desc['kind'] == 'study-plan' and desc['requirements'] == REQUIREMENTS, 'study planning criteria differ')
    raw = strict_load(_regular(Path(desc['document']['path'])))
    plan = raw['plan']
    review.need(review.seal(plan)['sha256'] == desc['study_revision'], 'reviewed plan revision differs')
    review.need(Path(desc['document']['path']).parents[1].name == 'focus-group' and
                Path(desc['document']['path']).parents[2].name == plan['study_id'], 'study plan path differs')
    review.need(Path(desc['document']['path']).name == desc['study_revision'] + '.json', 'not an immutable study plan')
    choices(plan, desc['admission'])
    return plan


def ready(study, revision):
    desc = descriptor(study, revision)
    validate_descriptor(desc)
    return adopter.validate(desc, PKG)


def same_subject(desc, record):
    review.need(all(record[k] == desc['admission'][k] for k in ('scope_id', 'request_reference', 'output_name')),
                'run choices belong to another study planning subject')


def run_choice(study, revision):
    ready(study, revision)
    record = study.read(f'planning/{revision}/run.json')
    admission(record)
    same_subject(descriptor(study, revision), record)
    review.need(record['operation'] in ('run', 'resume'), 'run choices required before dependent panel work')
    choices(study.plan(revision)['plan'], record)
    return record


def task_binding(plan, record, task):
    selected = choices(plan, record)
    if task['worker_id'] == 'focus-group/participant':
        roles = [f'participant-{n:02d}' for n, target in enumerate(plan['participant_models'], 1)
                 if equal_target(target, task['target'])]
        review.need(len(roles) == 1, 'participant target outside selected matrix')
        binding = {'role': roles[0]}
    elif task['worker_id'] == 'focus-group/analyst':
        binding = {'role': 'analysis'}
    else:
        review.need(task['worker_id'] == 'focus-group/fidelity-reviewer' and task.get('role') == 'review',
                    'unknown focus-group worker')
        slot = next(s for s in selected['review_panel'] if s['slot_id'] == 'fidelity')
        binding = {'role': slot['role'], 'slot_id': 'fidelity'}
    return dict(binding, selection_sha256=selected['selection_sha256'])


def bind_job(job, plan, record):
    selected = choices(plan, record)
    for task in job['tasks']:
        task['selection_binding'] = task_binding(plan, record, task)
    for stage in job['stages']:
        stage.setdefault('resources', {}).update(focus_group_plan=job['focus_group_plan'], focus_group_admission=record)
    job.update(adopter_admission=record, model_selection=selected,
               model_selection_sha256=selected['selection_sha256'], invocation_id=record['invocation_id'],
               scope_id=record['scope_id'])
    job['policy']['model_selection_required'] = True
    return job


def validate_job(job, *, previous=None, creating=False):
    """Unconditional generic create/prepare/direct/accept callback, including legacy-shaped inputs."""
    review.need(job.get('policy', {}).get('model_selection_required') is True,
                'panel model selection policy is required')
    resources = [s.get('resources', {}) for s in job['stages']]
    record = admission(next((r.get('focus_group_admission') for r in resources if r.get('focus_group_admission')), job.get('adopter_admission')))
    review.need(record['operation'] in ('run', 'resume'), 'panel job requires run choices')
    selected = models.validate(job.get('model_selection'), job.get('model_selection_sha256'))
    review.need(selected == record['selection'] and job.get('invocation_id') == record['invocation_id'] and
                job.get('scope_id') == record['scope_id'], 'panel job selection/invocation/scope differs')
    desc = next((r.get('focus_group_plan') for r in resources if r.get('focus_group_plan')), job.get('focus_group_plan'))
    review.need(isinstance(desc, dict), 'reviewed study-plan descriptor required before panel work')
    plan = validate_descriptor(desc)
    review.need(plan['study_id'] == job['job_id'] and record['scope_id'] == desc['admission']['scope_id'] and
                record['request_reference'] == desc['admission']['request_reference'] and
                record['output_name'] == desc['admission']['output_name'], 'study/admission/subject transplant refused')
    review.need(all(r.get('focus_group_plan') == desc and r.get('focus_group_admission') == record for r in resources),
                'all panel stages need the same reviewed revision and choices')
    review.need(job['authorization'].get('study_revision') == desc['study_revision'], 'panel job revision differs')
    pin = next((job.get('pins', {}).get(d['key']) for d in job.get('dependencies', []) if d['plugin'] == 'focus-group'), None)
    adopter.validate(desc, Path(pin['package_dir']) if pin else PKG)
    choices(plan, record)
    from shared.job_coordinator import selection_for_task
    producing_fields = ('stage_id', 'logical_slot_id', 'worker_id', 'dependency_key',
                        'target', 'role', 'selection_binding')
    prior_tasks = {t['task_id']: t for t in (previous or {}).get('tasks', [])}
    for task in job['tasks']:
        prior = prior_tasks.get(task['task_id'])
        if creating or previous is not None and (prior is None or
                any(task.get(k) != prior.get(k) for k in producing_fields)):
            review.need(task.get('selection_binding', {}).get('selection_sha256') == selected['selection_sha256'],
                        'new or changed panel slot requires current choices')
        # Retired/live slots can retain their producing selection after a revision.
        if task.get('selection_binding', {}).get('selection_sha256') == selected['selection_sha256']:
            review.need(task['selection_binding'] == task_binding(plan, record, task), 'panel slot role/choice differs')
        selection_for_task(dict(job, policy=dict(job.get('policy', {}), model_selection_required=True)), task)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('admit', 'continue', 'dispatch', 'prepare', 'attach', 'validate', 'run'))
    parser.add_argument('--input', required=True)
    args = parser.parse_args(argv)
    try:
        data = strict_load(_regular(Path(args.input)))
        if args.command == 'admit':
            out = adopter.admit('focus-group', data)
        elif args.command == 'continue':
            out = adopter.continuation(data['admission'], **{k:v for k,v in data.items() if k != 'admission'})
        elif args.command == 'dispatch':
            out = adopter.dispatch(data['admission'], **{k:v for k,v in data.items() if k != 'admission'})
        else:
            # Imported lazily: generic registry validation needs no study runtime or mutable state.
            sys.path.insert(0, str(PKG / 'scripts'))
            import study as fg
            study = fg.Study(data['state_root'], data['study'])
            revision = study.require()['revision']
            desc = descriptor(study, revision)
            if args.command == 'run':
                ready(study, revision)
                record = admission(data['admission'])
                same_subject(desc, record)
                review.need(record['operation'] in ('run', 'resume'), 'run/resume admission required')
                if record['operation'] == 'resume':
                    adopter.continuation(record, invocation_id=record['invocation_id'], event='resume', retain=data.get('retain'))
                choices(study.plan(revision)['plan'], record)
                with study.locked():
                    study.write(f'planning/{revision}/run.json', record)
                out = {'selection_sha256': record['selection_sha256'], 'dispatched': 0}
            elif args.command == 'prepare':
                out = adopter.prepare(desc, data['inputs'], data['metadata_file'], PKG)
            elif args.command == 'attach':
                out = adopter.attach(desc, data['metadata_file'], data['receipt'], PKG)
                desc['planning_review'] = out['metadata']
                with study.locked():
                    study.write(f'planning/{revision}/descriptor.json', desc)
            else:
                out = ready(study, revision)
        print(json.dumps(out, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError, StopIteration) as exc:
        print('focus_group_planning_error: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
