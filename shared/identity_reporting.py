"""Read-only identity summaries from recorded host observations."""
import json
from pathlib import Path


def recorded_identity_reporting(jobs_state_root):
    """Summarise saved observations without consulting or launching a host."""
    unreported, known, observed = set(), set(), set()
    try:
        files = sorted(Path(jobs_state_root).glob('*/job.json'))
    except OSError:
        files = []
    for path in files:
        try:
            if path.stat().st_size > 16 * 1024 * 1024: continue
            job = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError): continue
        if not isinstance(job, dict): continue
        tasks = list(job.get('tasks', []))
        for historic in job.get('history', []):
            if isinstance(historic, dict): tasks.extend(historic.get('tasks', []))
        for task in tasks:
            if not isinstance(task, dict): continue
            target = task.get('target')
            if isinstance(target, dict) and isinstance(target.get('providerInstanceId'), str):
                known.add(target['providerInstanceId'])
            records = [r for key in ('handles', 'followups', 'execution_history', 'dispatch_history', 'host_conflicts')
                       for r in task.get(key, [])]
            for record in records:
                identity = record.get('observed_identity') if isinstance(record, dict) else None
                if not isinstance(identity, dict): continue
                provider = identity.get('providerInstanceId')
                if not isinstance(provider, str) or not provider: continue
                observed.add(provider)
                if identity.get('status') == 'unreported' and not identity.get('model'):
                    unreported.add(provider)
    return {'source': 'recorded host observations only', 'providers_with_unreported_model': sorted(unreported),
            'identity_reporting_unverified': sorted(known - observed), 'launches_nothing': True}
