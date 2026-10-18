"""Create checked portable and LGPL source archives; never publishes anything."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
from app_config import VERSION
from release_layout import verify_public_layout

ROOT=Path(__file__).resolve().parent


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def package(root=ROOT):
    root=Path(root);bundle=root/'dist/Orbita';verify_public_layout(bundle)
    manifest=json.loads((bundle/'release-manifest.json').read_text(encoding='utf-8'))
    if manifest['version']!=VERSION or manifest.get('source_dirty',True):
        raise ValueError('Build must match current version and a clean committed source tree')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if head!=manifest.get('source_commit'):
        raise ValueError('Bundle source commit differs from HEAD; rebuild before packaging')
    sources=json.loads((bundle/'licenses/sources.json').read_text(encoding='utf-8'))
    if not sources:raise ValueError('Library source manifest is empty')
    for entry in sources:
        name=entry['archive']
        if Path(name).name!=name:raise ValueError('Unsafe source filename')
        path=root/'data/release-sources'/name
        if not entry.get('official_sha256_verified') or not path.is_file() or sha256(path)!=entry['sha256']:
            raise ValueError('Library source missing or changed: '+name)
    output=root/'dist/releases';output.mkdir(exist_ok=True)
    portable=output/f'Orbita-{VERSION}-Windows-x64.zip'
    libraries=output/f'Orbita-{VERSION}-library-sources.zip'
    installer_assets=[]
    installer=output/f'Orbita-Setup-{VERSION}-Windows-x64.exe'
    if installer.exists():
        setup_manifest=json.loads((output/'installer-manifest.json').read_text(encoding='utf-8'))
        if setup_manifest['source_commit']!=head or setup_manifest['version']!=VERSION or setup_manifest['sha256']!=sha256(installer):
            raise ValueError('Installer does not match the checked bundle')
        installer_assets.append(installer)
    inventory=[{'path':p.relative_to(bundle).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p)}
               for p in sorted(bundle.rglob('*')) if p.is_file()]
    with zipfile.ZipFile(portable,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for item in inventory:
            archive.write(bundle/item['path'],'Orbita/'+item['path'])
        archive.writestr('Orbita/bundle-inventory.json',json.dumps(inventory,indent=2))
    with zipfile.ZipFile(libraries,'w',zipfile.ZIP_STORED) as archive:
        for entry in sources:archive.write(root/'data/release-sources'/entry['archive'],entry['archive'])
        archive.write(bundle/'licenses/sources.json','sources.json')
        archive.write(bundle/'licenses/README.md','README.md')
    for path in (portable,libraries):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:raise ValueError('Archive integrity failure')
    checksums=output/'SHA256SUMS.txt'
    assets=[portable,libraries]+installer_assets
    checksums.write_text(''.join(sha256(p)+'  '+p.name+'\n' for p in assets),encoding='utf-8')
    print(json.dumps({'version':VERSION,'source_commit':head,'files':len(inventory),
        'assets':[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha256(p)} for p in assets],
        'checksums':checksums.name},indent=2))
    return portable,libraries,checksums


if __name__=='__main__':
    package()
