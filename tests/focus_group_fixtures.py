"""Invented capture packs for the focus-group tests: small real PNGs, page text and manifests.

Everything here is invented. Packs are written into a test's temporary directory and validated
through `plugins/focus-group/scripts/evidence.py pack`, the same entry point the coordinator uses.
"""
import hashlib
import json
import struct
import zlib
from pathlib import Path

PROFILE = {'label': 'phone', 'viewport': {'width': 390, 'height': 844}, 'extra_views': ['recipe detail', 'shopping list']}
CAPTURED_AT = '2029-05-31T23:00:00Z'
PAGE_TEXT = ('Pantry Planner (invented prototype)\nPlan three dinners in a few taps.\n'
             'Browse recipes, add them to a plan and open the shopping list.\n')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF)


def with_chunk(data, kind, body):
    """`data` (a PNG from `png`) with one more chunk straight after IHDR."""
    return data[:33] + chunk(kind, body) + data[33:]


def png(width, height, bands=((240, 240, 236), (32, 96, 64)), text_chunks=()):
    """An RGB PNG with horizontal colour bands (one band means a blank image). Rows use filter 0."""
    band = max(1, height // len(bands))
    rows = b''.join(b'\0' + bytes(bands[min(y // band, len(bands) - 1)]) * width for y in range(height))
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    for key, value in text_chunks:
        out += chunk(b'tEXt', key.encode() + b'\0' + value.encode())
    return out + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')


def inspection(names, **flags):
    row = {'viewed': True, 'blank': False, 'error_page': False, 'secrets_visible': False, 'personal_data_visible': False}
    return {'inspector': 'coordinator', 'inspected_at': '2029-05-31T23:10:00Z',
            'files': {name: dict(row, **flags.get(name, {})) for name in names}}


def write_pack(folder: Path, prefix='', text=PAGE_TEXT, initial=None, profile=PROFILE):
    """Write an initial viewport, two extra views and page text; return manifest file rows."""
    folder.mkdir(parents=True, exist_ok=True)
    vw, vh = profile['viewport']['width'], profile['viewport']['height']
    files = [(f'{prefix}initial-viewport.png', 'initial-viewport', None, initial or png(vw, vh), 'image/png'),
             (f'{prefix}recipe-detail.png', 'view', 'recipe detail', png(vw, vh, ((250, 250, 250), (180, 40, 40))),
              'image/png'),
             (f'{prefix}shopping-list.png', 'view', 'shopping list', png(vw, vh, ((20, 20, 20), (200, 200, 90))),
              'image/png'),
             (f'{prefix}welcome.txt', 'text', None, text.encode(), 'text/plain')]
    rows = []
    for name, role, view, data, media in files:
        path = folder / name
        path.write_bytes(data)
        rows.append({'name': name, 'role': role, 'view': view, 'path': str(path), 'sha256': sha(data),
                     'bytes': len(data), 'media_type': media})
    return rows


def manifest(files, url='https://staging.pantry-planner.example/welcome', **changes):
    """A capture manifest from a verified fresh anonymous host context."""
    value = {
        'schema_version': 1, 'kind': 'capture', 'attempt': {'number': 1, 'previous_manifest_sha256': None},
        'context': {'class': 'fresh-anonymous', 'reference': 'fixture-host-capture-context-1',
                    'freshness': {'verified': True, 'method': 'fixture: new host context with empty storage',
                                  'observed_at': '2029-05-31T22:59:00Z'},
                    'pre_existing_state': {'cookies': [], 'storage': [], 'onboarding': 'none'}, 'user_state': 'new',
                    'approval': None},
        'request': {'requested_url': url, 'final_url': url, 'http_status': 200}, 'supplied': None,
        'captured_at': CAPTURED_AT, 'profile': json.loads(json.dumps(PROFILE)),
        'readiness': {'state': 'ready', 'signal': 'fixture: main heading visible', 'observed_at': CAPTURED_AT},
        'files': files, 'limits': {'max_files': 8, 'max_file_bytes': 4 * 1024 * 1024},
        'device_access_not_exercised': ['screen reader', 'switch access', 'slow network'],
        'inspection': inspection([f['name'] for f in files]), 'derived_from': None}
    value.update(changes)
    return value
