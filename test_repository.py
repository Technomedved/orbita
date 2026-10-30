"""Keep private backup artifacts out of Git, including forced staged additions."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from check_repository import findings


ROOT = Path(__file__).resolve().parent
PRIVATE_FILE = 'local/private/generated file'


def archive_bytes(name, content):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return stream.getvalue()


class RepositoryTests(unittest.TestCase):
    def test_small_backup_archives_are_rejected_at_any_depth_and_case(self):
        content = archive_bytes('inbox.sqlite', b'synthetic database fixture')
        self.assertLess(len(content), 5 * 1024 * 1024)
        for name in ('manual.orbita.zip', 'copies/manual.orbita.zip',
                     'copies/Nested/Manual.OrBiTa.ZiP'):
            with self.subTest(name=name):
                self.assertEqual(findings(name, content), [PRIVATE_FILE])

    def test_backup_metadata_and_restore_contents_are_private(self):
        for name in ('.backup-device.json', 'profiles/.BACKUP-DEVICE.JSON',
                     '.auto-backups.json', 'profiles/.Auto-Backups.Json',
                     '.restore/journal.json', 'profiles/.ReStOrE/nested/pending.json'):
            with self.subTest(name=name):
                self.assertEqual(findings(name, b'{"fixture": true}'), [PRIVATE_FILE])

    def test_public_sources_and_unrelated_archives_remain_allowed(self):
        content = archive_bytes('README.md', b'Public library source fixture')
        self.assertEqual(findings('licenses/library-sources.zip', content), [])
        for name in ('docs/backup.orbita.zip.md', 'docs/.restore-guide.md', '.env.example'):
            with self.subTest(name=name):
                self.assertEqual(findings(name, b'Public example'), [])
        for name in ('check_repository.py', 'run_checks.py', 'test_repository.py', 'backup_service.py'):
            with self.subTest(name=name):
                self.assertEqual(findings(name, (ROOT / name).read_bytes()), [])

    def test_forced_ignored_backup_is_checked_from_index_not_worktree(self):
        # Inherited Git routing/configuration must never target the caller's index.
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                   PYTHONIOENCODING='utf-8')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return subprocess.run(['git', *args], cwd=root, env=env, check=True,
                                      capture_output=True, text=True, encoding='utf-8', timeout=15)

            def audit():
                return subprocess.run([sys.executable, str(ROOT / 'check_repository.py')],
                                      cwd=root, env=env, capture_output=True, text=True,
                                      encoding='utf-8', timeout=15)

            git('init', '--quiet')
            self.assertEqual(Path(git('rev-parse', '--show-toplevel').stdout.strip()).resolve(),
                             root.resolve())
            (root / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
            git('add', '--', '.gitignore')
            name = 'copies/manual.orbita.zip'
            backup = root / name
            backup.parent.mkdir()
            content = archive_bytes('inbox.sqlite', b'synthetic database fixture')
            backup.write_bytes(content)
            git('check-ignore', '--quiet', '--', name)
            git('add', '--force', '--', name)

            # Removing the working file cannot hide the private blob already staged.
            backup.unlink()
            result = audit()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(name + ': ' + PRIVATE_FILE, result.stdout)
            self.assertIn('Checked 2 staged files; 1 findings.', result.stdout)
            self.assertNotIn('synthetic database fixture', result.stdout + result.stderr)

            # Conversely, an ignored copy on disk is not part of the Git index.
            git('rm', '--cached', '--', name)
            backup.write_bytes(content)
            result = audit()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Checked 1 staged files; 0 findings.', result.stdout)


if __name__ == '__main__':
    unittest.main()
