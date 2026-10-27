"""Major-versioned run storage with atomic, process-locked transactions.

run.json is authoritative. run.lock has a stable inode. Artifacts, scratch,
notes and reports survive an agent's worktree cleanup. No agent lease is needed.
"""
from __future__ import annotations

import copy
import fcntl
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import schema
from .errors import Conflict, InvalidInput, Prohibited
from .fsutil import atomic_json, read_json

SCHEMA_VERSION = 2
RUN_ID = re.compile(r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$')


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]


class RunStore:
    def __init__(self, state_root: Path, run_id: str):
        if not RUN_ID.fullmatch(run_id or ''):
            raise InvalidInput('run_id', 'run IDs look like 20261009-120000-abc123')
        self.state_root = Path(state_root)
        self.run_id = run_id
        self.run_dir = self.state_root / 'runs' / run_id
        self.state_path = self.run_dir / 'run.json'
        self.lock_path = self.run_dir / 'run.lock'

    @contextmanager
    def locked(self):
        if not self.run_dir.is_dir():
            raise Prohibited('run_not_found', f'no run {self.run_id} under {self.state_root}')
        self.load()  # refuse incompatible state before even creating a lock file
        with open(self.lock_path, 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def load(self) -> dict:
        try:
            state = read_json(self.state_path)
        except FileNotFoundError as exc:
            raise Prohibited('run_not_found', f'no run {self.run_id} under {self.state_root}') from exc
        if not isinstance(state, dict):
            raise InvalidInput('state_invalid', 'run record is not an object')
        version = state.get('schema_version')
        if type(version) is not int or version != SCHEMA_VERSION:
            raise InvalidInput('unsupported_version',
                               f'run major version {version!r} is unsupported; this gate requires major version 2. '
                               'Use agents activate imps <previous-version> to inspect, resume or cancel an old run.')
        schema.validate(state, 'run', 'state_invalid')
        return state

    def create(self, state: dict) -> dict:
        state = dict(state, schema_version=SCHEMA_VERSION, run_id=self.run_id)
        schema.validate(state, 'run', 'state_invalid')
        self.run_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.run_dir.mkdir()
        except FileExistsError as exc:
            raise Conflict('run_exists', 'init never overwrites a run') from exc
        for name in ('artifacts', 'scratch', 'notes', 'reports'):
            (self.run_dir / name).mkdir()
        self.lock_path.touch()
        atomic_json(self.state_path, state)
        return state

    def mutate(self, change) -> tuple[dict, object]:
        with self.locked():
            working = copy.deepcopy(self.load())
            result = change(working)
            working['updated_at'] = now_iso()
            schema.validate(working, 'run', 'state_invalid')
            atomic_json(self.state_path, working)
            return working, result


def env_state_root(plugin: str | None) -> Path | None:
    explicit = os.environ.get('AGENTS_STATE_ROOT')
    if explicit:
        return Path(explicit).expanduser()
    if not plugin:
        return None
    base = os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local' / 'state')
    return Path(base) / 'agents' / 'jobs' / plugin
