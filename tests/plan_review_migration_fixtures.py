"""Migrate historical acceptance regressions through real public planning contracts."""
import json
from pathlib import Path
from types import SimpleNamespace

from tests.ape_plan_review_fixtures import select_legacy_ape_fixture, review_legacy_ape_fixture


def admit_ape(job, base, state_root, data):
    select_legacy_ape_fixture(job, base, state_root)
    job['stages'][0]['outputs'] = [data['report']['path']]
    return job


def review_ape(package, manifest, state_root, job_id, stage_id, data, base, env=None):
    import os
    ins = SimpleNamespace(version=Path(package), manifest=manifest, state=Path(state_root),
        prefix=Path(package).parents[1], agents=Path(manifest['bundle_dir']).parents[3],
        base=Path(base), env=dict(os.environ if env is None else env))
    # The public planning runtime stores the subject under the same private XDG root
    # for the producer and validator; never use the operator's state in fixtures.
    ins.env.update(HOME=str(Path(base)/'home'), XDG_STATE_HOME=str(Path(state_root)),
                   XDG_CONFIG_HOME=str(Path(base)/'config'), PYTHONDONTWRITEBYTECODE='1')
    from itertools import count
    inputs = count()
    def write(label, value):
        path = ins.base / (label + '-' + str(next(inputs)) + '.json')
        path.write_text(json.dumps(value))
        return path
    ins.write = write
    # Subsequent in-process acceptance starts the installed validator with this
    # fixture process environment. Match its subject locator, never owner state.
    os.environ['XDG_STATE_HOME'] = str(state_root)
    return review_legacy_ape_fixture(ins, job_id, stage_id, data)


def observe_direct_ape(box, package, job_id, caller, stage_id):
    from copy import deepcopy
    selected = box.state_of(job_id)['model_selection']
    caps = deepcopy(selected['capabilities'])
    caps.update(parentThreadId='fixture-parent', inheritedProviderInstanceId=selected['coordinator']['providerInstanceId'],
                inheritedModel=selected['coordinator']['model'], inheritedOptions=selected['coordinator'].get('observed_options', {}))
    box.job(package, 'direct-execution', job_id, {'caller':caller,'stage_id':stage_id},
            extra=('--capabilities', box.payload(caps)))
