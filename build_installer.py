"""Build a per-user Windows installer from a committed, checked onedir bundle."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from app_config import VERSION
from release_layout import PUBLIC_DOCS,verify_public_layout

ROOT=Path(__file__).resolve().parent


def compile_installer(bundle=None,output=None,version=VERSION,test_root=None,test_id=None,output_name=None):
    if sys.platform!='win32':raise RuntimeError('The installer must be compiled on Windows.')
    bundle=Path(bundle or ROOT/'dist/Orbita').resolve()
    if not (bundle/'Orbita.exe').is_file():raise ValueError('Windows executable missing')
    manifest=json.loads((bundle/'release-manifest.json').read_text(encoding='utf-8'))
    # Only the historical, already checked payload in an isolated test build
    # may use its original documentation layout.
    documents=tuple(name for name in PUBLIC_DOCS if name!='INSTALLATION.md') if test_root and manifest['version']=='0.9.1' else PUBLIC_DOCS
    verify_public_layout(bundle,public_docs=documents)
    if not test_root and (manifest['version']!=version or manifest.get('source_dirty',True)):
        raise ValueError('Installer requires a clean bundle matching the release version')
    if not test_root:
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        if manifest.get('source_commit')!=head:raise ValueError('Rebuild the bundle from the current commit before compiling the installer')
    compiler=Path(os.environ.get('ORBITA_ISCC',str(ROOT/'.build-tools/inno/ISCC.exe')))
    if not compiler.is_file():raise RuntimeError('Set ORBITA_ISCC to Inno Setup 7.1+ ISCC.exe.')
    output=Path(output or ROOT/'dist/releases').resolve();output.mkdir(parents=True,exist_ok=True)
    defines=[f'/DBundleDir={bundle}',f'/DProductVersion={version}',f'/DOutputPath={output}']
    if test_root is not None:
        test_root=Path(test_root).resolve()
        if not test_root.is_relative_to((ROOT/'data/installer-tests').resolve()) or not re.fullmatch('[a-zA-Z0-9-]{1,48}',test_id or ''):
            raise ValueError('Isolated installers must stay under data/installer-tests with a unique safe ID')
        defines += [f'/DTestRoot={test_root}',f'/DTestId={test_id}']
    name=output_name or f'Orbita-Setup-{version}-Windows-x64'
    if not re.fullmatch('[a-zA-Z0-9._-]+',name):raise ValueError('Unsafe output name')
    defines.append('/DOutputName='+name)
    subprocess.run([str(compiler),'/Qp',*defines,str(ROOT/'installer/Orbita.iss')],cwd=ROOT,check=True)
    target=output/(name+'.exe')
    if not target.is_file():raise RuntimeError('Compiler did not produce an installer')
    if not test_root:
        from release_artifacts import sha256
        (output/'installer-manifest.json').write_text(json.dumps({'version':version,'source_commit':manifest['source_commit'],
            'filename':target.name,'sha256':sha256(target),'privileges':'current-user','signed':False},indent=2),encoding='utf-8')
    return target


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    print(compile_installer(output=args.output))


if __name__=='__main__':main()
