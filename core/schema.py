"""A stdlib validator for the JSON Schema subset the published schemas use.

Loading a schema that uses any keyword outside SUPPORTED raises, so a published
schema can never declare a constraint this validator silently ignores. Tuple-form
(list) `items` is unsupported and raises the same way; `items` must be one schema."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .errors import InvalidInput

SCHEMA_DIR = Path(__file__).resolve().parent / 'schemas'

SUPPORTED = {
    '$schema', '$id', '$ref', '$defs', '$comment', 'title', 'description', 'examples',
    'type', 'properties', 'propertyNames', 'required', 'additionalProperties', 'items', 'enum', 'const',
    'minLength', 'maxLength', 'minimum', 'maximum', 'minItems', 'maxItems', 'pattern',
    'anyOf', 'oneOf', 'uniqueItems', 'default',
}

_TYPES = {
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'string': lambda v: isinstance(v, str),
    'boolean': lambda v: isinstance(v, bool),
    'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
    'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    'null': lambda v: v is None,
}


def check_keywords(node, where='#'):
    if isinstance(node, dict):
        unknown = set(node) - SUPPORTED
        if unknown:
            raise InvalidInput('schema_keyword', f'unsupported schema keyword(s) at {where}: {sorted(unknown)}')
        if isinstance(node.get('items'), list):
            raise InvalidInput('schema_keyword', f'tuple-form items is unsupported at {where}/items')
        for key, value in node.items():
            if key in ('properties', '$defs'):
                for name, sub in value.items():
                    check_keywords(sub, f'{where}/{key}/{name}')
            elif key in ('items', 'additionalProperties', 'propertyNames') and isinstance(value, dict):
                check_keywords(value, f'{where}/{key}')
            elif key in ('anyOf', 'oneOf'):
                for index, sub in enumerate(value):
                    check_keywords(sub, f'{where}/{key}/{index}')


def load_schema_file(path: Path) -> dict:
    schema = json.loads(Path(path).read_text())
    check_keywords(schema)
    return schema


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    return load_schema_file(SCHEMA_DIR / f'{name}.schema.json')


def _resolve(root, ref):
    if not ref.startswith('#/'):
        raise InvalidInput('schema_ref', f'only local $ref supported: {ref}')
    node = root
    for part in ref[2:].split('/'):
        node = node[part]
    return node


def errors(instance, schema, root=None, path='$'):
    """Return a list of human-readable violations (empty when valid)."""
    root = root if root is not None else schema
    found = []
    if '$ref' in schema:
        return errors(instance, _resolve(root, schema['$ref']), root, path)
    expected = schema.get('type')
    if expected is not None:
        kinds = expected if isinstance(expected, list) else [expected]
        if not any(_TYPES[kind](instance) for kind in kinds):
            return [f'{path}: expected {"/".join(kinds)}']
    if 'const' in schema and instance != schema['const']:
        found.append(f'{path}: must equal {schema["const"]!r}')
    if 'enum' in schema and instance not in schema['enum']:
        found.append(f'{path}: must be one of {schema["enum"]}')
    if isinstance(instance, str):
        if 'minLength' in schema and len(instance) < schema['minLength']:
            found.append(f'{path}: shorter than {schema["minLength"]}')
        if 'maxLength' in schema and len(instance) > schema['maxLength']:
            found.append(f'{path}: longer than {schema["maxLength"]}')
        if 'pattern' in schema and not re.search(schema['pattern'], instance):
            found.append(f'{path}: does not match {schema["pattern"]}')
    if _TYPES['number'](instance):
        if 'minimum' in schema and instance < schema['minimum']:
            found.append(f'{path}: below {schema["minimum"]}')
        if 'maximum' in schema and instance > schema['maximum']:
            found.append(f'{path}: above {schema["maximum"]}')
    if isinstance(instance, list):
        if 'minItems' in schema and len(instance) < schema['minItems']:
            found.append(f'{path}: fewer than {schema["minItems"]} items')
        if 'maxItems' in schema and len(instance) > schema['maxItems']:
            found.append(f'{path}: more than {schema["maxItems"]} items')
        if schema.get('uniqueItems'):
            seen = [json.dumps(item, sort_keys=True) for item in instance]
            if len(seen) != len(set(seen)):
                found.append(f'{path}: items must be unique')
        if isinstance(schema.get('items'), dict):
            for index, item in enumerate(instance):
                found += errors(item, schema['items'], root, f'{path}[{index}]')
    if isinstance(instance, dict):
        for name in schema.get('required', []):
            if name not in instance:
                found.append(f'{path}: missing required "{name}"')
        properties = schema.get('properties', {}); extra = schema.get('additionalProperties', True)
        for key, value in instance.items():
            if 'propertyNames' in schema: found += errors(key, schema['propertyNames'], root, f'{path}.{key} (name)')
            if key in properties:
                found += errors(value, properties[key], root, f'{path}.{key}')
            elif extra is False:
                found.append(f'{path}: unexpected field "{key}"')
            elif isinstance(extra, dict):
                found += errors(value, extra, root, f'{path}.{key}')
    if 'anyOf' in schema:
        if not any(not errors(instance, sub, root, path) for sub in schema['anyOf']):
            found.append(f'{path}: matches none of anyOf')
    if 'oneOf' in schema:
        matches = sum(1 for sub in schema['oneOf'] if not errors(instance, sub, root, path))
        if matches != 1:
            found.append(f'{path}: must match exactly one of oneOf (matched {matches})')
    return found


def validate(instance, name: str, code: str = 'schema_invalid'):
    problems = errors(instance, load_schema(name))
    if problems:
        raise InvalidInput(code, f'{name} failed validation', {'errors': problems[:20]})
    return instance
