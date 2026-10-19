"""Real per-user setup/upgrade/uninstall in compiled, isolated test installers.

Never redirects Windows known folders, never modifies the real Orbita Run value,
and never removes the real default profile. Test paths are baked into test builds.
"""
import ctypes
import atexit
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid
import winreg
from app_config import VERSION
from build_installer import compile_installer
from windows_integration import instance_name

ROOT=Path(__file__).resolve().parent
RUN_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if sys.platform!='win32':raise SystemExit('Windows only')
    unique='test-'+uuid.uuid4().hex[:12]
    sandbox=(ROOT/'data/installer-tests'/('Проверка установки '+unique)).resolve();sandbox.mkdir(parents=True)
    assert sandbox.is_relative_to((ROOT/'data/installer-tests').resolve())
    old=ROOT/'data/backups/before-data-093/Orbita'
    old_version=json.loads((old/'release-manifest.json').read_text(encoding='utf-8'))['version']
    assert old_version=='0.9.2'
    baseline=compile_installer(bundle=old,version=old_version,test_root=sandbox,test_id=unique,output=sandbox/'artifacts',output_name='Baseline')
    current=compile_installer(test_root=sandbox,test_id=unique,output=sandbox/'artifacts',output_name='Upgrade')
    app=sandbox/'program';profile=sandbox/'profile';key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\Technomedved.Orbita.Test.'+unique+'_is1'
    startup='Orbita-Test-'+unique;results=[]
    def cleanup_test_autostart():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_SET_VALUE) as h:winreg.DeleteValue(h,startup)
        except FileNotFoundError:pass
    atexit.register(cleanup_test_autostart)
    def run(executable,*args,success=True):
        result=subprocess.run([str(executable),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',*map(str,args)],timeout=45)
        assert (result.returncode==0)==success,(Path(executable).name,args,result.returncode)
        if Path(executable).name.startswith('unins') and success:
            log_name=next(str(a).split('=',1)[1] for a in args if str(a).upper().startswith('/LOG='))
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                log=Path(log_name)
                if log.exists() and 'Log closed.' in log.read_text(encoding='utf-8-sig',errors='replace'):break
                time.sleep(.05)
            else:raise AssertionError('Second-phase uninstall did not finish')
        results.append({'program':Path(executable).name,'args':list(map(str,args)),'exit_code':result.returncode})
    def get_value(path,name,root=winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root,path) as h:return winreg.QueryValueEx(h,name)[0]
        except FileNotFoundError:return None
    def start_value(value):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,RUN_KEY) as h:winreg.SetValueEx(h,startup,0,winreg.REG_SZ,value)
    flags=ctypes.windll.shell32.IsUserAnAdmin();assert not flags,'Run verification without elevation'
    foreign=sandbox/'unowned';foreign.mkdir();sentinel=foreign/'keep.txt';sentinel.write_text('user file')
    run(current,'/DIR='+str(foreign),success=False);assert sentinel.read_text()=='user file'
    assert get_value(key,'InstallLocation') is None
    run(baseline,'/LOG='+str(sandbox/'install.log'))
    assert get_value(key,'DisplayVersion')==old_version
    assert get_value(key,'DisplayVersion',winreg.HKEY_LOCAL_MACHINE) is None
    assert get_value(RUN_KEY,startup) is None
    assert (app/'Orbita.exe').is_file() and (app/'unins000.exe').is_file()
    assert (app/'orbita-installation.ini').is_file()
    buffer=ctypes.create_unicode_buffer(32768)
    assert ctypes.windll.shell32.SHGetFolderPathW(None,2,None,0,buffer)==0
    group=Path(buffer.value)/('Orbita Test '+unique)
    assert (group/'Орбита.lnk').is_file() and (group/'Удалить Орбиту.lnk').is_file()
    env=dict(os.environ,AUTOMATION_HOME=str(profile))
    payload=sandbox/'result.json';payload.write_text(json.dumps({'title':'Сохранённое напоминание','body':'Данные переживают обновление и удаление','dedupe':'setup-keep'}),encoding='utf-8')
    subprocess.run([str(app/'Orbita.exe'),'--publish-file',str(payload)],env=env,check=True,timeout=20)
    baseline_hash=digest(app/'Orbita.exe')
    proc=subprocess.Popen([str(app/'Orbita.exe'),'--background','--smoke-test'],env=env)
    kernel=ctypes.windll.kernel32;kernel.OpenMutexW.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.c_wchar_p];kernel.OpenMutexW.restype=ctypes.c_void_p
    ready=False
    for _ in range(150):
        handle=kernel.OpenMutexW(0x100000,False,instance_name(profile))
        if handle:
            kernel.CloseHandle(ctypes.c_void_p(handle));ready=True;break
        if proc.poll() is not None:break
        time.sleep(.05)
    assert ready,'Baseline application did not start'
    run(current,success=False)
    assert digest(app/'Orbita.exe')==baseline_hash
    assert proc.wait(timeout=20)==0
    before=digest(profile/'inbox.sqlite')
    own_command='"'+str(app/'Orbita.exe')+'" --background';start_value(own_command)
    (app/'_internal/stale-fixture.dll').write_bytes(b'obsolete dependency')
    extra=app/'user-extra.txt';extra.write_text('keep user additions')
    run(current,'/LOG='+str(sandbox/'upgrade.log'))
    assert get_value(key,'DisplayVersion')==VERSION
    assert digest(profile/'inbox.sqlite')==before
    assert get_value(RUN_KEY,startup)==own_command
    assert not (app/'_internal/stale-fixture.dll').exists()
    assert extra.read_text()=='keep user additions'
    assert digest(app/'Orbita.exe')==digest(ROOT/'dist/Orbita/Orbita.exe')
    subprocess.run([str(app/'Orbita.exe'),'--smoke-test'],env=env,check=True,timeout=20)
    with closing(sqlite3.connect(profile/'inbox.sqlite')) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1
    run(app/'unins000.exe','/LOG='+str(sandbox/'uninstall-keep.log'))
    assert (profile/'inbox.sqlite').is_file() and not (app/'Orbita.exe').exists()
    assert get_value(key,'DisplayVersion') is None,'Uninstall registry record remains'
    assert get_value(RUN_KEY,startup) is None,'Owned autostart value remains'
    assert not (group/'Орбита.lnk').exists(),'Start Menu shortcut remains'
    assert extra.is_file(),'Uninstaller removed an unowned user file'
    extra.unlink()
    if app.exists():app.rmdir()  # nonrecursive; any unexpected remaining file fails verification
    run(current)
    outside=sandbox/'outside-profile';outside.mkdir();outside_file=outside/'keep.txt';outside_file.write_text('do not follow junction')
    link=profile/'linked-folder'
    link_env=dict(os.environ,ORBITA_TEST_LINK=str(link),ORBITA_TEST_TARGET=str(outside))
    subprocess.run(['powershell.exe','-NoProfile','-Command','New-Item -ItemType Junction -Path $env:ORBITA_TEST_LINK -Target $env:ORBITA_TEST_TARGET | Out-Null'],env=link_env,check=True,capture_output=True,timeout=15)
    start_value('"'+str(sandbox/'another-portable/Orbita.exe')+'" --background')
    run(app/'unins000.exe','/PURGETESTDATA=yes','/LOG='+str(sandbox/'uninstall-purge.log'))
    assert not profile.exists(),'Explicit test-profile purge did not complete'
    assert outside_file.read_text()=='do not follow junction','Deletion traversed a junction'
    assert get_value(RUN_KEY,startup) is not None,'Uninstaller removed another installation autostart'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_SET_VALUE) as h:winreg.DeleteValue(h,startup)
    assert get_value(key,'DisplayVersion') is None and not (app/'Orbita.exe').exists()
    logs=(sandbox/'install.log').read_text(encoding='utf-8-sig')
    assert 'Administrative install mode: No' in logs
    report={'version':VERSION,'sandbox':str(sandbox),'non_elevated_account':True,'registry_hkcu_only':True,'unicode_paths':True,'start_menu_shortcuts':True,
        'fresh_install':True,'foreign_directory_rejected':True,'running_baseline_upgrade_rejected':True,
        'upgrade_from':old_version,'database_unchanged_on_upgrade':True,'obsolete_runtime_removed':True,'unknown_user_file_preserved':True,
        'silent_uninstall_keeps_profile':True,'explicit_test_profile_purge':True,'junction_target_preserved':True,
        'owned_autostart_removed':True,'foreign_autostart_preserved':True,'runs':results,
        'limits':'Same non-elevated Windows 11 account; isolated compiled test AppId/profile. GUI data-removal confirmation and other Windows accounts are not exercised by this silent test.'}
    (ROOT/'data/installer-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
