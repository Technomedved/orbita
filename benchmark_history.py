"""Repeatable offline stress benchmark, isolated from user data and the network."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
scratch = tempfile.TemporaryDirectory()
os.environ['AUTOMATION_HOME'] = scratch.name
import desktop_store as store
from automation_models import new_task
from automation_engine import Engine
import today_service
import agenda_service

store.initialize()
now = datetime(2026, 10, 18, 10, 0, tzinfo=store.LOCAL)
tasks = [new_task(f'Task {i}', 'reminder',
         {'type':'daily','time':'08:00','timezone':'Asia/Yekaterinburg'},
         enabled=True, now=now-timedelta(days=400)) for i in range(200)]
for task in tasks: store.save_task(task)
with store.connect() as db:
    db.executemany('INSERT INTO runs(task_id,slot,scheduled_at,status) VALUES(?,?,?,?)',
        ((task['id'], stamp.isoformat(), stamp.isoformat(), 'success')
         for task in tasks for day in range(300)
         for stamp in [now.replace(hour=8)-timedelta(days=day)]))
    db.executemany('INSERT INTO events(title,body,category,created,action_state) VALUES(?,?,?,?,?)',
        (('Reminder','Saved result','Напоминания',now.isoformat(), 'pending' if i<200 else 'done')
         for i in range(20000)))
    db.execute('UPDATE events SET root_id=id')
engine = Engine(clock=lambda:now, inline=True)
result = {'fixture':{'tasks':200,'runs':60000,'events':20000}, 'measurements':{}}
original = store.connect
connections = 0
@contextmanager
def counted():
    global connections
    connections += 1
    with original() as db: yield db
with patch.object(store,'connect',counted):
    for name, action in [('today',lambda:today_service.snapshot(now)),
                         ('tomorrow',lambda:agenda_service.snapshot(now)),
                         ('scheduler_noop',lambda:engine.tick(now))]:
        samples=[]; connections=0
        for _ in range(5):
            start=time.perf_counter(); action(); samples.append((time.perf_counter()-start)*1000)
        result['measurements'][name]={'median_ms':round(statistics.median(samples),2),
            'max_ms':round(max(samples),2),'connections_per_call':connections/5}
Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
