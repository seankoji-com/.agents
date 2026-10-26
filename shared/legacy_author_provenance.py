"""Read-only, request-specific provenance for pre-selection author executions.

The job/coordinator and its owner records are trusted, as at the existing decision
boundary. A native hash observation is worker-initiated host output inspected by
that coordinator, not cryptographic proof of the command or the human source.
"""
from pathlib import Path
import re

from core.jobs import _owner_current
from core.jobs.store import JobError, _regular, canonical, digest, strict_load, tasks
from shared.lineage import DRIVER_LINEAGE, FAMILY_LINEAGE


def provenance_scope(job_id, task_id, request_id):
    return 'legacy-author:' + digest(canonical([job_id, task_id, request_id]))


def _require(value):
    if not value:
        raise JobError('legacy author provenance is incomplete or conflicting')


def _path(value):
    _require(isinstance(value, str))
    p = Path(value)
    _require(p.is_absolute() and str(p) == value and '..' not in p.parts)
    _require(p.resolve() == p and not any(x.is_symlink() for x in (p, *p.parents)))
    return p


class LegacyAuthors:
    """One read-only view per author-set calculation; no inferred past choices."""
    def __init__(self, job):
        self.job = job
        self.records = list(tasks(job))
        self.limit = job.get('policy', {}).get('max_artifact_bytes', 16 * 1024 * 1024)

    def descriptors(self):
        for task in self.records:
            for key in ('brief', 'prepared_followup'):
                desc = task.get(key)
                if isinstance(desc, dict):
                    yield desc

    def root(self):
        roots = set()
        for desc in self.descriptors():
            p = _path(desc['path'])
            parent = p.parent.parent if p.parent.name == 'followup' else p.parent
            _require(parent.name == 'briefs' and parent.parent.name == self.job['job_id'])
            _require(p.name == desc['task_id'] + '-' + digest(desc['request_id'].encode()) + '.json')
            roots.add(parent)
        _require(len(roots) == 1)
        return roots.pop()

    def matching_records(self, task, handle):
        return [row for row in self.records if row['task_id'] == task['task_id'] and any(
            h.get('request_id') == handle['request_id'] and h.get('task_id') == handle.get('task_id')
            for h in row.get('handles', []) + row.get('followups', []))]

    def outside(self, value, root):
        p = _path(value)
        _require(not p.is_relative_to(root.parent))
        for task in self.records:
            scope = task.get('write_scope') or {}
            if scope.get('path'):
                worker = Path(scope['path'])
                _require('..' not in worker.parts)
                worker = worker if worker.is_absolute() else root.parent / worker
                _require(not p.is_relative_to(_path(str(worker))))
        return p

    def external_file(self, desc, root):
        _require(isinstance(desc, dict) and set(desc) == {'path', 'sha256', 'bytes'})
        _require(type(desc['bytes']) is int and 0 <= desc['bytes'] <= self.limit)
        raw = _regular(self.outside(desc['path'], root), max_bytes=self.limit)
        _require(len(raw) == desc['bytes'] and digest(raw) == desc['sha256'])
        return raw

    def proof_anchor(self, task, handle, path, root):
        scope = provenance_scope(self.job['job_id'], task['task_id'], handle['request_id'])
        found = set()
        for decision in self.job.get('decisions', []):
            if decision.get('scope') != scope:
                continue
            _require(_owner_current(decision, self.limit))
            proof_raw = _regular(self.outside(decision['source'], root), max_bytes=self.limit)
            proof = strict_load(proof_raw)
            _require(isinstance(proof, dict) and set(proof) == {
                'schema_version', 'kind', 'job_id', 'task_id', 'stage_id', 'logical_slot_id',
                'request_id', 'worker_id', 'host_task_id', 'target', 'brief', 'owner_source',
                'owner_quote', 'native_observation'})
            _require(proof['schema_version'] == 1 and type(proof['schema_version']) is int and
                     proof['kind'] == 'legacy-author-provenance')
            for key in ('job_id', 'task_id', 'stage_id', 'logical_slot_id', 'request_id', 'worker_id'):
                expected = self.job['job_id'] if key == 'job_id' else handle['request_id'] if key == 'request_id' else task[key]
                _require(proof[key] == expected)
            _require(proof['host_task_id'] == handle['task_id'] and proof['target'] == handle['target'])
            owner = self.external_file(proof['owner_source'], root).decode('utf-8')
            _require(bool(proof['owner_quote']) and proof['owner_quote'] == decision['quote'] and proof['owner_quote'] in owner)
            brief = proof['brief']
            _require(set(brief) == {'path', 'sha256', 'bytes'} and brief['path'] == str(path))
            _require(type(brief['bytes']) is int and 0 < brief['bytes'] <= self.limit)
            observation = proof['native_observation']
            _require(set(observation) == {'path', 'sha256', 'bytes', 'item_id', 'thread_id', 'run_id'})
            raw = self.external_file({k: observation[k] for k in ('path', 'sha256', 'bytes')}, root)
            native = strict_load(raw)['structuredContent']
            _require(observation['thread_id'] == handle['child_thread_id'] == native['thread']['threadId'])
            items = [i for i in native['items'] if i['itemId'] == observation['item_id']]
            _require(len(items) == 1)
            item = items[0]
            _require(item['runId'] == observation['run_id'] and item['runId'] and
                     item['sourceThreadId'] == handle['child_thread_id'] and
                     item['type'] == 'command_execution' and item['status'] == 'completed' and
                     item.get('textTruncated') is False)
            if handle.get('run_id'):
                _require(handle['run_id'] == item['runId'])
            text = item['text']
            # The coordinator inspected the original command when recording it.
            # These checks bind that retained observation, not shell semantics.
            lines = text.splitlines()
            full = brief['sha256'] + '  ' + str(path)
            relative = brief['sha256'] + '  ' + path.name
            _require(full in lines or relative in lines and str(path.parent) in text)
            found.add((brief['sha256'], brief['bytes']))
        _require(len(found) == 1)
        return found.pop()

    def anchor(self, task, handle, path, root):
        found = set()
        for desc in self.descriptors():
            if desc.get('task_id') == task['task_id'] and desc.get('request_id') == handle['request_id']:
                _require(desc['path'] == str(path))
                found.add(desc['sha256'])
        _require(len(found) <= 1)
        if found:
            return found.pop(), None
        return self.proof_anchor(task, handle, path, root)

    def original_identity(self, task, handle, brief, records):
        target, identity = handle['target'], handle['observed_identity']
        _require(isinstance(target, dict) and isinstance(identity, dict) and identity.get('status') == 'verified')
        _require(all(isinstance(target.get(k), str) and target[k] and identity.get(k) == target[k]
                     for k in ('providerInstanceId', 'model')))
        observations = list((identity.get('sources') or {}).values())
        dispatches = [d for row in records for d in row.get('dispatch_history', []) if
            d.get('request_id') == handle['request_id'] and d.get('host_task_id') == handle['task_id']]
        observations += [d['status_identity'] for d in dispatches if isinstance(d.get('status_identity'), dict)]
        if 'target' in brief:
            _require(brief['target'] == target)
        else:
            _require(any(d.get('kind') in ('accepted', 'completion') and all(
                d.get('status_identity', {}).get(k) == target[k] for k in ('providerInstanceId', 'model'))
                for d in dispatches))
        for row in [identity, *observations]:
            for key in ('providerInstanceId', 'model'):
                _require(key not in row or row[key] == target[key])
        match = re.match(r'[a-z]+', target['model'].rsplit('/', 1)[-1].lower())
        family = FAMILY_LINEAGE.get(match.group(0)) if match else None
        _require(family is not None)
        for row in [identity, *observations]:
            if row.get('driverKind') in DRIVER_LINEAGE:
                _require(DRIVER_LINEAGE[row['driverKind']] == family)
        return family

    def classify(self, task, handle):
        """Return a producing modern binding, a legacy family, or 'unknown'.

        None retains the old path for partial format-neutral import fixtures.
        """
        binding = task.get('selection_binding')
        if 'selection_binding' in task and not isinstance(binding, dict):
            return 'unknown'
        # Partial, format-neutral modern fixture/import objects retain their old
        # eligibility path. Real stored executions carry these correlation keys.
        if not self.job.get('job_id') or not task.get('task_id') or not handle.get('request_id'):
            return None if binding else 'unknown'
        try:
            records = self.matching_records(task, handle)
            unbound = [r for r in records if 'selection_binding' not in r]
            root = self.root()
            followup = any(h.get('request_id') == handle['request_id'] for r in records for h in r.get('followups', []))
            path = root / ('followup' if followup else '') / (task['task_id'] + '-' + digest(handle['request_id'].encode()) + '.json')
            raw = _regular(_path(str(path)), max_bytes=self.limit)
            brief = strict_load(raw)
            _require(isinstance(brief, dict))
            if 'model_selection' in brief:
                # A stripped modern task/binding cannot acquire legacy status.
                selected = brief['model_selection']
                _require(not unbound and isinstance(binding, dict) and isinstance(selected, dict) and
                         isinstance(selected.get('binding'), dict) and
                         selected.get('selection_sha256') == selected['binding'].get('selection_sha256'))
                producing_binding = selected['binding']
                _require(any(r.get('selection_binding') == producing_binding for r in records))
                from shared.model_selection import validate
                producing = (self.job.get('model_selection_history') or {}).get(
                    selected['selection_sha256'], self.job.get('model_selection'))
                validate(producing, selected['selection_sha256'])
                for desc in self.descriptors():
                    if desc.get('task_id') == task['task_id'] and desc.get('request_id') == handle['request_id']:
                        _require(desc['path'] == str(path) and digest(raw) == desc['sha256'])
                content = dict(brief); effective = content.pop('effective_brief_sha256')
                _require(digest(canonical(content)) == effective)
                return producing_binding
            original = unbound or records
            _require(bool(original))
            # Require one original contract, not a choice made after execution.
            for key in ('stage_id', 'logical_slot_id', 'worker_id'):
                _require(len({r[key] for r in original}) == 1 and brief.get(key) == original[0][key])
            _require(brief.get('job_id') == self.job['job_id'] and brief.get('task_id') == task['task_id'] and
                     brief.get('request_id') == handle['request_id'])
            _require(not any(k in brief for k in ('model_selection_sha256', 'selection_sha256', 'selection_binding')))
            expected, size = self.anchor(original[0], handle, path, root)
            _require(digest(raw) == expected and (size is None or len(raw) == size))
            content = dict(brief); effective = content.pop('effective_brief_sha256')
            _require(digest(canonical(content)) == effective)
            if followup:
                parents = [h for r in records for h in r.get('handles', []) + r.get('followups', [])
                           if h.get('task_id') == handle.get('parent_task_id')]
                _require(parents and all(h['request_id'] == brief.get('followup_of') for h in parents))
            return self.original_identity(original[0], handle, brief, original)
        except (JobError, OSError, ValueError, KeyError, TypeError, AttributeError):
            return 'unknown'
