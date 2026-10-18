"""Packaged fresh/upgrade/location CLI checks. Never requests device access."""
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
import location_service as location
import learning_service as learning
import project_service as projects
from automation_models import new_task


def main():
    root=Path(__file__).resolve().parent;bundle=root/'dist/Orbita';exe=bundle/'Orbita.exe'
    assert json.loads((bundle/'release-manifest.json').read_text(encoding='utf-8'))['version']==VERSION
    assert (bundle/'docs/PRIVACY.md').is_file()
    assert list((bundle/'_internal').rglob('*winrt*')), 'Windows positioning plugin missing'
    assert list((bundle/'_internal').rglob('Kathmandu')), 'IANA timezone data missing'
    base=Path(tempfile.mkdtemp(prefix='orbita-location-exe-'));processes=[]
    def run(home,*args):
        result=subprocess.run([str(exe),*map(str,args)],cwd=root,env=dict(os.environ,AUTOMATION_HOME=str(home)),timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode)
        processes.append({'args':list(map(str,args)),'exit_code':result.returncode})
    fresh=base/'fresh'
    with patch.object(store,'HOME',fresh):
        store.initialize();assert location.current() is None
        run(fresh,'--location-setup','--capture',root/'data/location-exe-first.png')
        assert location.current() is None and not store.get_setting('location_refresh_on_start',False)
        assert not store.events()
        city=dict(name='Казань',latitude=55.79,longitude=49.12,timezone='Europe/Moscow',source='manual')
        location.save(city,[7,12,20]);run(fresh,'--capture',root/'data/location-exe-city.png')
        assert location.current()['timezone']=='Europe/Moscow';assert store.get_setting('weather_hours')==[7,12,20]
        assert all(not t['enabled'] for t in store.tasks())
    upgrade=base/'v5'
    with patch.object(store,'HOME',upgrade):
        store.initialize();learning.save_progress('joins',answer='SELECT document_id FROM training_documents;',notes='Keep this draft')
        key=projects.create('Сохранить проект');projects.save(key,notes='Не терять заметки')
        task=new_task('Legacy future reminder','reminder',{'type':'once','at':(datetime.now(store.LOCAL)+timedelta(days=2)).isoformat(),'timezone':'Asia/Yekaterinburg'},enabled=True)
        store.save_task(task);store.set_setting('dnd',True);store.publish('Legacy result','Keep body','Проекты','legacy-location')
        before_events=store.events();before_progress=learning.progress('joins')
        with store.connect() as db:
            for row in db.execute('SELECT id,schedule FROM tasks').fetchall():
                spec=json.loads(row['schedule']);spec.pop('timezone',None);db.execute('UPDATE tasks SET schedule=? WHERE id=?',(json.dumps(spec),row['id']))
            db.execute("DELETE FROM settings WHERE key LIKE 'location_%'");db.execute('PRAGMA user_version=5')
        run(upgrade,'--smoke-test')
        with sqlite3.connect(upgrade/'inbox.sqlite') as db:
            assert db.execute('PRAGMA user_version').fetchone()[0]==store.SCHEMA_VERSION
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert store.events()==before_events;assert learning.progress('joins')==before_progress
        assert projects.get(key)['notes']=='Не терять заметки'
        preserved=next(t for t in store.tasks() if t['id']==task['id'])
        assert preserved['enabled'] and preserved['schedule']['timezone']=='Asia/Yekaterinburg'
        assert preserved['schedule']['at']==task['schedule']['at']
        assert location.current()['source']=='legacy';assert not store.get_setting('location_refresh_on_start',False)
        backups=list((upgrade/'backups').glob('inbox-v5-*.sqlite'));assert len(backups)==1
        with sqlite3.connect(backups[0]) as db:assert db.execute('PRAGMA user_version').fetchone()[0]==5
        payload=base/'result.json';payload.write_text(json.dumps({'title':'CLI result','body':'Still works','dedupe':'location-cli'}),encoding='utf-8')
        run(upgrade,'--publish-file',payload);run(upgrade,'--publish-file',payload)
        assert len([e for e in store.events() if e['dedupe']=='location-cli'])==1
    report={'version':VERSION,'isolated_data':str(base),'fresh_no_location_without_consent':True,
            'city_hours_persisted':True,'v5_backup_and_preservation':True,'json_deduplicated':True,
            'native_plugin_and_tzdata_bundled':True,'native_fix_tested':False,'processes':processes}
    (root/'data/location-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
