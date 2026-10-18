"""Native desktop build. Run separately on each target desktop OS."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import platform
from datetime import datetime,timezone
from app_config import VERSION
from release_layout import copy_public_files,verify_public_layout


ROOT=Path(__file__).resolve().parent


def build():
    if sys.platform not in ('win32','darwin','linux'):raise SystemExit('This builder targets desktop OSes only.')
    env=dict(os.environ)
    if sys.platform=='win32' and sys.version_info[:2]==(3,12):
        # Avoid collecting unrelated DLLs from developer tools in PATH (e.g.
        # Poppler's ICU). Qt hooks already know their own library directories.
        env['PATH']=os.pathsep.join([str(Path(os.environ['WINDIR'])/'System32'),os.environ['WINDIR'],str(Path(sys.executable).parent)])
        local=[str(ROOT/name) for name in ('.build-tools','.ui-runtime') if (ROOT/name).is_dir()]
        if local:
            env['PYTHONPATH']=os.pathsep.join(local+([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    command=[sys.executable,'-m','PyInstaller','--noconfirm',str(ROOT/'Orbita.spec')]
    subprocess.run(command,cwd=ROOT,env=env,check=True)
    destination=ROOT/'dist'/'Orbita'
    if sys.platform=='win32':
        collected=destination/'_internal'/'icuuc.dll'
        if collected.exists():
            if not (Path(os.environ['WINDIR'])/'System32'/'icuuc.dll').exists():raise RuntimeError('Windows ICU is required for this Qt build.')
            collected.unlink()
    elif sys.platform=='darwin':destination=ROOT/'dist'/'Orbita.app'/'Contents'/'Resources'
    destination.mkdir(parents=True,exist_ok=True)
    copy_public_files(ROOT,destination)
    verify_public_layout(destination)
    (destination/'README.txt').write_text('Орбита '+VERSION+'\nЗапуск: Orbita.exe на Windows; для других ОС нужен собственный пакет.\n'
        'Сохраняйте программу вместе с её зависимостями. Python и Codex для запуска не нужны.\nРуководство: docs/USER_GUIDE.md\nНачало работы: docs/START_HERE.md\n'
        'Новый профиль пустой, шаблоны автоматизаций выключены. Данные сохраняются отдельно в профиле текущего пользователя.\n',encoding='utf-8')
    manifest={'version':VERSION,'platform':sys.platform,'python':sys.version.split()[0],
              'architecture':platform.machine(),
              'built_at_utc':datetime.now(timezone.utc).isoformat(),
              'documentation':[str(p.relative_to(destination)) for p in sorted((destination/'docs').glob('*.md'))]}
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
    changes=subprocess.run(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,capture_output=True,text=True)
    manifest['source_commit']=revision.stdout.strip() if revision.returncode==0 else None
    manifest['source_dirty']=bool(changes.stdout.strip()) if changes.returncode==0 else True
    manifest['signed']=False
    (destination/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Orbita '+VERSION+' ready: '+str(destination))


if __name__=='__main__':build()
