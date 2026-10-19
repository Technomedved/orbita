"""Small read models and allowlisted diagnostics, never raw logs or user content."""
from contextlib import closing
from datetime import datetime,timezone
import json
import platform
import sqlite3
import desktop_store as store
from app_config import VERSION
from profile_access import access

ERRORS={'OSError','PermissionError','FileNotFoundError','TimeoutError','OperationalError','DatabaseError','ValueError','BadZipFile','RuntimeError'}


def safe_error(value):
    return value if isinstance(value,str) and value in ERRORS else 'ExecutionError' if value else None


def safe_stamp(value):
    try:return datetime.fromisoformat(value).isoformat() if value else None
    except (TypeError,ValueError):return None


def snapshot(scheduler=None):
    with store.connect() as db:
        schema=db.execute('PRAGMA user_version').fetchone()[0]
        counts={name:db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in
                ('tasks','runs','events','projects','learning_progress')}
        enabled=db.execute('SELECT COUNT(*) FROM tasks WHERE enabled=1').fetchone()[0]
        waiting=db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','retry')").fetchone()[0]
        values={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM settings')}
        last=db.execute("SELECT finished FROM runs WHERE task_id='weather' AND status='success' ORDER BY id DESC LIMIT 1").fetchone()
        failures=db.execute("""SELECT COUNT(*) FROM tasks t JOIN runs r ON r.id=
            (SELECT id FROM runs WHERE task_id=t.id ORDER BY id DESC LIMIT 1) WHERE r.status='failed'""").fetchone()[0]
        automatic=db.execute("SELECT enabled,config FROM tasks WHERE id='profile-backup'").fetchone()
    backup=values.get('backup_state',{})
    backup_state=backup.get('state','not_started')
    if backup_state not in ('not_started','running','success','error','interrupted'):backup_state='unknown'
    if backup_state=='running' and not (scheduler or {}).get('backup_running'):
        backup_state='interrupted'
    return {'version':VERSION,'schema':schema,'scheduler':scheduler or {'running':False},'paused':bool(values.get('paused')),
            'enabled_tasks':enabled,'waiting_runs':waiting,'counts':counts,'failed_latest_tasks':failures,
            'weather':{'configured':bool(values.get('location_profile')),'last_success':safe_stamp(last[0]) if last else None},
            'backup':{'state':backup_state,'last_success':safe_stamp(backup.get('last_success')),'error':safe_error(backup.get('error')),
                      'automatic_configured':bool(automatic and json.loads(automatic[1]).get('folder')),'automatic_enabled':bool(automatic and automatic[0])}}


def integrity():
    with access(store.HOME),closing(sqlite3.connect(store.HOME/'inbox.sqlite',timeout=10)) as db:
        import time
        deadline=time.monotonic()+30
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        ok=db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        foreign=db.execute('PRAGMA foreign_key_check').fetchone() is None
        return {'integrity':'ok' if ok else 'failed','references':'ok' if foreign else 'failed'}


def diagnostic(model,checks=None):
    # Construct afresh from primitives; never serialize an engine exception/log,
    # environment, username, host name, task title, settings, IDs or paths.
    return {'format':1,'created':datetime.now(timezone.utc).isoformat(),'application_version':VERSION,
            'os':{'system':platform.system(),'release':platform.release()},'schema':model['schema'],
            'counts':dict(model['counts']),'enabled_tasks':model['enabled_tasks'],'waiting_runs':model['waiting_runs'],
            'paused':model['paused'],'scheduler_running':bool(model['scheduler'].get('running')),
            'scheduler_error':safe_error(model['scheduler'].get('error')),
            'failed_latest_tasks':model['failed_latest_tasks'],
            'weather':{'configured':bool(model['weather']['configured']),'last_success':safe_stamp(model['weather'].get('last_success'))},
            'backup':{'state':model['backup']['state'] if model['backup']['state'] in ('not_started','running','success','error','interrupted') else 'unknown',
                      'last_success':safe_stamp(model['backup'].get('last_success')),'error':safe_error(model['backup'].get('error'))},
            'checks':{k:v for k,v in (checks or {}).items() if k in ('integrity','references') and v in ('ok','failed')}}
