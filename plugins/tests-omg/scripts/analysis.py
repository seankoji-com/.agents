"""Calculations over declared evidence. No repository execution or model client."""
from __future__ import annotations

import math
import random
import re
from datetime import datetime, timezone

VERSION = '1.0'
DIMENSIONS = [
    'Critical behavior', 'Wallclock', 'Flakiness/retries', 'Coverage',
    'Detection usefulness', 'Learning from bugs', 'Real boundaries',
    'Adverse conditions', 'Reproducibility', 'Cost/maintenance', 'PR evidence', 'CI integrity',
]
PROFILES = {
    'web-services': ['HTTP contracts', 'tenant isolation', 'browser journeys', 'accessibility'],
    'native-mobile-wearable': ['device lifecycle', 'offline state', 'permissions', 'packaging'],
    'cli-tui-shell': ['exit codes', 'terminal and pipe contracts', 'signals', 'quoting'],
    'agent-plugins': ['authorization', 'installed relocation', 'model and host boundaries'],
    'financial-data': ['rounding', 'calendar dates', 'idempotency', 'reconciliation'],
    'cms': ['content permissions', 'rendering', 'migration', 'cache invalidation'],
    'packaging': ['installed artifact', 'dependency resolution', 'upgrade and rollback'],
    'infrastructure-recovery': ['least privilege', 'partial failure', 'restore', 'owned cleanup'],
}


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def percentile(values, p):
    """Nearest rank: sorted[ceil(p*n)-1]. Retain all outliers separately."""
    if not values:
        return None
    rank = max(1, math.ceil(p * len(values)))
    return {'seconds': sorted(values)[rank - 1], 'rank': rank, 'n': len(values),
            'method': 'nearest-rank ceil(p*n)',
            'small_sample_warning': len(values) - rank <= 1}


def timing(run):
    if run.get('observed_seconds') is not None and not number(run['observed_seconds']):
        raise ValueError('invalid observed duration')
    result = {'run_id': run.get('id'), 'attempt': run.get('attempt'),
              'outcome': run.get('outcome', 'unknown'),
              'observed_seconds': run.get('observed_seconds'),
              'available_seconds': None, 'estimate': True, 'limitations': [],
              'capacity': run.get('capacity', {}), 'runner_minutes': None,
              'phases': {}, 'other_merge_blockers': run.get('other_merge_blockers', []),
              'loop_seconds': run.get('loop_seconds'),
              'capacity_waits': run.get('capacity_waits'), 'runner_class': run.get('runner_class'),
              'setup_temperature': run.get('setup_temperature'), 'queue_intervals': run.get('queue_intervals', [])}
    nodes = run.get('nodes', [])
    result['lower_bound_seconds'] = max((n['duration'] for n in nodes if number(n.get('duration'))), default=0)
    capacities = run.get('capacity', {})
    if not nodes or not capacities or run.get('graph_complete') is not True:
        result['limitations'].append('Complete retained-check dependency graph and numeric capacity required.')
        return result
    if len(nodes) > 2000:
        result['limitations'].append('Timing graph exceeds the 2000-node calculation budget; normalize or partition evidence without dropping dependencies.')
        return result
    if run.get('ready_metadata') is not True:
        result['limitations'].append('Ready/start metadata missing; capacity waits cannot be separated reliably.')
    by_id = {n['id']: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError('duplicate timing node')
    for pool, workers in capacities.items():
        if type(workers) is not int or not 1 <= workers <= 1024:
            raise ValueError('capacity workers must be integers 1..1024')
    for n in nodes:
        if not number(n.get('duration')) or n.get('pool') not in capacities:
            result['limitations'].append('Unknown dependency duration or runner pool.')
            return result
        if any(dep not in by_id for dep in n.get('needs', [])):
            result['limitations'].append('Unknown cross-workflow/repository dependency.')
            return result
    # A deterministic list schedule. Pool lanes impose actual capacity limits;
    # explicit needs encode serialization/matrix batches and reporting dependencies.
    demand = {}
    for n in nodes:
        demand[n['pool']] = demand.get(n['pool'], 0) + 1
    # Never allocate unused advertised workers: total lanes cannot exceed nodes.
    lanes = {pool: [0.0] * min(capacities[pool], count) for pool, count in demand.items()}
    finish, schedule, remaining = {}, [], dict(by_id)
    while remaining:
        ready = [n for n in remaining.values() if all(d in finish for d in n.get('needs', []))]
        if not ready:
            raise ValueError('cyclic timing DAG')
        def start(n):
            return max(max((finish[d] for d in n.get('needs', [])), default=0), min(lanes[n['pool']]))
        n = min(ready, key=lambda n: (start(n), n['id']))
        pool = lanes[n['pool']]
        lane = min(range(len(pool)), key=pool.__getitem__)
        begin = start(n)
        finish[n['id']] = pool[lane] = begin + n['duration']
        schedule.append({'id': n['id'], 'start': begin, 'finish': finish[n['id']],
                         'pool': n['pool'], 'lane': lane})
        phase = n.get('phase', 'unspecified')
        result['phases'][phase] = result['phases'].get(phase, 0) + n['duration']
        del remaining[n['id']]
    result.update(modelled_seconds=max(finish.values()), schedule=schedule,
                  lower_bound_seconds=max(n['duration'] for n in nodes),
                  runner_minutes=sum(n['duration'] for n in nodes) / 60,
                  required_pool=capacities)
    if not result['limitations']:
        result['available_seconds'] = result['modelled_seconds']
    return result


def sample(groups, seed, random_count=2):
    """All named consequential strata plus a reproducible random remainder."""
    if type(random_count) is not int or not 0 <= random_count <= 100:
        raise ValueError('random sample count must be 0..100')
    selected = {g['id'] for g in groups if set(g.get('tags', [])) &
                {'critical', 'changed', 'bug-prone', 'flaky', 'slow'}}
    rest = sorted(g['id'] for g in groups if g['id'] not in selected)
    random_ids = random.Random(str(seed)).sample(rest, min(random_count, len(rest)))
    return {'seed': str(seed), 'rule': 'all critical/changed/bug-prone/flaky/slow + seeded random remainder',
            'selected': sorted(selected | set(random_ids)), 'random': random_ids,
            'population': len(groups), 'random_count': random_count}


def base_finding(i, stamp, revision):
    return {'id': f'TEST-{i:02}', 'dimension': DIMENSIONS[i - 1], 'state': 'unknown',
            'reason': 'Evidence has not established this dimension.', 'evidence': [],
            'evidence_date': stamp, 'revision': revision, 'run_attempts': [],
            'scope': 'inspected snapshot only', 'confidence': 'low',
            'consequence': 'Material protection remains unverified.', 'owner': 'repository owner',
            'next_action': 'Inspect applicable critical behavior and collect the smallest useful evidence.',
            'exceptions': []}


def recommendations(groups, refs, comparisons):
    rows = []
    comparisons_by_group = {c['group']: c for c in comparisons}
    if len(comparisons_by_group) != len(comparisons):
        raise ValueError('duplicate comparison group')
    for g in groups:
        row = dict(g)
        row.setdefault('assessment_state', 'needs_evidence')
        row.setdefault('action', None)
        row.setdefault('protection_retained', [])
        row.setdefault('protection_lost', [])
        row.setdefault('owner', 'repository owner')
        row.setdefault('unresolved_claim', 'Distinct detection value has not been established.')
        row.setdefault('next_experiment', 'Inspect a critical failure and its independent oracle.')
        row.setdefault('evidence', [])
        if row['action'] not in (None, 'keep', 'simplify', 'replace', 'delete'):
            raise ValueError('invalid recommendation action')
        if row['assessment_state'] not in ('supported', 'needs_evidence'):
            raise ValueError('invalid assessment_state')
        if any(ref not in refs for ref in row['evidence']):
            raise ValueError('unknown recommendation evidence reference')
        # These are not measurable universal targets. Nor can deferral satisfy
        # removal of low-value checks from the pre-merge assurance set.
        prose = ' '.join(str(row.get(k, '')) for k in ('rationale', 'next_experiment', 'savings', 'proposal'))
        if re.search(r'80\s*/\s*20|80\s*(?:%|percent)\s*(?:of\s+(?:the\s+)?)?(?:value|protection|safety)|'
                     r'(?:value|protection|safety)[^.!?]*80\s*(?:%|percent)', prose, re.I):
            raise ValueError('invented 80/20 protection claim')
        if re.search(r'\b(?:move|shift|relocate|run|defer|schedule|make|keep|offload)\b[^.!?]*\b(?:nightly|post.merge|background|optional slow)\b|'
                     r'\b(?:nightly|post.merge|background|optional)\s+(?:slow\s+)?(?:suite|tests?|checks?|job)\b|'
                     r'\bdefer[^.!?]*suite\b', prose, re.I):
            raise ValueError('slow-suite deferral is not a removal recommendation')
        supported = row['assessment_state'] == 'supported'
        required = ('failure', 'consequence', 'boundary', 'oracle', 'distinct_protection',
                    'rationale', 'maintenance', 'owner')
        if supported and (not row['evidence'] or any(not row.get(k) for k in required)):
            raise ValueError('supported value claim needs evidence, boundary, oracle, consequence and upkeep')
        if supported and row['action'] is None:
            raise ValueError('supported recommendation needs an action')
        if supported and row['action'] in ('keep', 'simplify', 'replace') and not row['protection_retained']:
            raise ValueError('supported retention needs named protection cases')
        if row['action'] is None and any(not row.get(k) for k in ('unresolved_claim', 'owner', 'next_experiment')):
            raise ValueError('null action needs unresolved claim, owner and next experiment')
        if not supported and row['action'] is not None:
            raise ValueError('unsupported value claim must leave action null')
        if row['action'] in ('replace', 'delete'):
            comparison = comparisons_by_group.get(row['id'])
            if row['action'] == 'replace' and not comparison:
                raise ValueError('replacement requires same-corpus comparison')
            if row['action'] == 'delete' and row.get('basis') not in ('obvious-tautology', 'dead-feature', 'confirmed-duplication'):
                raise ValueError('deletion needs direct inspection or confirmed duplication')
            if row.get('basis') == 'confirmed-duplication' and not row.get('independent_boundary_analysis'):
                raise ValueError('same lines do not establish duplicate protection')
            if comparison:
                if not comparison.get('same_corpus') or not comparison.get('same_environment'):
                    raise ValueError('incompatible comparison')
                cases = comparison.get('cases', [])
                if not cases:
                    raise ValueError('comparison has no named failure cases')
                outcomes = {'detected', 'missed', 'unknown', 'equivalent', 'build-error', 'timeout'}
                if (len({c['id'] for c in cases}) != len(cases) or
                        any(not c.get('risk') or c.get('existing') not in outcomes or
                            c.get('candidate') not in outcomes for c in cases)):
                    raise ValueError('comparison needs unique named cases, risk and explicit outcomes')
                lost = [c['id'] for c in cases if c.get('existing') == 'detected' and c.get('candidate') != 'detected']
                unknown = [c['id'] for c in cases if c.get('candidate') in ('unknown', 'equivalent', 'build-error', 'timeout') or
                           c.get('existing') in ('unknown', 'equivalent', 'build-error', 'timeout')]
                row['comparison'] = comparison
                row['protection_lost'] = sorted(set(row['protection_lost']) | set(lost))
                row['protection_retained'] = [c['id'] for c in cases if c.get('existing') == c.get('candidate') == 'detected']
                costs = ('existing_seconds', 'candidate_seconds', 'existing_runner_minutes', 'candidate_runner_minutes')
                if lost or unknown or not row['protection_retained'] or any(not number(comparison.get(k)) for k in costs):
                    row.update(assessment_state='needs_evidence', action=None,
                               unresolved_claim='Candidate detection or cost remains unsupported. Lost/unknown cases: ' + ', '.join(sorted(set(lost + unknown))),
                               next_experiment='Repair the candidate and compare named protection, elapsed time and compute on the same corpus and environments again.')
        rows.append(row)
    # Ranking is the coordinator's explicit priority, never a weighted safety score.
    return sorted(rows, key=lambda r: (r.get('priority', 999), r['id']))


def evidence_rejections(evidence, snapshot):
    """Binding failures, distinct from an advisory with no measured inputs.

    Also usable on saved input without recalculating or upgrading its findings.
    """
    identity = evidence.get('identity', {})
    claims = 'identity' in evidence or any(evidence.get(k) for k in
        ('artifacts', 'checks', 'runs', 'findings', 'coverage', 'groups', 'comparisons', 'inspected_groups'))
    rejected = []
    if claims and (identity.get('head_sha') != snapshot['head_sha'] or
                   identity.get('snapshot_sha256') != snapshot['sha256']):
        rejected.append('source_binding_mismatch')
    if (any(any(a.get(k) != identity.get(k) for k in
                ('head_sha', 'tested_sha', 'run_id', 'attempt', 'environment', 'config_version'))
            for a in evidence.get('artifacts', [])) or
            any(any(k in c and c[k] != identity.get(k) for k in
                    ('head_sha', 'tested_sha', 'environment', 'config_version'))
                for c in evidence.get('checks', []))):
        rejected.append('artifact_identity_mismatch')
    return rejected


def analyze(evidence, snapshot, stamp):
    findings = [base_finding(i, stamp, snapshot['head_sha']) for i in range(1, 13)]
    def setf(i, state, reason, refs=()):
        findings[i - 1].update(state=state, reason=reason, evidence=list(refs))
    refs = {r['id']: r for r in evidence.get('references', [])}
    if len(refs) != len(evidence.get('references', [])):
        raise ValueError('duplicate evidence reference')
    unavailable = []
    for ref in refs.values():
        if not ref.get('observed_at') or not ref.get('source'):
            raise ValueError('evidence references need date and source')
        if ref.get('expires_at') and datetime.fromisoformat(ref['expires_at'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            unavailable.append(ref['id'])
        if ref.get('available') is False:
            unavailable.append(ref['id'])
    identity = evidence.get('identity', {})
    current = identity.get('head_sha') == snapshot['head_sha'] and identity.get('snapshot_sha256') == snapshot['sha256']
    tested = identity.get('tested_sha')
    rejected = evidence_rejections(evidence, snapshot)
    mixed = 'artifact_identity_mismatch' in rejected
    valid = current and not mixed and not snapshot.get('limitations')
    limitations = list(snapshot.get('limitations', []))
    if not current:
        limitations.append('Input evidence is not bound to this source snapshot; all input conclusions are unavailable.')
    if mixed:
        limitations.append('Mixed artifact revision/run/attempt/environment/config identities; aggregation rejected.')
    if unavailable:
        limitations.append('Unavailable or expired diagnostics: ' + ', '.join(sorted(set(unavailable))))
    usable_refs = {k: v for k, v in refs.items() if k not in unavailable}
    def supported(item):
        return not any(ref not in usable_refs for ref in item.get('evidence', []))
    groups = evidence.get('groups', [])
    if len({g['id'] for g in groups}) != len(groups):
        raise ValueError('duplicate check group')
    if set(evidence.get('inspected_groups', [])) - {g['id'] for g in groups}:
        raise ValueError('inspected group is outside declared sample population')
    finding_ids = set()
    for j in evidence.get('findings', []):
        if not re.fullmatch(r'TEST-(?:0[1-9]|1[0-2])', str(j.get('id'))) or j['id'] in finding_ids:
            raise ValueError('invalid or duplicate finding ID')
        finding_ids.add(j['id'])
        i = int(j['id'].removeprefix('TEST-'))
        if not 1 <= i <= 12 or j.get('state') not in ('meets', 'gap', 'unknown', 'not_applicable'):
            raise ValueError('invalid finding ID/state')
        for key in ('reason', 'evidence', 'confidence', 'consequence', 'owner', 'next_action'):
            if key not in j or not j[key]:
                raise ValueError('finding missing ' + key)
        if any(r not in refs for r in j['evidence']):
            raise ValueError('unknown finding evidence reference')
        for exception in j.get('exceptions', []):
            if any(not exception.get(k) for k in ('owner', 'reason', 'evidence', 'expires_at')):
                raise ValueError('exception missing owner/reason/compensating evidence/expiry')
        if j.get('revision', snapshot['head_sha']) != snapshot['head_sha']:
            raise ValueError('finding revision differs from inspected snapshot')
        if valid and supported(j) and all(supported(x) for x in j.get('exceptions', [])):
            findings[i - 1].update(j)
            findings[i - 1]['dimension'] = DIMENSIONS[i - 1]
    runs = [timing(r) for r in evidence.get('runs', []) if supported(r)] if valid else []
    values = [r['available_seconds'] for r in runs if r['available_seconds'] is not None]
    observed = [r['observed_seconds'] for r in runs if number(r['observed_seconds'])]
    breaches = [r for r in runs if (r['available_seconds'] is not None and r['available_seconds'] > 600)
                or (number(r.get('modelled_seconds')) and r['modelled_seconds'] > 600)
                or r.get('lower_bound_seconds', 0) > 600]
    observed_breaches = [r for r in runs if number(r['observed_seconds']) and r['observed_seconds'] > 600]
    time_summary = {'target_seconds': 600, 'decision_rule': 'T_available <= 600s',
                    'runs': runs, 'available_p50': percentile(values, .5), 'available_p95': percentile(values, .95),
                    'observed_p50': percentile(observed, .5), 'observed_p95': percentile(observed, .95),
                    'breaches': breaches, 'observed_breaches': observed_breaches,
                    'all_outcomes_retained': True}
    if breaches:
        setf(2, 'gap', 'A retained dependency path exceeds 600 seconds. Optimize without weakening protection or deferring checks.')
    elif runs and len(values) == len(runs):
        setf(2, 'meets', 'All sampled capacity-adjusted estimates meet 600 seconds; these are estimates, not measured available-capacity runs.')
    elif findings[1]['state'] != 'gap':
        setf(2, 'unknown', 'Incomplete timing dependencies or ready/start metadata prevent a complete capacity-adjusted claim.')
    attempts = [c for c in evidence.get('checks', []) if supported(c)] if valid else []
    keys = set()
    counts = dict(first_attempt_passes=0, retry_passes=0, failures=0, skipped=0,
                  quarantined=0, incomplete=0)
    per_test, grouped = {}, {}
    for c in attempts:
        if (any(not isinstance(c.get(k), str) or not c[k].strip() or ':' in c[k] for k in ('check', 'shard')) or
                type(c.get('discovered', 0)) is not int or
                c.get('discovered', 0) < 0):
            raise ValueError('check/shard IDs must be nonempty strings without colons, with nonnegative discovery counts')
        key = (c['check'], c['shard'], c['attempt'])
        if key in keys or type(c['attempt']) is not int or c['attempt'] < 1:
            raise ValueError('duplicate check/shard attempt or invalid attempt')
        keys.add(key)
        grouped.setdefault((c['check'], c['shard']), []).append(c)
        for t in c.get('tests', []):
            if any(k in t and t[k] != value for k, value in
                   {'check': c['check'], 'shard': c['shard'], 'attempt': c['attempt'], 'test': t['id']}.items()):
                raise ValueError('per-test identity differs from containing check attempt')
            tk = (c['check'], c['shard'], t['id'])
            if (tk, c['attempt']) in per_test:
                raise ValueError('duplicate per-test attempt')
            per_test[(tk, c['attempt'])] = t
    intermittent = []
    completed = []
    incomplete_attempt_history = []
    for key, cs in grouped.items():
        cs.sort(key=lambda c: c['attempt'])
        first, last = cs[0], cs[-1]
        complete_attempts = len(cs) == last['attempt'] and first['attempt'] == 1
        if not complete_attempts:
            incomplete_attempt_history.append(':'.join(key))
        clean_tests = all(t.get('outcome') == 'pass' for t in last.get('tests', []))
        if (last.get('outcome') == 'pass' and last.get('report_complete') is True and
                last.get('discovered', 0) > 0 and not last.get('quarantined') and not last.get('skipped_tests') and
                complete_attempts and clean_tests):
            completed.append(':'.join(key))
        if any(c.get('outcome') == 'fail' for c in cs[:-1]) and last.get('outcome') == 'pass':
            intermittent.append({'check': key[0], 'shard': key[1], 'attempts': cs,
                                 'disposition': last.get('disposition', 'open')})
        if first.get('outcome') == 'pass' and first['attempt'] == 1:
            counts['first_attempt_passes'] += 1
        elif last.get('outcome') == 'pass':
            counts['retry_passes'] += 1
        for c in cs:
            if c.get('outcome') == 'fail': counts['failures'] += 1
            if c.get('outcome') == 'skipped': counts['skipped'] += 1
            if c.get('quarantined'): counts['quarantined'] += 1
            if c.get('outcome') not in ('pass', 'fail', 'skipped'): counts['incomplete'] += 1
    def repaired(item):
        repair = item['attempts'][-1].get('repair_evidence', [])
        return (item['disposition'] == 'fixed' and isinstance(repair, list) and bool(repair) and
                all(ref in usable_refs for ref in repair))
    open_failures = [x for x in intermittent if not repaired(x)]
    if open_failures or any(c.get('outcome') == 'fail' for c in attempts):
        setf(3, 'gap' if open_failures or any(cs[-1].get('outcome') == 'fail' for cs in grouped.values()) else 'unknown',
             'Original failures and all attempts retained. Cause labels and retry success do not establish a repair.')
    elif attempts:
        setf(3, 'unknown', 'No failure in this sample establishes neither zero nondeterminism nor complete history.')
    expected = evidence.get('expected_checks')
    collected = sorted(':'.join(k) for k in grouped)
    missing = sorted(set(expected or []) - set(completed))
    if expected is not None and (not isinstance(expected, list) or len(expected) != len(set(expected))):
        raise ValueError('expected check identities must be a unique list')
    integrity_gap = expected == [] or bool(missing) or bool(incomplete_attempt_history) or bool(expected is not None and set(collected) - set(expected)) or any(
        c.get('discovered', 0) == 0 or c.get('outcome') != 'pass' or c.get('quarantined') or
        c.get('skipped_tests', 0) or not c.get('report_complete') or
        any(t.get('outcome') != 'pass' for t in c.get('tests', [])) for c in [cs[-1] for cs in grouped.values()])
    if incomplete_attempt_history:
        limitations.append('Missing first/intermediate check attempts: ' + ', '.join(incomplete_attempt_history))
    verdict = 'unknown'
    if not valid:
        setf(11, 'gap' if mixed else 'unknown', 'Stale, missing or expired input/artifact identity; current evidence rejected.')
    elif not tested or any(not identity.get(k) for k in ('run_id', 'attempt', 'environment', 'tool_versions', 'config_version')):
        setf(11, 'unknown', 'Head/tested SHA, attempt, environment and tools must identify the report inputs.')
    else:
        if findings[10]['state'] != 'gap':
            setf(11, 'meets', 'Current snapshot-bound local HTML/JSON identifies the tested SHA, run/attempt, environment and tools. Publication is separately authorized.')
        limitations.append('Authenticated download and current-head PR summary delivery remain unverified; local report generation grants no publication authority.')
    if valid and integrity_gap:
        setf(12, 'gap', 'Zero discovery, missing retained shard, failed/skipped/quarantined/incomplete check or required report. Wrapper success is insufficient.')
        verdict = 'incomplete'
    elif valid and expected and set(expected) == set(collected) == set(completed) and evidence.get('assurance_set_complete') is True:
        setf(12, 'meets', 'Declared retained checks and shards completed with required reports before merge; branch-rule enforcement is separate.')
        verdict = 'complete'
    elif findings[11]['state'] != 'gap':
        setf(12, 'unknown', 'Current complete assurance-set discovery and all retained shard outcomes are required.')
    coverage = evidence.get('coverage', {}) if valid else {}
    if coverage and not supported(coverage):
        coverage = {}
        note = 'Coverage supporting evidence expired or unavailable; revalidation required.'
        findings[3]['coverage_comparison'] = {'state': 'unknown', 'reason': note}
        if findings[3]['state'] != 'gap':
            setf(4, 'unknown', note)
    if coverage:
        fields = ('tool', 'version', 'unit', 'source_inventory', 'exclusions', 'uninstrumented',
                  'generated_vendored', 'identity_policy', 'counts', 'revision')
        compatible = coverage.get('revision') == tested and all(k in coverage for k in fields)
        baseline = coverage.get('baseline', {})
        comparison_ok = bool(baseline and baseline.get('compatible') is True and
                             baseline.get('base_sha') == identity.get('comparison_base') and
                             baseline.get('policy') and baseline.get('instrumentation') == coverage.get('instrumentation'))
        note = ('Compatible named baseline.' if compatible and comparison_ok else
                'Missing/incompatible denominator, shard union identity or base comparison; comparison unknown.')
        findings[3]['coverage_comparison'] = {'state': 'compatible' if compatible and comparison_ok else 'unknown', 'reason': note}
        if findings[3]['state'] == 'unknown' or (findings[3]['state'] == 'meets' and not (compatible and comparison_ok)):
            setf(4, 'unknown', 'Coverage execution counts are recorded; critical uncovered decisions still need inspection. ' + note)
    recs = recommendations(groups, refs, evidence.get('comparisons', [])) if valid else []
    for row in recs:
        comparison = row.get('comparison', {})
        if ((row['assessment_state'] == 'supported' and row['id'] not in evidence.get('inspected_groups', []))
                or not supported(row) or not supported(comparison)):
            row.update(assessment_state='needs_evidence', action=None,
                       unresolved_claim='Group not inspected or supporting evidence unavailable; detection claim requires revalidation.',
                       next_experiment='Inspect this group and collect current evidence for its named failure cases and independent oracle.')
    lost = [r for r in recs if r['protection_lost']]
    if lost:
        for i in (5, 10):
            setf(i, 'gap', 'Proposed smaller suite loses or cannot establish named protection; replacement unsupported.')
            findings[i - 1]['comparison_evidence'] = lost
    history = {'run_window_days': 30, 'incident_window_days': 90, 'other_fix_limit': 10,
               'selection_rule': 'severe/repeated incidents and up to ten other recent fixes; inaccessible history stays unknown',
               **evidence.get('history', {})}
    if not history.get('bugs_accessible'):
        setf(6, 'unknown', 'No accessible incident/fix history. This is not evidence of no escaped bugs.')
    if not history.get('runs_complete'):
        limitations.append('Run/job/attempt history incomplete; no complete-history reliability or timing claim.')
    if snapshot['limitations']:
        limitations.append('Source inventory incomplete; affected conclusions require revalidation.')
        for f in findings:
            if f['state'] == 'meets': f.update(state='unknown', reason='Incomplete inspected source inventory. ' + f['reason'])
    for f in findings:
        f['run_attempts'] = [{'run': r.get('id'), 'attempt': r.get('attempt')} for r in evidence.get('runs', [])]
    affected = {x['check'] for x in intermittent}
    sampling = sample(evidence.get('groups', []), snapshot['sha256'])
    sampling['inspected'] = sorted(evidence.get('inspected_groups', [])) if valid else []
    sampling['omitted'] = sorted(set(sampling['selected']) - set(sampling['inspected']))
    if sampling['omitted']:
        limitations.append('Selected test-value sample not inspected: ' + ', '.join(sampling['omitted']))
    return {'findings': findings, 'timing': time_summary, 'recommendations': recs,
            'validation_verdict': verdict, 'counts': counts,
            'count_units': 'unique check:shard first/retry passes; failure/skip/incomplete/quarantine attempts; quarantine is a subset',
            'per_test_attempts': [{**v, 'check': k[0][0], 'shard': k[0][1], 'test': k[0][2], 'attempt': k[1]}
                                  for k, v in per_test.items()],
            'intermittent': intermittent, 'expected_checks': expected, 'collected_checks': collected,
            'affected_suite_count': len(affected), 'affected_suites': sorted(affected),
            'completed_checks': sorted(completed), 'missing_checks': missing,
            'coverage': coverage, 'limitations': limitations,
            'sample': sampling,
            'history': history, 'evidence_current': valid, 'evidence_rejections': rejected}
