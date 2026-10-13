#!/usr/bin/env python3
"""Resolve selected aliases with primary provider metadata, without inference."""
import datetime
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
from urllib.parse import quote


def resolve_identity(provider, target):
    model = target['model']
    host, variable = (('api.anthropic.com', 'ANTHROPIC_API_KEY') if provider == 'claudeAgent'
                      else ('api.openai.com', 'OPENAI_API_KEY'))
    credential = os.environ.get(variable)
    if not credential:
        raise ValueError('gateway metadata credential is unavailable')
    path = '/v1/models/' + quote(model, safe='')
    headers = ({'x-api-key': credential, 'anthropic-version': '2023-06-01'} if provider == 'claudeAgent'
               else {'Authorization': 'Bearer ' + credential})
    connection = http.client.HTTPSConnection(host, timeout=20, context=ssl.create_default_context())
    try:
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        raw = response.read(131073)
        if response.status != 200 or len(raw) > 131072:
            raise ValueError('primary provider metadata response is unavailable or oversized')
        data = json.loads(raw)
        canonical = data.get('id') if isinstance(data, dict) else None
        family = r'claude-haiku-[0-9]+(?:-[0-9]+)*' if provider == 'claudeAgent' else r'gpt-[0-9]+(?:\.[0-9]+)?-luna'
        if not isinstance(canonical, str) or not re.fullmatch(family, canonical):
            raise ValueError('primary provider metadata did not resolve a permitted model identity')
        return {'provider_instance_id': provider, 'requested_model_id': model,
                'response_model_id': canonical, 'source': 'https://' + host + path,
                'http_status': response.status, 'response_sha256': hashlib.sha256(raw).hexdigest(),
                'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    finally:
        connection.close()


def valid_identity(record, provider, requested):
    source = 'https://' + ('api.anthropic.com' if provider == 'claudeAgent' else 'api.openai.com') + '/v1/models/' + quote(requested, safe='')
    return (isinstance(record, dict) and record.get('provider_instance_id') == provider and
            record.get('requested_model_id') == requested and record.get('source') == source and
            record.get('http_status') == 200 and isinstance(record.get('response_model_id'), str) and
            bool(record['response_model_id']) and isinstance(record.get('observed_at'), str) and
            re.fullmatch(r'[0-9a-f]{64}', str(record.get('response_sha256', ''))) is not None)


if __name__ == '__main__':
    try:
        from gateway import read_policy
        targets = json.loads(sys.argv[1])
        read_policy_targets = {'schema_version': 1, 'targets': targets}
        # The caller passes catalog-validated low-cost targets. Independently
        # validate them again through the same gateway contract before any GET.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / 'policy.json'; policy.write_text(json.dumps(read_policy_targets))
            read_policy(policy)
        records = {provider: resolve_identity(provider, target) for provider, target in targets.items()}
        print(json.dumps({'verified': True, 'identities': records}, sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, IndexError, http.client.HTTPException) as exc:
        print(json.dumps({'verified': False, 'reason': 'primary metadata unavailable: ' + type(exc).__name__}))
        sys.exit(1)
