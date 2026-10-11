"""Provider-neutral additional review perspectives, owned by the run engine."""
import re

from .errors import InvalidInput


def perspectives(policy):
    additional = policy.get('perspectives', {})
    if (not isinstance(additional, dict) or len(additional) > 10
            or any(not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', key) or key == 'default'
                   or not isinstance(value, str) or not value.strip()
                   for key, value in additional.items())):
        raise InvalidInput('review_perspectives', 'perspectives must map up to 10 distinct names to nonempty briefs; default is reserved')
    if additional and not policy.get('required'):
        raise InvalidInput('review_perspectives', 'additional perspectives require review.required')
    return [{'id': 'default', 'brief': ''}] + [
        {'id': key, 'brief': value} for key, value in additional.items()]
