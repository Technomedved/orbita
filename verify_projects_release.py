"""Check packaged project workflow offline in an isolated data directory."""
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import desktop_store as store
import project_service as projects


def main():
    root=Path(__file__).resolve().parent;exe=root/'dist'/'Orbita'/'Orbita.exe'
    snapshot=store.get_setting('weather_snapshot')
    if not snapshot:raise RuntimeError('A saved weather snapshot is needed to keep the packaging test offline')
    folder=Path(tempfile.mkdtemp(prefix='orbita-projects-exe-'));store.HOME=folder;store.initialize()
    store.set_setting('weather_snapshot',snapshot);store.set_setting('dnd',True)
    key=projects.create('Проверка сборки проекта','print');record=projects.get(key)
    projects.save(key,notes='Размер 42 мм; пробный образец')
    projects.edit_step(key,record['steps'][0]['id'],done=True)
    projects.add_link(key,'Материалы','https://example.com/model')
    env=dict(os.environ,AUTOMATION_HOME=str(folder));results=[]
    def run(*args):
        started=time.perf_counter()
        result=subprocess.run([str(exe),*map(str,args)],cwd=root,env=env,timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode)
        results.append({'args':list(map(str,args)),'exit_code':result.returncode,'seconds':round(time.perf_counter()-started,3)})
    screenshot=root/'data'/'project-exe-card.png'
    run('--open-project',key,'--capture',screenshot);assert screenshot.exists()
    record=projects.get(key)
    assert record['notes']=='Размер 42 мм; пробный образец' and record['steps'][0]['done']==1
    assert record['links'][0]['url']=='https://example.com/model'
    at=datetime.now(store.LOCAL)+timedelta(seconds=1);task_id=projects.save_reminder(key,at.isoformat(),True)
    screenshot=root/'data'/'projects-exe-overview.png'
    run('--projects','--capture',screenshot);assert screenshot.exists()
    events=[r for r in store.events() if r['task_id']==task_id]
    assert len(events)==1 and events[0]['target']=='project:'+key and events[0]['delivered']==0
    assert store.runs(task_id)[0]['status']=='success'
    run('--projects','--capture',root/'data'/'projects-exe-restart.png')
    assert len([r for r in store.events() if r['task_id']==task_id])==1
    projects.save(key,state='archived')
    run('--open-project',key,'--capture',root/'data'/'project-exe-archived.png')
    assert projects.get(key)['state']=='archived'
    assert not next(t for t in store.tasks() if t['id']==task_id)['enabled']
    assert store.events()[0]['action_state']=='cancelled'
    payload=folder/'publish.json';payload.write_text(json.dumps({'title':'Compatibility','body':'JSON publication','dedupe':'projects-release'}),encoding='utf-8')
    run('--publish-file',payload);run('--publish-file',payload)
    assert sum(r['dedupe']=='projects-release' for r in store.events())==1
    report={'isolated_data':str(folder),'project_data_preserved':True,'scheduled_notification_during_dnd':True,
            'project_target_preserved':True,'no_duplicate_after_restart':True,'archive_cancels_notification':True,
            'json_cli_compatible':True,'processes':results}
    (root/'data'/'projects-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
