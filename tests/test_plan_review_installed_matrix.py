"""Final source/relocated installed matrix through real public acceptance paths.

Reuse the domain scenarios rather than a parallel mock validator. Every installation
is moved and explicitly adopted before any job pins it; original package files are gone.
Only host model observations are synthetic. No live models or GitHub are called.
"""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_rebuild_installed import Sandbox, ROOT
from shared import worker_registry as registry


def relocate(box, packages):
    old = box.prefix
    moved = box.base / 'relocated-prefix'
    shutil.move(old, moved)
    box.prefix = moved
    box.t3('adopt', '--from-prefix', old)
    if any((old / name / package.name).exists() for name, (package, _) in packages.items()):
        raise AssertionError('relocation test retained an original package')
    return {name: (moved / name / package.name,
                   json.loads((moved / name / package.name / 'install-manifest.json').read_text()))
            for name, (package, _) in packages.items()}


class PackagingAcceptance(unittest.TestCase):
    def test_every_worker_bundle_and_adapter_carries_only_supported_contracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            packages = {p.name: box.install(p.name) for p in (ROOT / 'plugins').iterdir()
                        if (p / 'plugin.json').is_file()}
            packages = relocate(box, packages)
            for plugin, (package, receipt) in packages.items():
                with self.subTest(plugin=plugin):
                    registry.verify_package_files(package, receipt)
                    declared = json.loads((package / 'plugin.json').read_text())
                    self.assertEqual(receipt['installation_id'],
                                     registry.installation_id(box.prefix, create=False))
                    if declared.get('workers'):
                        checked = registry.verify_bundle(Path(receipt['bundle_dir']),
                            receipt['installation_id'], plugin, package.name, registry.package_digest(receipt))
                        for worker in declared['workers']:
                            asset = next(a for a in checked['manifest']['assets'] if a.get('id') == worker['id'])
                            for key in ('operations', 'role', 'responsibility', 'allowed_scope', 'output_contract'):
                                self.assertEqual(asset[key], worker[key])
                            self.assertEqual(asset['allowed_scope'], registry.WORKER_SCOPES[worker['id']])
                        for name in registry.SHARED_REQUIRED:
                            self.assertEqual((package / 'shared/agents' / name).read_bytes(),
                                             (Path(receipt['bundle_dir']) / 'shared' / name).read_bytes())
                    else:
                        self.assertNotIn('bundle_dir', receipt)
                        self.assertNotIn('bundle_digest', receipt)
                    skills = box.home / 'skills'
                    box.t3('skills', 'install', plugin, '--root', skills)
                    adapter = skills / plugin / 'SKILL.md'
                    text = adapter.read_text()
                    frontmatter = text.split('---', 2)[1]
                    self.assertNotIn('model:', frontmatter)
                    self.assertNotIn('effort:', frontmatter)
                    self.assertIn(str(box.prefix / plugin / 'current/entry.md'), text)
                    marker = json.loads((adapter.parent / '.agents-skill.json').read_text())
                    self.assertEqual(marker['entry'], str(box.prefix / plugin / 'current/entry.md'))
                    self.assertFalse(list(skills.glob('*plan-reviewer*')))

    def test_real_installer_refuses_unsupported_or_weakened_worker_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            box = Sandbox(Path(temporary))
            for field, value in [('allowed_scope', 'unrestricted'), ('output_contract', 'anything.json'),
                                 ('operations', ['doctor']), ('model', 'invented-control')]:
                def mutate(plugin):
                    path = plugin / 'plugin.json'
                    data = json.loads(path.read_text())
                    data['workers'][0][field] = value
                    path.write_text(json.dumps(data))
                source = box.source_copy('ape', mutate=mutate)
                result = box.install('ape', source=source, check=False)
                self.assertNotEqual(result.returncode, 0, field)
                self.assertFalse((box.prefix / 'ape/current').exists())


if __name__ == '__main__':
    unittest.main()
