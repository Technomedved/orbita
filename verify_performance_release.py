"""Exercise the frozen binary against a populated v6 database, never the user's DB."""
from contextlib import closing
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from unittest.mock import patch
from app_config import VERSION
import desktop_store as store
from automation_models import new_task
import project_service as projects


def main():
    root=Path(__file__).resolve().parent;bundle=root/'dist/Orbita';exe=bundle/'Orbita.exe'
    assert json.loads((bundle/'release-manifest.json').read_text(encoding='utf-8'))['version']==VERSION
    assert (bundle/'docs/PORTABLE.md').is_file()
    scratch=Path(tempfile.mkdtemp(prefix='orbita-performance-exe-'));processes=[]
    def run(*args):
        result=subprocess.run([str(exe),*map(str,args)],cwd=root,
            env=dict(os.environ,AUTOMATION_HOME=str(scratch)),timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode);processes.append({'args':list(map(str,args)),'exit_code':0})
    with patch.object(store,'HOME',scratch):
        store.initialize();store.set_setting('dnd',True);store.set_setting('animations',False)
        store.set_setting('location_setup_complete',True)
        with store.connect() as db:db.execute("DELETE FROM settings WHERE key='onboarding_pending'")
        for i in range(80):store.save_task(new_task(f'Задача {i}','reminder',{'type':'daily','time':'19:00'},enabled=False))
        key=projects.create('Сохранённый корпус','print');projects.save(key,notes='Данные до обновления')
        store.publish('Сохранённый результат','Текст до обновления','Проекты','preserved')
        before_tasks=store.tasks();before_events=store.events();before_project=projects.get(key)
        with store.connect() as db:
            for name in ('runs_task_latest','runs_day','events_root','events_action','snoozes_due','snoozes_event','snoozes_root'):
                db.execute('DROP INDEX '+name)
            db.execute('PRAGMA user_version=6')
        run('--smoke-test');run('--smoke-test')
        backups=list((scratch/'backups').glob('inbox-v6-*.sqlite'));assert len(backups)==1
        with closing(sqlite3.connect(backups[0])) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0]==6
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        with store.connect() as db:
            assert db.execute('PRAGMA user_version').fetchone()[0]==store.SCHEMA_VERSION
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert store.tasks()==before_tasks and store.events()==before_events and projects.get(key)==before_project
        assert store.get_setting('animations') is False
        report={'version':VERSION,'isolated_data':str(scratch),'v6_backup_verified':True,
                'migration_and_restart_preserve_data':True,'motion_setting_preserved':True,'processes':processes}
        (root/'data/performance-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
