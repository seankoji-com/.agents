#!/usr/bin/env python3
"""Validate report-first audit criteria and distinct parse, load and enforcement evidence."""
import argparse, hashlib, json, re, sys
from pathlib import Path
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p/'shared/adopter_planning.py').is_file())))
from shared.validator_observations import read_object, observation, emit
from core.jobs.store import _regular

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    args = parser.parse_args()
    try:
        data, sha = read_object(args.input)
        findings, changes = data['findings'], data['changes']
        criteria = data['criteria']
        if not isinstance(findings, list) or any(not isinstance(f, dict) or not f.get('code') or not f.get('location') for f in findings):
            raise ValueError('audit findings are malformed')
        if not isinstance(criteria, dict) or criteria.get('operation') not in ('audit', 'apply'):
            raise ValueError('explicit audit/apply criteria are required')
        if data.get('audit_exit_code') not in (0, 1) or data.get('audit_exit_code') == 1 and not criteria.get('findings_allowed'):
            raise ValueError('audit result does not meet the task exit-code criteria')
        if not isinstance(changes, list) or criteria['operation'] == 'audit' and changes:
            raise ValueError('report-only audit cannot accept settings changes')
        if criteria['operation'] == 'apply' and not changes and criteria.get('allow_noop_apply') is not True:
            raise ValueError('apply requires a recorded change or explicit no-op criteria')
        if criteria['operation'] == 'apply':
            from shared.adopter_planning import apply_ready
            apply_ready(data['apply_context'], data['applied_plan'], Path(__file__).resolve().parents[1])
        for change in changes:
            if not isinstance(change, dict) or not change.get('authorization_ref') or len(change.get('backup_sha256', '')) != 64:
                raise ValueError('settings change lacks authorization or backup')
            owner = next((d for d in data.get('authorization_records', []) if d.get('id') == change['authorization_ref']), None)
            if not owner or owner.get('scope') != 'settings-change:' + str(change.get('id', '')) or not owner.get('quote') or not owner.get('source') or not re.fullmatch(r'[0-9a-f]{64}', str(owner.get('source_sha256', ''))):
                raise ValueError('settings change lacks its recorded scoped owner authorization')
            backup, before = Path(change['backup_path']), Path(change['before_path'])
            if not backup.is_absolute() or not before.is_absolute():
                raise ValueError('settings backup and before-edit snapshot paths must be absolute')
            backup_raw, before_raw = _regular(backup), _regular(before)
            if backup_raw != before_raw or hashlib.sha256(backup_raw).hexdigest() != change['backup_sha256'] or hashlib.sha256(before_raw).hexdigest() != change['before_sha256']:
                raise ValueError('actual backup differs from the bound before-edit bytes')
            if criteria['operation'] == 'apply':
                plan = data['applied_plan']
                if hashlib.sha256(before_raw).hexdigest() != plan['before_sha256'] or hashlib.sha256(_regular(Path(plan['target']))).hexdigest() != plan['after_sha256']:
                    raise ValueError('applied target or rollback bytes differ from reviewed plan')
            content = observation(change.get('observation'), 'settings-change')
            for field in ('authorization_ref', 'backup_sha256', 'backup_path', 'before_path', 'before_sha256', 'parse_result', 'load_result', 'enforcement_result'):
                if content.get(field) != change.get(field):
                    raise ValueError('settings observation does not bind the claimed result')
            if change.get('parse_result') != 'passed' or change.get('load_result') != 'passed':
                raise ValueError('parse or load failed')
            if change.get('enforcement_required') and change.get('enforcement_result') != 'passed':
                raise ValueError('required live enforcement is unverified')
        if criteria.get('live_enforcement_required'):
            observed = observation(data.get('live_observation'), 'live-enforcement')
            if observed.get('result') != 'passed':
                raise ValueError('required live enforcement failed')
        if data.get('adopter_output'):
            from shared.adopter_planning import validate_observation
            validate_observation(data, data['adopter_output'], Path(__file__).resolve().parents[1])
        result = emit(True, 'audit-criteria', {'input': args.input, 'sha256': sha},
                      findings_count=len(findings), live_enforcement='observed' if criteria.get('live_enforcement_required') else 'not-required')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = emit(False, 'audit-criteria', {'reason': str(exc)})
    print(json.dumps(result, sort_keys=True))
    return 0 if result['accepted'] else 1

if __name__ == '__main__':
    sys.exit(main())
