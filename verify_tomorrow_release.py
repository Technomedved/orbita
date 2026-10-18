"""Packaged next-day preview, restart, later execution and JSON checks."""
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
from app_config import VERSION
import desktop_store as store
import location_service as location
import agenda_service as agenda
import project_service as projects
from automation_models import new_task,parse_time
from automation_engine import Engine
from test_tomorrow import CITY,sample_snapshot


def main():
    root=Path(__file__).resolve().parent;bundle=root/'dist/Orbita';exe=bundle/'Orbita.exe'
    manifest=json.loads((bundle/'release-manifest.json').read_text(encoding='utf-8'));assert manifest['version']==VERSION
    assert (bundle/'docs/USER_GUIDE.md').is_file()
    scratch=Path(tempfile.mkdtemp(prefix='orbita-tomorrow-exe-'));runs=[]
    def run(*args):
        result=subprocess.run([str(exe),*map(str,args)],cwd=root,env=dict(os.environ,AUTOMATION_HOME=str(scratch)),timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode);runs.append({'args':list(map(str,args)),'exit_code':result.returncode})
    with patch.object(store,'HOME',scratch):
        store.initialize();location.save(CITY);store.set_setting('dnd',True)
        now=datetime.now(store.local_zone());tomorrow=now+timedelta(days=1)
        today_data=sample_snapshot(now.date(),11,CITY,now);tomorrow_data=sample_snapshot(tomorrow.date(),22,CITY,now)
        store.set_setting('weather_snapshot',today_data);store.set_setting('weather_forecasts',{today_data['date']:today_data,tomorrow_data['date']:tomorrow_data})
        at=tomorrow.replace(hour=9,minute=0,second=0,microsecond=0)
        task=new_task('Завтрашняя проверка размеров','reminder',{'type':'once','at':at.isoformat(),'timezone':CITY['timezone']},
                      {'body':'Сверить модель с чертежом'},enabled=True);store.save_task(task)
        key=projects.create('Подготовить корпус','print');projects.save(key,notes='Сохранить исходные размеры')
        projects.save_reminder(key,tomorrow.replace(hour=14,minute=0,second=0,microsecond=0).isoformat(),True,CITY['timezone'])
        assert agenda.snapshot(now)['counts']=={'events':2,'reminders':2,'projects':1}
        before_task=next(t for t in store.tasks() if t['id']==task['id'])
        run('--tomorrow','--capture',root/'data/tomorrow-exe-overview.png')
        assert store.events()==[] and store.runs()==[]
        run('--tomorrow','--smoke-test')
        assert store.events()==[] and store.runs()==[]
        assert next(t for t in store.tasks() if t['id']==task['id'])==before_task
        assert projects.get(key)['notes']=='Сохранить исходные размеры'
        assert store.get_setting('weather_forecasts')[tomorrow_data['date']]['hourly']['temperature_2m'][9]==22
        future=Engine(clock=lambda:at,inline=True);future.tick();future.tick()
        Engine(clock=lambda:at,inline=True).tick()
        assert len([e for e in store.events() if e['task_id']==task['id']])==1
        assert len(store.runs(task['id']))==1
        assert not next(t for t in store.tasks() if t['id']==task['id'])['enabled']
        assert agenda.snapshot(now)['counts']['events']==1
        run('--tomorrow','--capture',root/'data/tomorrow-exe-after-completion.png')
        assert len(store.events())==1
        payload=scratch/'result.json';payload.write_text(json.dumps({'title':'JSON result','body':'Publication still works','dedupe':'tomorrow-cli'}),encoding='utf-8')
        run('--publish-file',payload);run('--publish-file',payload)
        assert len([e for e in store.events() if e['dedupe']=='tomorrow-cli'])==1
        with store.connect() as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    report={'version':VERSION,'isolated_data':str(scratch),'preview_and_restart_without_execution':True,
            'two_dates_preserved':True,'later_execution_exactly_once':True,'project_and_task_preserved':True,
            'json_deduplicated':True,'processes':runs}
    (root/'data/tomorrow-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
