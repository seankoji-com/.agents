#!/usr/bin/env python3
"""Validate a sanitized bench-v2 attempt record using its adjacent schema."""
import json
import math
import re
import sys
from pathlib import Path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f'non-finite JSON number: {value}')


def _matches_type(value, kind):
    return {
        'object': lambda: isinstance(value, dict),
        'array': lambda: isinstance(value, list),
        'string': lambda: isinstance(value, str),
        'integer': lambda: type(value) is int,
        # Integers are always finite; math.isfinite would convert them to float and overflow.
        'number': lambda: type(value) is int or (type(value) is float and math.isfinite(value)),
        'boolean': lambda: type(value) is bool,
        'null': lambda: value is None,
    }[kind]()


def _schema_errors(value, schema, path='$'):
    errors = []
    kinds = schema.get('type')
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(_matches_type(value, kind) for kind in kinds):
            return [f'{path} must be {" or ".join(kinds)}']
    if 'const' in schema and value != schema['const']:
        errors.append(f'{path} must equal {schema["const"]!r}')
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path} must be one of {schema["enum"]!r}')
    if isinstance(value, str) and len(value) < schema.get('minLength', 0):
        errors.append(f'{path} is too short')
    if isinstance(value, str) and 'pattern' in schema and re.fullmatch(schema['pattern'], value) is None:
        errors.append(f'{path} does not match required pattern')
    if type(value) in (int, float) and value < schema.get('minimum', float('-inf')):
        errors.append(f'{path} is below minimum {schema["minimum"]}')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            errors.append(f'{path} has too few items')
        if 'items' in schema:
            for index, item in enumerate(value):
                errors.extend(_schema_errors(item, schema['items'], f'{path}[{index}]'))
    if isinstance(value, dict):
        if len(value) < schema.get('minProperties', 0):
            errors.append(f'{path} has too few properties')
        for key in schema.get('required', []):
            if key not in value:
                errors.append(f'{path} missing {key}')
        properties = schema.get('properties', {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_schema_errors(item, properties[key], f'{path}.{key}'))
            elif schema.get('additionalProperties') is False:
                errors.append(f'{path} contains unsupported field {key}')
            elif isinstance(schema.get('additionalProperties'), dict):
                errors.extend(_schema_errors(item, schema['additionalProperties'], f'{path}.{key}'))
    return errors


FAMILY_PATTERNS = {'codex': r'gpt-[0-9]+(?:\.[0-9]+)?-luna',
                   'claudeAgent': r'claude-haiku-[0-9]+(?:-[0-9]+)*'}
# Complete low/standard option shapes a launch may request, per provider.
REQUESTED_SHAPES = {'codex': [{'reasoningEffort': 'low', 'serviceTier': 'default'}],
                    'claudeAgent': [{'effort': 'low'}, {'effort': 'low', 'fastMode': False}, {'thinking': False}]}


def _requested_option_errors(options):
    """Policy for requested options when no exact model readback exists."""
    errors = []
    providers = set(REQUESTED_SHAPES)
    requested_provider = options.get('provider_instance_id')
    if 'provider_instance_id' in options:
        # A malformed (non-string) provider is an error, never an unhashable lookup.
        if not isinstance(requested_provider, str) or requested_provider not in REQUESTED_SHAPES:
            errors.append('model_options.provider_instance_id is not a permitted benchmark provider')
        providers &= {requested_provider} if isinstance(requested_provider, str) else set()
    if 'model_id' in options:
        model_id = options['model_id']
        families = {p for p in providers if isinstance(model_id, str) and re.fullmatch(FAMILY_PATTERNS[p], model_id)}
        if not families:
            errors.append('model_options.model_id is not a permitted benchmark tier')
        providers = families
    settings = {key: value for key, value in options.items() if key not in ('provider_instance_id', 'model_id')}
    shapes = [shape for provider in sorted(providers) for shape in REQUESTED_SHAPES[provider]]
    if not any(set(shape) == set(settings) and all(type(settings[k]) is type(v) and settings[k] == v
                                                   for k, v in shape.items()) for shape in shapes):
        errors.append('model_options requested without readback must match the low/standard benchmark policy')
    return errors


def validate(record):
    schema_path = Path(__file__).with_name('attempt.schema.json')
    try:
        schema = json.loads(schema_path.read_text(encoding='utf-8'), object_pairs_hook=_pairs,
                            parse_constant=_constant)
    except (OSError, ValueError) as exc:
        return [f'cannot load attempt schema: {exc}']
    errors = _schema_errors(record, schema)
    if not isinstance(record, dict):
        return errors
    reasons = record.get('unknown_reasons')
    metric_reasons = record.get('metrics_unknown_reasons')
    if isinstance(reasons, dict):
        nullable = ('provider_instance_id', 'model_as_read_back', 'runtime_mode', 'os',
                    't3_build', 'job_id', 'thread_id', 'parser_summary')
        for key in nullable:
            if record.get(key) is None and not (isinstance(reasons.get(key), str) and reasons[key].strip()):
                errors.append(f'{key} null requires unknown_reasons entry')
        for key in reasons:
            if key not in nullable or record.get(key) is not None:
                errors.append(f'unknown_reasons.{key} does not describe a null field')
    if isinstance(metric_reasons, dict) and isinstance(record.get('metrics'), dict):
        metrics = record['metrics']
        for key, reason in metric_reasons.items():
            if key not in metrics or metrics[key] is not None or not isinstance(reason, str) or not reason.strip():
                errors.append(f'metrics_unknown_reasons.{key} must explain a null metric')
        for key, value in metrics.items():
            if value is None and not (isinstance(metric_reasons.get(key), str) and metric_reasons[key].strip()):
                errors.append(f'metrics.{key} null requires metrics_unknown_reasons entry')
        workers = metrics.get('worker_usage')
        if isinstance(workers, dict):
            usage_fields = ('input', 'cache_read', 'cache_write', 'output', 'context')
            for task_id, summary in workers.items():
                if not isinstance(summary, dict):
                    continue
                nested_reasons = summary.get('unknown')
                if not isinstance(nested_reasons, dict):
                    errors.append(f'metrics.worker_usage.{task_id}.unknown must be an object')
                    continue
                for field in usage_fields:
                    if summary.get(field) is None and not (isinstance(nested_reasons.get(field), str) and nested_reasons[field].strip()):
                        errors.append(f'metrics.worker_usage.{task_id}.{field} null requires unknown reason')
                for field in nested_reasons:
                    if field not in usage_fields or summary.get(field) is not None:
                        errors.append(f'metrics.worker_usage.{task_id}.unknown.{field} does not describe a null total')
    readback = record.get('model_as_read_back')
    provider = record.get('provider_instance_id')
    if isinstance(readback, dict):
        if readback.get('provider_instance_id') != provider:
            errors.append('model_as_read_back.provider_instance_id must match provider_instance_id')
        options = record.get('model_options')
        if isinstance(options, dict):
            for key, actual in (('provider_instance_id', readback.get('provider_instance_id')),
                                ('model_id', readback.get('model_id'))):
                if key in options and options[key] != actual:
                    errors.append(f'model_options.{key} must match exact model readback')
            model_id = readback.get('model_id', '')
            # The schema error is already recorded; a non-string readback matches no permitted tier.
            if not isinstance(model_id, str):
                model_id = ''
            expected = None
            if provider == 'codex' and re.fullmatch(r'gpt-[0-9]+(?:\.[0-9]+)?-luna', model_id):
                expected = {'reasoningEffort': 'low', 'serviceTier': 'default'}
            elif provider == 'claudeAgent' and re.fullmatch(r'claude-haiku-[0-9]+(?:-[0-9]+)*', model_id):
                expected = {'thinking': False} if 'thinking' in options else {'effort': 'low'}
                if 'fastMode' in options and 'thinking' not in expected:
                    expected['fastMode'] = False
            if expected is None:
                errors.append('exact model readback family is not a permitted benchmark tier')
            else:
                for key, value in expected.items():
                    if type(options.get(key)) is not type(value) or options.get(key) != value:
                        errors.append(f'model_options.{key} must match the low/standard benchmark policy')
                allowed = set(expected) | {'provider_instance_id', 'model_id'}
                for key in options:
                    if key not in allowed:
                        errors.append(f'model_options.{key} is not part of the low/standard benchmark policy')
    elif readback is None:
        if provider is not None:
            errors.append('provider_instance_id must be null when exact model readback is unknown')
        options = record.get('model_options')
        if isinstance(options, dict):
            errors.extend(_requested_option_errors(options))
    for field in ('package_digests', 'bundle_digests'):
        digest_map = record.get(field)
        if isinstance(digest_map, dict):
            if not digest_map:
                errors.append(f'{field} must contain at least one named digest')
            for name, digest in digest_map.items():
                if not isinstance(name, str) or not name.strip() or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                    errors.append(f'{field}.{name} must be a lowercase SHA-256 digest')
    digests = record.get('private_raw_sha256')
    if isinstance(digests, list):
        for index, digest in enumerate(digests):
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                errors.append(f'private_raw_sha256[{index}] must be a lowercase SHA-256 digest')
    return errors


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('usage: attempt_record.py RECORD.json')
        record = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'),
                            object_pairs_hook=_pairs, parse_constant=_constant)
        errors = validate(record)
    except (OSError, ValueError) as exc:
        print(json.dumps({'valid': False, 'errors': [str(exc)]}, separators=(',', ':')))
        sys.exit(2)
    print(json.dumps({'valid': not errors, 'errors': errors}, separators=(',', ':')))
    sys.exit(bool(errors))
