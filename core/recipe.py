"""Project verification recipes: scaffold from discovered facts, check, and stamp
as verified only from a recorded runtime run whose evidence still exists.

A recipe is `draft` until stamped. Placeholder text (angle-bracket slots, TODO,
TBD, unrendered {{...}}) is rejected, so a placeholder can never be verified."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import schema
from .errors import InvalidInput, Prohibited
from .fsutil import atomic_json, atomic_write_bytes, sha256_file

PLACEHOLDER = re.compile(r'<[a-z][a-z0-9 _-]*>|\bTODO\b|\bTBD\b|\{\{[^}]*\}\}', re.I)
VARIABLE = re.compile(r'\$\{([A-Z][A-Z0-9_]*)\}')
SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,40}$')


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def problems(recipe: dict, directory: Path) -> list:
    found = list(schema.errors(recipe, schema.load_schema('recipe')))
    if found:
        return found
    declared = set(recipe.get('variables', {}))
    for text in _strings({k: v for k, v in recipe.items() if k != 'verified_run'}):
        if PLACEHOLDER.search(text):
            found.append(f'placeholder text: {text[:80]!r}')
        for name in VARIABLE.findall(text):
            if name not in declared:
                found.append(f'undeclared variable ${{{name}}}')
    for feature in recipe['features']:
        doc = directory / feature['doc']
        if not doc.is_file():
            found.append(f'feature doc missing: {feature["doc"]}')
        elif PLACEHOLDER.search(doc.read_text()):
            found.append(f'placeholder text in {feature["doc"]}')
    if recipe['status'] == 'verified':
        run = recipe.get('verified_run')
        if not run or not run.get('evidence'):
            found.append('verified recipe has no recorded run evidence')
        else:
            root = Path(directory).resolve()
            for item in run['evidence']:
                rel = Path(item['path'])
                path = (directory / rel).resolve()
                if rel.is_absolute() or '..' in rel.parts or not path.is_relative_to(root):
                    found.append(f'evidence path escapes the recipe directory: {item["path"]}')
                elif not path.is_file():
                    found.append(f'evidence missing: {item["path"]}')
                elif sha256_file(path) != item['sha256']:
                    found.append(f'evidence changed: {item["path"]}')
    return found


def check(path: Path) -> dict:
    path = Path(path)
    try:
        recipe = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidInput('recipe_unreadable', f'cannot read recipe: {exc}') from exc
    found = problems(recipe, path.parent)
    return {'valid': not found, 'status': recipe.get('status'), 'problems': found,
            'features': [f['id'] for f in recipe.get('features', [])]}


def _render(text: str, values: dict) -> str:
    def swap(match):
        key = match.group(1).strip()
        if key not in values:
            raise InvalidInput('template_value', f'template needs a value for {key}')
        return str(values[key])
    return re.sub(r'\{\{\s*([a-z_]+)\s*\}\}', swap, text)


def scaffold(facts: dict, template_dir: Path, repo_root: Path) -> dict:
    """Write .agents/skills/verify-<project>/ from discovered facts. Status stays draft."""
    schema.validate(facts, 'recipe-facts', 'facts_invalid')
    slug = facts['project']
    if not SLUG.match(slug):
        raise InvalidInput('project_slug', 'project slug is lowercase letters, digits and dashes')
    root = Path(repo_root).resolve()
    target = root
    for part in ('.agents', 'skills', f'verify-{slug}'):
        target = target / part
        if target.is_symlink():
            raise InvalidInput('path_escape', 'recipe destination component is a symlink', {'path': str(target)})
    for path in (target / 'features',):
        if path.is_symlink():
            raise InvalidInput('path_escape', 'recipe destination component is a symlink', {'path': str(path)})
    features = facts['features'][:5]
    recipe = {
        'schema_version': 1, 'project': slug, 'status': 'draft',
        'prerequisites': facts['prerequisites'], 'variables': facts.get('variables', {}),
        'launch': facts['launch'], 'doctor': facts['doctor'], 'cleanup': facts['cleanup'],
        'evidence': {'dir': 'evidence', 'expected': [f['observe'] for f in features]},
        'features': [{'id': f['id'], 'name': f['name'], 'doc': f'features/{f["id"].lower()}.md',
                      'steps': f['steps'], 'expect': f['expect']} for f in features],
        'verified_run': None,
    }
    feature_template = (Path(template_dir) / 'feature.md').read_text()
    skill_template = (Path(template_dir) / 'verify-project.md').read_text()
    for feature, spec in zip(recipe['features'], features):
        text = _render(feature_template, {
            'feature_id': spec['id'], 'feature_name': spec['name'], 'purpose': spec['purpose'],
            'steps': '\n'.join(f'{n}. `{json.dumps(step)}`' for n, step in enumerate(spec['steps'], 1)),
            'expect': '\n'.join(f'- `{json.dumps(item)}`' for item in spec['expect']),
            'observe': spec['observe']})
        atomic_write_bytes(target / feature['doc'], text.encode())
    index = ['# Feature index', ''] + [f'- [{f["id"]}]({Path(f["doc"]).name}): {f["name"]}' for f in recipe['features']]
    atomic_write_bytes(target / 'features' / 'index.md', ('\n'.join(index) + '\n').encode())
    skill = _render(skill_template, {
        'project': slug, 'prerequisites': ', '.join(facts['prerequisites']),
        'launch': ' '.join(facts['launch']['argv']), 'ready': json.dumps(facts['launch']['ready']),
        'doctor': '\n'.join('- `' + ' '.join(item['argv']) + '`' for item in facts['doctor']),
        'cleanup': '\n'.join('- `' + ' '.join(item['argv']) + '`' for item in facts['cleanup']),
        'features': '\n'.join(f'- {f["id"]}: {f["name"]}' for f in recipe['features'])})
    atomic_write_bytes(target / 'SKILL.md', skill.encode())
    atomic_json(target / 'recipe.json', recipe)
    found = problems(recipe, target)
    if found:
        raise InvalidInput('recipe_invalid', 'scaffolded recipe failed its own check', {'problems': found})
    return {'dir': str(target), 'recipe': str(target / 'recipe.json'), 'status': 'draft',
            'features': [f['id'] for f in recipe['features']]}


def stamp(recipe_path: Path, state: dict, run_dir: Path, feature_id: str, requirement_id: str) -> dict:
    """Mark verified from a run whose runtime acceptance for this feature passed and
    whose evidence artifacts still exist. Copies the evidence beside the recipe."""
    recipe_path = Path(recipe_path)
    recipe = json.loads(recipe_path.read_text())
    if state['phase'] != 'completed':
        raise Prohibited('run_not_completed', 'stamp only from a completed run; its evidence was valid at completion')
    if feature_id not in {f['id'] for f in recipe['features']}:
        raise InvalidInput('feature', f'recipe has no feature {feature_id}')
    entry = None
    for item in reversed(state.get('acceptance', [])):
        if item['requirement_id'] == requirement_id and not item.get('invalidated'):
            entry = item
            break
    if not entry or entry['status'] != 'passed' or entry['kind'] != 'runtime':
        raise Prohibited('recipe_unproven', 'stamping needs a passed runtime acceptance from an actual run')
    target = recipe_path.parent / 'evidence' / state['run_id']
    for part in (recipe_path.parent / 'evidence', target):
        if part.is_symlink():
            raise InvalidInput('path_escape', 'recipe evidence directory is a symlink', {'path': str(part)})
    copied = []
    root = Path(run_dir).resolve()
    for artifact in entry['artifacts']:
        rel = Path(artifact['path'])
        source = (Path(run_dir) / rel).resolve()
        if rel.is_absolute() or '..' in rel.parts or not source.is_relative_to(root):
            raise InvalidInput('path_escape', 'run evidence path escapes the run directory', {'path': artifact['path']})
        if not source.is_file() or sha256_file(source) != artifact['sha256']:
            raise Prohibited('evidence_missing', f'run evidence {artifact["path"]} is missing or changed')
        destination = target / Path(artifact['path']).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or not destination.parent.resolve().is_relative_to(recipe_path.parent.resolve()):
            raise InvalidInput('path_escape', 'evidence destination escapes the recipe directory', {'path': str(destination)})
        shutil.copyfile(source, destination)
        copied.append({'path': destination.relative_to(recipe_path.parent).as_posix(), 'sha256': artifact['sha256']})
    recipe['status'] = 'verified'
    recipe['verified_run'] = {'run_id': state['run_id'], 'feature': feature_id, 'requirement_id': requirement_id,
                              'recorded_at': entry['recorded_at'], 'head': entry['snapshot']['head'], 'evidence': copied}
    found = problems(recipe, recipe_path.parent)
    if found:
        raise InvalidInput('recipe_invalid', 'recipe failed its check after stamping', {'problems': found})
    atomic_json(recipe_path, recipe)
    return {'status': 'verified', 'evidence': copied}
