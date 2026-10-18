"""Explicit public release layout. Development logs and user data stay in source/profile."""
from pathlib import Path
import shutil

PUBLIC_DOCS=('START_HERE.md','USER_GUIDE.md','PRIVACY.md','PORTABLE.md','LICENSES.md')
PUBLIC_LEGAL=('LICENSE','THIRD_PARTY_NOTICES.md')


def copy_public_files(root,destination):
    root=Path(root);destination=Path(destination);docs=destination/'docs';docs.mkdir(parents=True,exist_ok=True)
    # The builder supplies a fresh destination. Refuse to retain stray old docs.
    for old in docs.iterdir():
        if old.is_file() and old.name not in PUBLIC_DOCS+('MANUAL.md',):old.unlink()
    for name in PUBLIC_DOCS:shutil.copy2(root/'release_docs'/name,docs/name)
    guide=(root/'release_docs/USER_GUIDE.md').read_text(encoding='utf-8')
    (docs/'MANUAL.md').write_text(guide,encoding='utf-8')
    root_guide=guide
    for name in PUBLIC_DOCS:root_guide=root_guide.replace(']('+name+')','](docs/'+name+')')
    (destination/'MANUAL.md').write_text(root_guide,encoding='utf-8')
    shutil.copytree(root/'training',destination/'training',dirs_exist_ok=True)
    for name in PUBLIC_LEGAL:shutil.copy2(root/name,destination/name)
    shutil.copytree(root/'licenses',destination/'licenses',dirs_exist_ok=True)


def verify_public_layout(destination):
    destination=Path(destination)
    expected=set(PUBLIC_DOCS)|{'MANUAL.md'}
    actual={p.name for p in (destination/'docs').iterdir()}
    if actual!=expected:raise RuntimeError('Unexpected release documentation: '+repr(actual^expected))
    for name in PUBLIC_LEGAL+('licenses/README.md','licenses/sources.json'):
        if not (destination/name).is_file():raise RuntimeError('Missing legal notice: '+name)
    for p in destination.rglob('*'):
        if p.is_file() and (p.suffix in ('.dpapi','.log','.pfx','.p12','.key') or '.sqlite' in p.name.lower()
                or p.name.startswith('.env') or p.name in ('mail.local.json','AGENTS.md','HANDOFF.md')
                or 'virtualkeyboard' in p.name.lower() or p.name.lower() in ('qt6pdf.dll','qpdf.dll')):
            raise RuntimeError('Forbidden file in release: '+p.name)
