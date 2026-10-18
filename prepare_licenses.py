"""Fetch upstream source archives and collect their unmodified license notices.

Downloads are explicit, cached under ignored data/, and never executed. The full
archives are retained for distribution alongside the corresponding binary release.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
QT_VERSION = '6.12.0'
MODULES = ('qtbase', 'qtdeclarative', 'qtsvg', 'qtimageformats', 'qtpositioning', 'qtserialport')


def download(name, url):
    target = ROOT / 'data' / 'release-sources' / url.rsplit('/', 1)[-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    # MirrorBrain publishes the expected hash on the official HTTPS page.
    # Pick a listed HTTPS mirror without weakening TLS validation.
    with urlopen(url + '.mirrorlist', timeout=30) as response:
        listing = response.read().decode('utf-8')
    match = re.search(r'SHA-256 Hash</a>:</span>\s*<tt>([0-9a-f]{64})</tt>', listing)
    if not match:
        raise ValueError('Official source SHA-256 unavailable: ' + name)
    expected = match.group(1)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + '.part')
        candidates = re.findall(r'href="(https://[^"<>]+' + re.escape(target.name) + r')"', listing)
        candidates = sorted(set(candidates), key=lambda value: ('qt.mirror.constant.com' not in value, value))
        for mirror in candidates[:3]:
            try:
                with urlopen(Request(mirror, method='HEAD'), timeout=15) as response:
                    size = int(response.headers['Content-Length'])
                offset = temporary.stat().st_size if temporary.exists() else 0
                if offset > size:
                    raise ValueError('Partial archive larger than upstream file')
                # Bounded ranges survive interrupted large transfers without
                # repeatedly downloading the beginning of the same archive.
                def fetch_range(start):
                    end = min(start + 1024 * 1024, size) - 1
                    for attempt in range(3):
                        try:
                            request = Request(mirror, headers={'Range': f'bytes={start}-{end}', 'User-Agent': 'Orbita-license-preparation'})
                            with urlopen(request, timeout=20) as response:
                                if response.status != 206 or not response.headers.get('Content-Range','').startswith(f'bytes {start}-'):
                                    raise OSError('Mirror did not honor byte range')
                                chunk = response.read()
                            if len(chunk) != end-start+1:
                                raise OSError('Incomplete source range')
                            return chunk
                        except OSError:
                            if attempt == 2:raise
                # Keep memory and concurrent requests bounded; write in order so
                # the partial file is always a resumable prefix of the archive.
                while offset < size:
                    starts = list(range(offset, min(offset+4*1024*1024,size),1024*1024))
                    with ThreadPoolExecutor(max_workers=4) as pool:
                        for chunk in pool.map(fetch_range,starts):
                            with temporary.open('ab') as stream:stream.write(chunk)
                            offset += len(chunk)
                break
            except OSError:
                continue
        else:
            raise RuntimeError('Listed HTTPS source mirrors unavailable: ' + name)
        temporary.replace(target)
    with target.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    if checksum != expected:
        raise ValueError('Upstream SHA-256 mismatch: ' + name)
    notices = ROOT / 'licenses' / name
    count = 0
    with tarfile.open(target, 'r:xz') as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts[1:]
            if not member.isfile() or not parts or '..' in parts or member.size > 1024 * 1024:
                continue
            basename = parts[-1].lower()
            if not ('LICENSES' in parts or re.match(r'^(license|licence|copying|notice|copyright)(?:$|[._-])', basename)
                    or basename == 'qt_attribution.json'):
                continue
            # Copy only textual notices, never executable source or symbolic links.
            raw = archive.extractfile(member).read()
            try:
                raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
            if b'\0' in raw:
                continue
            destination = notices.joinpath(*parts)
            if not destination.resolve().is_relative_to(notices.resolve()):
                raise ValueError('Notice path escapes destination')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            count += 1
    print(name, 'source bytes', target.stat().st_size, 'notice files', count, flush=True)
    return {'name': name, 'version': QT_VERSION, 'url': url, 'archive': target.name,
            'sha256': checksum, 'official_sha256_verified': True, 'notice_files': count}


def main():
    sources = [(module, f'https://download.qt.io/official_releases/qt/6.12/{QT_VERSION}/submodules/{module}-everywhere-src-{QT_VERSION}.tar.xz')
               for module in MODULES]
    sources.append(('pyside-setup', f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{QT_VERSION}-src/pyside-setup-everywhere-src-{QT_VERSION}.tar.xz'))
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda item: download(*item), sources))
    (ROOT / 'licenses' / 'sources.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print('Retained full library sources under data/release-sources; notices under licenses/.')


if __name__ == '__main__':
    main()
