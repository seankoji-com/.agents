"""Read routing data with human-facing metadata from canonical skill frontmatter."""
import json
from pathlib import Path

from source_runtime.layout import frontmatter


def load(path):
    path = Path(path)
    result = json.loads(path.read_text())
    candidates = [path.parent/'SKILL.md', path.parents[2]/'skills'/path.parent.name/'SKILL.md']
    skill = next((file for file in candidates if file.is_file()),None)
    if skill is not None:
        result = enrich(result,skill.read_bytes())
    return result


def enrich(result,raw):
    metadata,_ = frontmatter(raw)
    if result['name'] != metadata['name']:
        raise ValueError('skill and routing manifest names differ')
    if any(field in result for field in ('description','short_description','argument_hint')):
        raise ValueError('skill frontmatter exclusively owns description and invocation hints')
    return {**result,'description':metadata['description']}
