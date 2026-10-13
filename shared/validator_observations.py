"""Strict structural validation of content-bound coordinator observations."""
import hashlib
from pathlib import Path
from core.jobs.store import canonical, strict_load, _regular

def read_object(path):
    raw = _regular(Path(path), max_bytes=16 * 1024 * 1024)
    value = strict_load(raw)
    if not isinstance(value, dict):
        raise ValueError('validator input must be one complete JSON object')
    return value, hashlib.sha256(raw).hexdigest()

def observation(row, kind=None):
    if not isinstance(row, dict) or row.get('observer') != 'coordinator' or not row.get('source'):
        raise ValueError('explicit coordinator observation is required')
    if kind is not None and row.get('kind') != kind:
        raise ValueError('observation operation identity differs')
    content = row.get('content')
    if not isinstance(content, dict) or row.get('sha256') != hashlib.sha256(canonical(content)).hexdigest():
        raise ValueError('observation content is missing or its hash differs')
    return content

def emit(ok, name, evidence, **extra):
    return {'accepted': bool(ok), 'requirement_outcomes': {
        name: {'status': 'passed' if ok else 'failed', 'evidence': evidence}}, **extra}
