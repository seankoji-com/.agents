"""Explicit same-job dependency adoption from a newer installed package."""
from pathlib import Path

from core.jobs import _unsettled, revise_plan
from core.jobs.store import JobError, MAX_STATE_BYTES, _authorize, _regular, _retain, canonical, digest
from shared.job_coordinator import adopt_pins, verify_all_pins
from shared.worker_registry import job_agents_roots, record_job_root


def upgrade_package(store, caller, revision, dependency_key, expected_state_sha256,
                    expected_package_digest, package_dir, prefix, agents_root, config=None):
    """No implicit pin switch: old ownership, exact state, decision and new receipt bind it."""
    if not prefix or not agents_root:
        raise JobError('upgrade requires --prefix and --agents-root')
    job = verify_all_pins(store, caller)
    _authorize(job, caller, 'plan-revision')
    before = _regular(store.file, max_bytes=MAX_STATE_BYTES)
    if digest(before) != expected_state_sha256 or canonical(job) != before:
        raise JobError('upgrade state hash differs; inspect the current job before retrying')
    if not isinstance(revision, dict) or set(revision) != {'id', 'owner_decision_id', 'reason'}:
        raise JobError('upgrade revision needs only id, owner_decision_id and reason')
    if dependency_key not in job['pins']:
        raise JobError('upgrade references an undeclared dependency')
    if any(_unsettled(job, task) for task in job['tasks']):
        raise JobError('upgrade requires reconciled owned work and ingested results')
    package_dir = Path(package_dir).resolve()
    if package_dir == Path(job['pins'][dependency_key]['package_dir']).resolve():
        raise JobError('upgrade must adopt a different installed package')

    def adopt(current, dependencies):
        if canonical(current) != before:
            raise JobError('job changed during upgrade; inspect before retrying')
        pins = adopt_pins(current, dependencies, store.root, prefix, agents_root,
                          config, [dependency_key])
        pin = pins[dependency_key]
        if (Path(pin['package_dir']).resolve() != package_dir or
                pin['package_digest'] != expected_package_digest or
                pin['installation_id'] != current['installation_id']):
            raise JobError('upgrade target differs from executing package, digest or installation')
        # Existing pin verification and adoption verify package files and worker bundles.
        # Retain exact old bytes, including pins, before a transaction can replace them.
        backup = store.path / 'migrations' / (expected_state_sha256 + '-job.json')
        _retain(backup, before, 'upgrade backup bytes differ', max_bytes=MAX_STATE_BYTES)
        record_job_root(job_agents_roots(pins), store.root, store.path.name)
        return pins

    bound_revision = {**revision, 'adopt_keys': [dependency_key],
                      'previous_state': {'path': str(store.path / 'migrations' / (expected_state_sha256 + '-job.json')),
                                         'sha256': expected_state_sha256, 'bytes': len(before)},
                      'new_package_digest': expected_package_digest}
    # The ordinary plan-revision authority checks require a current matching owner
    # decision. It preserves runtime histories/counters and stales dependent acceptance.
    result = revise_plan(store, caller, bound_revision, {}, adopt)
    return {'job_id': result['job_id'], 'previous_state': bound_revision['previous_state'],
            'package_dir': str(package_dir), 'package_digest': expected_package_digest,
            'acceptance': 'invalidated; rerun validators', 'state_limit_bytes': MAX_STATE_BYTES}
