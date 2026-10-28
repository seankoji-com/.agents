"""Coordinator-only target findings channel. Worker result semantics stay generic."""
from pathlib import Path
import re

from core.jobs.store import _regular, canonical, digest, strict_load


RESEARCH_INSTRUCTIONS = """The coordinator assigned the explicit audited-target contract in resources.target_report.
Do not choose this scope yourself. Write original target findings to your assigned
target-findings.json under artifacts/tasks/<task-id>/, using the exact path in that
contract. The artifact is {"schema_version":1,"findings":[...]} in discovery order.
Each finding needs a stable id, severity (blocker, major, minor, note), code,
redacted location, concrete scenario and source_evidence (URL and version, or the
command and an excerpt). Preserve whole objects, severity and order. Include the
artifact's exact path, SHA-256 and byte count in worker-result artifacts.

Carry every assigned deterministic inspect finding and gap from consumed_outputs
or the brief's explicit inputs into that artifact. Preserve assigned IDs,
severities and whole objects in their assigned order. If an inspect row lacks the
required fields, have the coordinator assign them before dispatch. Add research
findings after those rows. Keep coverage_gap and unsupported intact; Muse native
approval-policy-store coverage remains unsupported. Never omit or demote a gap
because its underlying semantics could not be verified.

Worker-result findings describe defects in your delivered report, including
missing evidence. Any major or blocker there requires review_verdict: adverse
and fails acceptance. Otherwise review_verdict is null. List gaps, uncertainties
and exact commands. The later integrated quality review is not a prerequisite
for research completion.

Never return secrets, tokens, headers, private URLs, hostnames, home paths or
settings values. Refer to settings by scope and JSON pointer. Excerpt output;
do not paste it whole. Never fetch raw remote settings for local redaction or
transfer raw/aggregate transcripts. Do not bypass a guard refusal or
install/execute a remote extractor. If safe extraction is unsupported, report a
coverage gap."""


def need(condition, message):
    if not condition:
        raise ValueError('target report: ' + message)


def contract(value):
    need(isinstance(value, dict) and set(value) == {
        'schema_version', 'finding_scope', 'reports', 'quality_review'}, 'explicit contract required')
    need(type(value['schema_version']) is int and value['schema_version'] == 1 and
         value['finding_scope'] == 'audited-target' and
         value['quality_review'] == 'integrated-adopter-planning', 'unsupported contract')
    reports = value['reports']
    need(isinstance(reports, list) and bool(reports), 'research reports required')
    ids = []
    for row in reports:
        need(isinstance(row, dict) and set(row) == {'task_id', 'path'}, 'invalid report descriptor')
        tid = row['task_id']
        need(isinstance(tid, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', tid), 'invalid task ID')
        need(row['path'] == f'artifacts/tasks/{tid}/target-findings.json', 'report escapes exact task path')
        ids.append(tid)
    need(len(ids) == len(set(ids)), 'duplicate reports')
    return reports


def criteria(data):
    need(isinstance(data.get('criteria'), dict) and data['criteria'].get('operation') == 'audit' and
         data['criteria'].get('findings_allowed') is True and data.get('changes') == [],
         'only findings-allowed audit without settings changes may opt in')
    contract(data['target_report'])
    validate_findings(data.get('findings'))
    need(data.get('report_stage') in ('research', 'integrated'), 'explicit report stage required')
    if data['report_stage'] == 'integrated':
        need(isinstance(data.get('adopter_output'), dict), 'independent quality review required, even with zero findings')


def validate_findings(findings):
    need(isinstance(findings, list), 'findings array required')
    ids = set()
    for finding in findings:
        need(isinstance(finding, dict) and all(isinstance(finding.get(k), str) and finding[k].strip()
             for k in ('id', 'severity', 'code', 'location', 'scenario')) and
             finding['severity'] in ('blocker', 'major', 'minor', 'note') and
             (isinstance(finding.get('source_evidence'), str) and bool(finding['source_evidence'].strip()) or
              isinstance(finding.get('source_evidence'), list) and bool(finding['source_evidence']) and
              all(isinstance(e, str) and e.strip() for e in finding['source_evidence'])),
             'original finding needs ID, severity, code, location, scenario and source evidence')
        need(finding['id'] not in ids, 'duplicate finding ID')
        ids.add(finding['id'])


def validate_job(job):
    stages = [s for s in job['stages'] if 'target_report' in s.get('validator_contract', {})]
    if not stages:
        return
    need(job['workflow'] in ('agent-tuneup/audit', 'agent-tuneup/align', 'agent-tuneup/tuneup'),
         'wrong plugin or operation')
    research, finals, reports = [], [], []
    for stage in stages:
        c = stage['validator_contract']
        need(c.get('criteria', {}).get('operation') == 'audit' and
             c['criteria'].get('findings_allowed') is True, 'audit criteria required')
        dep = next((d for d in job['dependencies'] if d['key'] == stage.get('validator_dependency')), {})
        need(dep.get('plugin') == 'agent-tuneup', 'wrong validator plugin')
        rows = contract(c['target_report'])
        slots = [t for t in job['tasks'] if t['stage_id'] == stage['id']]
        if c.get('report_stage') == 'research':
            resources = stage.get('resources', {})
            need(isinstance(resources, dict) and
                 canonical(resources.get('target_report')) == canonical(c['target_report']) and
                 resources.get('target_report_instructions') == RESEARCH_INSTRUCTIONS,
                 'research resources must carry the exact target contract and specialization instructions')
            producers = [t for t in slots if t.get('role', 'worker') != 'review']
            need(stage.get('execution_mode', 'workers') == 'workers' and bool(producers), 'worker research stage required')
            need([r['task_id'] for r in rows] == [t['task_id'] for t in producers], 'exact ordered researcher coverage required')
            for task in producers:
                need(task['worker_id'] == 'agent-tuneup/config-researcher' and task.get('role', 'worker') == 'worker' and
                     task.get('dependency_key') == stage['validator_dependency'] and
                     task.get('write_scope') == {'mode': 'worker-evidence', 'path': 'artifacts/tasks/' + task['task_id']},
                     'only owned non-review researcher slots may produce target findings')
            research.append(stage['id'])
            reports.extend(rows)
        elif c.get('report_stage') == 'integrated':
            need(stage.get('execution_mode') == 'direct' and not slots and
                 not any(stage['id'] in s.get('depends_on', []) for s in job['stages']),
                 'integrated report must be a final direct stage')
            finals.append(stage)
        else:
            need(False, 'explicit report stage required')
    need(bool(research) and len(finals) == 1, 'research requires one final independent quality-review gate')
    final = finals[0]
    need(set(research) <= set(final.get('depends_on', [])) and
         final['validator_contract']['target_report']['reports'] == reports,
         'final integration must depend on and preserve every ordered research report')


def artifacts(job, root, value):
    """Bind exact ingested descriptors and bounded actual bytes; never trust prose."""
    findings, descriptors, ids = [], [], set()
    for row in contract(value):
        task = next((t for t in job['tasks'] if t['task_id'] == row['task_id']), None)
        need(task is not None and task.get('worker_id') == 'agent-tuneup/config-researcher' and
             task.get('role', 'worker') == 'worker', 'research ownership mismatch')
        execution = next((e for e in task.get('execution_history', []) if e.get('request_id') == task['request_id']), None)
        need(execution and execution.get('sha256') == task.get('result_ref', {}).get('sha256'),
             'current ingested execution required')
        matches = [a for a in execution['result']['artifacts'] if a.get('path') == row['path']]
        need(len(matches) == 1, 'exact ingested artifact descriptor required')
        descriptor = matches[0]
        path = Path(root) / row['path']
        raw = _regular(path, max_bytes=job['policy']['max_artifact_bytes'])
        need(digest(raw) == descriptor.get('sha256') and len(raw) == descriptor.get('bytes'),
             'artifact bytes changed since ingestion')
        content = strict_load(raw)
        need(isinstance(content, dict) and set(content) == {'schema_version', 'findings'} and
             type(content['schema_version']) is int and content['schema_version'] == 1 and
             isinstance(content['findings'], list), 'malformed findings artifact')
        validate_findings(content['findings'])
        for finding in content['findings']:
            need(finding['id'] not in ids, 'duplicate finding ID')
            ids.add(finding['id'])
            findings.append(finding)
        descriptors.append({'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)})
    return findings, descriptors


def validate_observation(job, stage, data, root):
    validate_job(job)
    c = stage['validator_contract']
    need(data.get('target_report') == c.get('target_report') and
         data.get('report_stage') == c.get('report_stage'), 'coordinator contract differs')
    criteria(data)
    if data['report_stage'] == 'integrated':
        need(data['adopter_output'].get('job_file') == str(Path(root) / 'job.json'),
             'quality receipt belongs to another producing job')
    findings, descriptors = artifacts(job, root, c['target_report'])
    need(canonical(findings) == canonical(data.get('findings')), 'omitted, substituted or reordered original findings')
    return {d['path']: d['sha256'] for d in descriptors}


def quality_evidence(data, desc, metadata, passes):
    """Called after the independent planning receipt has been validated."""
    criteria(data)
    need(data['report_stage'] == 'integrated', 'quality review is for integrated conclusions')
    path = Path(desc.get('job_file', ''))
    need(path.is_absolute() and path.name == 'job.json', 'producing job required')
    job = strict_load(_regular(path))
    validate_job(job)
    findings, descriptors = artifacts(job, path.parent, data['target_report'])
    need(canonical(findings) == canonical(data['findings']), 'review omitted original findings')
    evidence = metadata['snapshot']['evidence_paths']
    need(all(any(all(e.get(k) == d[k] for k in ('path', 'sha256', 'bytes')) for e in evidence)
             for d in descriptors), 'quality review must declare the original target artifacts as evidence')
    paths = {d['path'] for d in descriptors}
    need(bool(passes) and all(paths <= set(p['inspected_paths']) for p in passes),
         'every required quality-review pass must inspect the original target artifacts')
