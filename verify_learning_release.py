"""Exercise the built exe using a separate database; never enables real user tasks.

Run after build-desktop.ps1, with the primary Orbita instance fully exited.
No Db2 connection or SQL execution is performed.
"""
from datetime import datetime,timedelta
import json
from pathlib import Path
import os
import subprocess
import tempfile
import time

import desktop_store as store
import learning_service as learning


def main():
    root=Path(__file__).resolve().parent
    exe=root/'dist'/'Orbita'/'Orbita.exe'
    snapshot=store.get_setting('weather_snapshot')
    if not snapshot:
        raise RuntimeError('Seed a saved weather snapshot to keep this packaging check offline')
    folder=Path(tempfile.mkdtemp(prefix='orbita-learning-exe-'))
    store.HOME=folder
    store.initialize()
    store.set_setting('weather_snapshot',snapshot)
    store.set_setting('dnd',True)  # Scheduler must still produce its learning result.
    task=next(t for t in store.tasks() if t['id']=='learning-db2')
    assert not task['enabled']
    learning.save_progress('joins',answer='SELECT d.DOC_ID FROM ORB_DOCS d;',notes='Packaging persistence check')
    learning.reveal_hint('joins')
    env=dict(os.environ,AUTOMATION_HOME=str(folder))
    timings=[]

    def run(*args):
        started=time.perf_counter()
        process=subprocess.run([str(exe),*map(str,args)],cwd=root,env=env,timeout=40,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        assert process.returncode==0,(args,process.returncode)
        timings.append({'args':list(map(str,args)),'exit_code':process.returncode,
                        'seconds':round(time.perf_counter()-started,3)})

    payload=folder/'publication.json'
    payload.write_text(json.dumps({'title':'Packaging check','body':'Synthetic notification',
                                   'dedupe':'learning-release-cli'}),encoding='utf-8')
    run('--publish-file',payload);run('--publish-file',payload)
    assert len(store.events())==1
    capture=root/'data'/'learning-exe-lesson.png'
    run('--open-lesson','joins','--capture',capture)
    assert capture.exists()
    record=learning.progress('joins')
    assert record['answer']=='SELECT d.DOC_ID FROM ORB_DOCS d;'
    assert record['notes']=='Packaging persistence check'
    assert record['hints_revealed']==1 and record['state']=='in_progress'

    for iteration in range(2):
        task=next(t for t in store.tasks() if t['id']=='learning-db2')
        task.update(enabled=True,schedule={'type':'once','at':(datetime.now(store.LOCAL)+timedelta(seconds=1)).isoformat()})
        store.save_task(task)
        capture=root/'data'/f'learning-exe-overview-{iteration+1}.png'
        run('--learning','--capture',capture)
        assert capture.exists()
        rows=[e for e in store.events() if e['task_id']=='learning-db2']
        assert len(rows)==1 and rows[0]['target']=='lesson:db2:joins'
        assert rows[0]['delivered']==0  # DND defers display, not task execution.
        assert len(store.runs('learning-db2'))==iteration+1
        assert all(r['status']=='success' for r in store.runs('learning-db2'))
        assert learning.progress('joins')['state']=='in_progress'
        assert learning.progress('aggregation')['state']=='not_started'

    report={'executable':str(exe),'isolated_data':str(folder),
            'default_learning_disabled':True,'cli_publication_deduplicated':True,
            'answer_notes_hints_preserved_after_exe_restart':True,
            'scheduled_runs_during_dnd':2,'single_learning_card':True,
            'target':'lesson:db2:joins','db2_sql_executed':False,'processes':timings}
    (root/'data'/'learning-release-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
