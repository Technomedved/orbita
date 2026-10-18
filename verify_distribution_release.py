"""Run the relocated Windows package with fresh profiles and no developer runtime PATH."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from app_config import VERSION
from release_layout import verify_public_layout


def main():
    root=Path(__file__).resolve().parent;source=root/'dist/Orbita'
    assert json.loads((source/'release-manifest.json').read_text(encoding='utf-8'))['version']==VERSION
    verify_public_layout(source)
    scratch=Path(tempfile.mkdtemp(prefix='orbita-distribution-'))
    bundle=scratch/'Программы с пробелами'/'Орбита';shutil.copytree(source,bundle)
    def files():return {str(p.relative_to(bundle)):(p.stat().st_size,p.stat().st_mtime_ns) for p in bundle.rglob('*') if p.is_file()}
    original_files=files()
    working=scratch/'Другой рабочий каталог';working.mkdir()
    env=dict(os.environ)
    for key in list(env):
        if key.startswith(('PYTHON','QT_','ORBITA_')) or key=='AUTOMATION_HOME':env.pop(key)
    env['PATH']=str(Path(os.environ['WINDIR'])/'System32')
    processes=[]
    def profile(name):
        home=scratch/name;local=home/'AppData/Local';local.mkdir(parents=True)
        roaming=home/'AppData/Roaming';roaming.mkdir()
        return dict(env,USERPROFILE=str(home),LOCALAPPDATA=str(local),APPDATA=str(roaming)),local/'Orbita/inbox.sqlite'
    def run(environment,*args):
        result=subprocess.run([str(bundle/'Orbita.exe'),*map(str,args)],cwd=working,env=environment,
            timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode)
        processes.append({'args':list(map(str,args)),'exit_code':0})
    first,first_db=profile('Пользователь А');second,second_db=profile('Пользователь Б')
    capture=root/'data/distribution-exe-welcome.png';run(first,'--welcome','--capture',capture)
    with closing(sqlite3.connect(first_db)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        for table in ('events','runs','projects','learning_progress','learning_profiles'):
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0,table
        tasks=list(db.execute('SELECT id,name,enabled,schedule FROM tasks'));assert len(tasks)==3
        weather=next(t for t in tasks if t[0]=='weather')
        assert weather[1]=='Отчёт о погоде' and json.loads(weather[3])['days']==list(range(7))
        assert not any(t[2] for t in tasks)
        settings={k:json.loads(v) for k,v in db.execute('SELECT * FROM settings')}
        assert 'location_profile' not in settings and 'weather_snapshot' not in settings
        assert settings['topmost'] is False and settings['user_timezone']
    payload=working/'Результат.json';payload.write_text(json.dumps({'title':'Мой результат','body':'Только профиль А','dedupe':'isolated'}),encoding='utf-8')
    run(first,'--publish-file',payload);run(first,'--publish-file',payload);run(first,'--smoke-test')
    run(second,'--smoke-test')
    with closing(sqlite3.connect(first_db)) as db:assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==1
    with closing(sqlite3.connect(second_db)) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==0
    verify_public_layout(bundle)
    assert files()==original_files,'Application wrote into its program directory'
    report={'version':VERSION,'relocated_bundle':str(bundle),'working_directory':str(working),
            'fresh_profile_welcome':True,'stock_templates_disabled':True,'no_developer_data':True,
            'no_external_python_path':True,'separate_localappdata_profiles':True,'json_deduplicated':True,
            'no_program_directory_data_written':True,'capture':str(capture),'processes':processes,
            'limits':'Same Windows 11 host; environment-isolated profiles, not separate Windows accounts or a clean VM.'}
    (root/'data/distribution-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
