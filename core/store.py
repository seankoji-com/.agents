"""One authoritative run record per run directory, guarded by flock, an owner
token and an optimistic generation.

Layout of <state-root>/runs/<run-id>/:
  run.json    the record (schema_version, generation, ...)
  owner.json  present only while an invocation holds the claim
  run.lock    stable lock inode; never unlinked
  artifacts/  evidence copied in by `record`; never removed by cleanup
  reports/    JSON and Markdown reports
"""
from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import schema
from .errors import Conflict, Environment, InvalidInput, Prohibited
from .fsutil import atomic_json, read_json

SCHEMA_VERSION = 1
RUN_ID = re.compile(r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$')


def now_iso(clock=None) -> str:
    return datetime.fromtimestamp(clock if clock is not None else time.time(), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]


class RunStore:
    def __init__(self, state_root: Path, run_id: str):
        if not RUN_ID.match(run_id or ''):
            raise InvalidInput('run_id', 'run IDs look like 20261009-120000-abc123', {'run_id': run_id})
        self.state_root = Path(state_root)
        self.run_id = run_id
        self.run_dir = self.state_root / 'runs' / run_id
        self.state_path = self.run_dir / 'run.json'
        self.owner_path = self.run_dir / 'owner.json'
        self.lock_path = self.run_dir / 'run.lock'

    # -- low level -------------------------------------------------------
    def exists(self) -> bool:
        return self.state_path.is_file()

    @contextmanager
    def locked(self):
        if not self.run_dir.is_dir():
            raise Prohibited('run_not_found', f'no run {self.run_id} under {self.state_root}')
        try:
            handle = open(self.lock_path, 'a')
        except OSError as exc:
            raise Environment('io_error', f'cannot open lock: {exc.strerror}') from exc
        with handle:
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
        if not isinstance(version, int) or version > SCHEMA_VERSION or version < 1:
            raise InvalidInput('unsupported_version',
                               f'run record schema_version {version!r} is not supported (max {SCHEMA_VERSION})',
                               {'schema_version': version})
        return state

    def owner(self) -> dict | None:
        try:
            return read_json(self.owner_path)
        except FileNotFoundError:
            return None

    def _write(self, state: dict) -> None:
        schema.validate(state, 'run', 'state_invalid')
        atomic_json(self.state_path, state)

    # -- lifecycle -------------------------------------------------------
    def create(self, state: dict) -> dict:
        self.run_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.run_dir.mkdir()
        except FileExistsError as exc:
            raise Conflict('run_exists', f'run {self.run_id} already exists; init never overwrites') from exc
        except OSError as exc:
            raise Environment('io_error', f'cannot create run directory: {exc.strerror}') from exc
        (self.run_dir / 'artifacts').mkdir()
        (self.run_dir / 'scratch').mkdir()
        self.lock_path.touch()
        state = dict(state, schema_version=SCHEMA_VERSION, run_id=self.run_id, generation=1)
        self._write(state)
        return state

    def claim(self, invocation: dict) -> dict:
        with self.locked():
            state = self.load()
            if self.owner():
                raise Conflict('owned', 'run is already claimed; confirm the prior invocation stopped, then recover',
                               {'owner': {k: v for k, v in self.owner().items() if k != 'token'}})
            budget = state['budget']
            remaining = max(0.0, budget['seconds'] - budget['spent_seconds'])
            clock = time.time()
            owner = {'token': uuid.uuid4().hex, 'claimed_at': clock, 'deadline': clock + remaining,
                     'spent_before': budget['spent_seconds'], 'generation_at_claim': state['generation'],
                     'invocation': invocation}
            atomic_json(self.owner_path, owner)
            return owner

    def _charge(self, owner: dict) -> dict:
        state = self.load()
        spent = owner['spent_before'] + max(0.0, min(time.time(), owner['deadline']) - owner['claimed_at'])
        state['budget']['spent_seconds'] = round(spent, 3)
        state['generation'] += 1
        state['updated_at'] = now_iso()
        self._write(state)
        return state

    def release(self, token: str) -> dict:
        with self.locked():
            owner = self.owner()
            if not owner:
                raise Conflict('not_owned', 'no claim to release')
            if owner['token'] != token:
                raise Conflict('token_mismatch', 'release token does not match the current claim')
            state = self._charge(owner)
            self.owner_path.unlink()
            return {'released': True, 'generation': state['generation'], 'budget': state['budget']}

    def recover(self, token: str | None, confirmed_dead: bool) -> dict:
        if not confirmed_dead:
            raise Prohibited('recovery_unconfirmed',
                             'recover requires --confirmed-dead; deadline or heartbeat age never proves an invocation stopped')
        with self.locked():
            owner = self.owner()
            if not owner:
                raise Conflict('not_owned', 'no claim to recover')
            if not token or owner['token'] != token:
                raise Conflict('token_mismatch', 'pass the stale claim token shown by status to recover it')
            state = self._charge(owner)
            self.owner_path.unlink()
            return {'recovered': True, 'generation': state['generation'], 'budget': state['budget']}

    def mutate(self, token: str | None, expected_generation, change) -> tuple[dict, object]:
        """Apply change(state) -> result under the lock.

        Requires a live claim whose token matches (a missing owner file is a
        rejection, not a free pass) and the expected generation. Rejected calls
        leave run.json byte-identical."""
        with self.locked():
            owner = self.owner()
            if owner is None:
                raise Conflict('not_owned', 'mutations require a claim; run claim first')
            if not token or owner.get('token') != token:
                raise Conflict('token_mismatch', 'token does not match the current claim')
            state = self.load()
            if expected_generation is None or int(expected_generation) != state['generation']:
                raise Conflict('stale_generation', 'state generation changed; re-read status and retry',
                               {'expected': expected_generation, 'actual': state['generation']})
            working = copy.deepcopy(state)
            result = change(working, owner)
            working['generation'] = state['generation'] + 1
            working['updated_at'] = now_iso()
            self._write(working)
            return working, result

    def mutate_unowned(self, expected_check, change) -> tuple[dict, object]:
        """Operator decisions applied while no invocation holds the run."""
        with self.locked():
            if self.owner() is not None:
                raise Conflict('owned', 'run is claimed by a live invocation; release or recover first')
            state = self.load()
            expected_check(state)
            working = copy.deepcopy(state)
            result = change(working)
            working['generation'] = state['generation'] + 1
            working['updated_at'] = now_iso()
            self._write(working)
            return working, result


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


def env_state_root(plugin: str | None) -> Path | None:
    explicit = os.environ.get('T3_PLUGINS_STATE_ROOT')
    if explicit:
        return Path(explicit).expanduser()
    if not plugin:
        return None
    base = os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local' / 'state')
    return Path(base) / 't3-plugins' / plugin
