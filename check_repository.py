"""Audit staged Git blobs without printing potential secret values. No dependencies."""
from pathlib import PurePosixPath
import re
import subprocess
import sys

FORBIDDEN_DIRS = {'data', 'dist', 'build', '.venv', '.ui-runtime', '.build-tools', 'history', '__pycache__'}
FORBIDDEN_NAMES = {'mail.local.json', 'setup-mail.ps1', 'set-mail-login.ps1', 'run.ps1',
                   'install-schedule.ps1', 'notification.glass.json', 'notification.management.json'}
BACKUP_NAMES = {'.backup-device.json', '.auto-backups.json'}
SECRET_PATTERNS = [
    re.compile(rb'gh[pousr]' + rb'_[A-Za-z0-9]{30,}'),
    re.compile(rb'github_' + rb'pat_[A-Za-z0-9_]{30,}'),
    re.compile(rb'-----BEGIN ' + rb'(?:[A-Z]+ )?PRIVATE KEY-----'),
]


def findings(name, content):
    path = PurePosixPath(name)
    lower_name = path.name.lower()
    # Git paths are POSIX, but Windows backup names are case-insensitive.
    backup_artifact = (lower_name.endswith('.orbita.zip') or lower_name in BACKUP_NAMES
                       or any(part.lower() == '.restore' for part in path.parts[:-1]))
    reasons = []
    if (backup_artifact or set(path.parts[:-1]) & FORBIDDEN_DIRS or path.name in FORBIDDEN_NAMES
            or path.suffix.lower() in {'.dpapi', '.pem', '.key', '.pfx', '.p12', '.log', '.exe', '.dll'}
            or '.sqlite' in path.name.lower()
            or (path.name.startswith('.env') and path.name != '.env.example')
            or ('release_docs', 'private') == path.parts[:2]):
        reasons.append('local/private/generated file')
    if len(content) > 5 * 1024 * 1024:
        reasons.append('file larger than 5 MiB; review before tracking')
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        reasons.append('possible credential/private key')
    return reasons


def main():
    paths = subprocess.run(['git', 'ls-files', '--cached', '-z'], check=True,
                           capture_output=True).stdout.split(b'\0')
    count = 0
    problems = []
    for raw in filter(None, paths):
        name = raw.decode('utf-8')
        blob = subprocess.run(['git', 'show', ':' + name], capture_output=True)
        if blob.returncode:
            problems.append((name, 'cannot read staged blob; check unresolved index'))
            continue
        count += 1
        problems.extend((name, reason) for reason in findings(name, blob.stdout))
    for name, reason in problems:
        print(name + ': ' + reason)
    print(f'Checked {count} staged files; {len(problems)} findings. Values are never printed.')
    if not count:
        print('No staged files to audit.')
        return 1
    return int(bool(problems))


if __name__ == '__main__':
    sys.exit(main())
