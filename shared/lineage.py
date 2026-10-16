"""Canonical default lineage labels shared by routing and job evidence."""
import re

DRIVER_LINEAGE = {'claudeAgent': 'anthropic', 'codex': 'openai', 'antigravity': 'google', 'grok': 'xai', 'muse': 'meta'}
FAMILY_LINEAGE = {'claude': 'anthropic', 'gpt': 'openai', 'o': 'openai', 'gemini': 'google', 'grok': 'xai', 'muse': 'meta'}
MULTI_LINEAGE_DRIVERS = {'opencode', 'cursor', 'pi'}


def lineage(driver: str, model: str) -> str:
    if driver not in MULTI_LINEAGE_DRIVERS and driver in DRIVER_LINEAGE:
        return DRIVER_LINEAGE[driver]
    family = re.match(r'[a-z]+', model.rsplit('/', 1)[-1].lower())
    if not family:
        return 'unknown'
    return FAMILY_LINEAGE.get(family.group(0), family.group(0))
