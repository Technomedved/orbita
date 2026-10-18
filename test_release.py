"""Distribution guardrails: private files, unused Qt modules and source integrity."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from app_config import VERSION
from release_artifacts import package,sha256
from release_layout import copy_public_files,verify_public_layout


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bundle=self.root/'dist/Orbita'
        copy_public_files(Path(__file__).resolve().parent,self.bundle)

    def test_legal_texts_are_part_of_public_bundle(self):
        verify_public_layout(self.bundle)
        self.assertIn('MIT License',(self.bundle/'LICENSE').read_text())
        self.assertTrue((self.bundle/'licenses/qtbase/LICENSES/LGPL-3.0-only.txt').exists())

    def test_forced_private_files_and_unneeded_plugins_are_rejected(self):
        for name in ['inbox.sqlite-wal','.env.production','private.pfx','Qt6VirtualKeyboard.dll','qpdf.dll']:
            path=self.bundle/name;path.write_text('fixture')
            with self.assertRaises(RuntimeError):verify_public_layout(self.bundle)
            path.unlink()

    def test_missing_or_changed_library_sources_prevent_packaging(self):
        (self.bundle/'release-manifest.json').write_text(json.dumps({'version':VERSION,'source_commit':'fixture','source_dirty':False}))
        source_dir=self.root/'data/release-sources';source_dir.mkdir(parents=True)
        archive=source_dir/'test.tar.xz';archive.write_bytes(b'upstream fixture')
        (self.bundle/'licenses/sources.json').write_text(json.dumps([{'archive':archive.name,'sha256':sha256(archive),'official_sha256_verified':True}]))
        with patch('release_artifacts.subprocess.check_output',return_value='fixture'):
            archive.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'missing or changed'):package(self.root)

    def test_dirty_build_prevents_packaging(self):
        (self.bundle/'release-manifest.json').write_text(json.dumps({'version':VERSION,'source_dirty':True}))
        with self.assertRaisesRegex(ValueError,'clean committed'):package(self.root)

    def test_archives_contain_inventory_sources_and_matching_checksums(self):
        (self.bundle/'release-manifest.json').write_text(json.dumps({'version':VERSION,'source_commit':'fixture','source_dirty':False}))
        source_dir=self.root/'data/release-sources';source_dir.mkdir(parents=True)
        source=source_dir/'test.tar.xz';source.write_bytes(b'upstream fixture')
        (self.bundle/'licenses/sources.json').write_text(json.dumps([{'archive':source.name,'sha256':sha256(source),'official_sha256_verified':True}]))
        with patch('release_artifacts.subprocess.check_output',return_value='fixture'),patch('builtins.print'):
            portable,libraries,checksums=package(self.root)
        with zipfile.ZipFile(portable) as archive:
            inventory=json.loads(archive.read('Orbita/bundle-inventory.json'))
            self.assertIn('LICENSE',{entry['path'] for entry in inventory})
            self.assertEqual(archive.read('Orbita/LICENSE'),(self.bundle/'LICENSE').read_bytes())
        with zipfile.ZipFile(libraries) as archive:
            self.assertEqual(archive.read(source.name),source.read_bytes())
        lines=checksums.read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines,[sha256(portable)+'  '+portable.name,sha256(libraries)+'  '+libraries.name])


if __name__=='__main__':unittest.main()
