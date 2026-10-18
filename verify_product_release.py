"""Exercise the packaged 0.5 product with isolated data, offline and without mail."""
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from app_config import VERSION
import desktop_store as store
import project_service as projects
from automation_models import new_task
from automation_engine import Engine
import location_service as location


def main():
    root=Path(__file__).resolve().parent;folder=root/'dist'/'Orbita';exe=folder/'Orbita.exe'
    manifest=json.loads((folder/'release-manifest.json').read_text(encoding='utf-8'))
    assert manifest['version']==VERSION
    required=['START_HERE.md','USER_GUIDE.md','PRIVACY.md','PORTABLE.md','MANUAL.md']
    assert all((folder/'docs'/name).is_file() for name in required)
    scratch=Path(tempfile.mkdtemp(prefix='orbita-product-exe-'));store.HOME=scratch;store.initialize()
    location.save(location.LEGACY_LOCATION)
    now=datetime.now(store.LOCAL);day=now.date().isoformat()
    hourly={'time':[f'{day}T{h:02d}:00' for h in range(24)]}
    for field,value in {'temperature_2m':2,'apparent_temperature':0,'relative_humidity_2m':80,
                        'precipitation_probability':10,'precipitation':0,'snowfall':0,'wind_speed_10m':2,
                        'wind_gusts_10m':4,'weather_code':3,'is_day':1}.items():hourly[field]=[value]*24
    store.set_setting('weather_snapshot',{'date':day,'fetched':now.isoformat(),'hourly':hourly,'location':location.LEGACY_LOCATION,'location_key':location.location_key(location.LEGACY_LOCATION)})
    store.set_setting('dnd',True)
    demo_id=store.publish('Historical demo','Synthetic old entry','Демо','product-old-demo')
    key=projects.create('Контрольная печать корпуса','print')
    projects.save(key,notes='Размер 42 мм; проверить посадку')
    task=new_task('Сверить размеры перед печатью','reminder',{'type':'once','at':(now+timedelta(hours=1)).isoformat()})
    store.save_task(task);Engine(inline=True).run_now(task['id'])
    env=dict(os.environ,AUTOMATION_HOME=str(scratch));runs=[]
    def run(*args):
        started=time.perf_counter()
        result=subprocess.run([str(exe),*map(str,args)],cwd=root,env=env,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode)
        runs.append({'args':list(map(str,args)),'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3)})
    run('--capture',root/'data'/'product-exe-today.png')
    before=len(store.events());run('--smoke-test');assert len(store.events())==before
    assert len(store.user_events())==1 and len(store.events())==2
    assert next(e for e in store.events() if e['id']==demo_id)['delivered']==0
    run('--open-project',key,'--capture',root/'data'/'product-exe-project.png')
    assert projects.get(key)['notes']=='Размер 42 мм; проверить посадку'
    payload=scratch/'result.json';payload.write_text(json.dumps({'title':'Published result','body':'JSON compatibility','dedupe':'product-cli'}),encoding='utf-8')
    run('--publish-file',payload);run('--publish-file',payload)
    assert sum(e['dedupe']=='product-cli' for e in store.events())==1
    report={'version':VERSION,'platform':'win32','isolated_data':str(scratch),'packaged_documentation':required,
            'smoke_created_no_events':True,'historical_demo_retained_and_not_delivered':True,
            'project_data_preserved':True,'json_cli_deduplicated':True,'processes':runs}
    (root/'data'/'product-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
