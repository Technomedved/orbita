"""Portable durable scheduler. Qt and Windows APIs are deliberately absent."""
from datetime import datetime, timedelta
import json
import logging
import threading
import time
from uuid import uuid4

import desktop_store as store
from automation_models import latest_due, parse_time
from automation_handlers import HANDLERS


TERMINAL = ('success','failed','skipped','cancelled')


class Engine:
    def __init__(self, handlers=None, clock=None, inline=False):
        store.initialize()
        self.handlers = handlers or HANDLERS
        raw_clock=clock or (lambda:datetime.now(store.LOCAL))
        self.clock=lambda:raw_clock().astimezone(store.LOCAL)
        self.inline = inline
        self.owner = uuid4().hex
        self.stop_event = threading.Event()
        self.workers = {}
        self.lock = threading.RLock()
        self.loop_thread = None
        self.last_error = None

    def start(self):
        if self.loop_thread and self.loop_thread.is_alive(): return
        self.stop_event.clear()
        self.loop_thread = threading.Thread(target=self._loop,name='orbita-scheduler',daemon=True)
        self.loop_thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.tick(); self.last_error = None
            except Exception as exc:
                self.last_error = type(exc).__name__
                logging.exception('Scheduler tick failed')
            self.stop_event.wait(5)

    def stop(self, wait=True):
        self.stop_event.set()
        if wait:
            if self.loop_thread: self.loop_thread.join(timeout=4)
            deadline = time.monotonic()+15
            for worker in list(self.workers.values()):
                worker.join(timeout=max(0,deadline-time.monotonic()))

    def _enqueue(self, task, scheduled, slot, skipped=False):
        rows=self._enqueue_batch([(task,scheduled,slot,skipped)])
        return rows[0] if rows else None

    def _enqueue_batch(self, candidates):
        if not candidates:return []
        with store.connect() as db:
            # Most ticks contain only already processed slots. Avoid a write lock
            # in this common case; INSERT OR IGNORE still arbitrates concurrent engines.
            missing=[row for row in candidates if not db.execute(
                'SELECT 1 FROM runs WHERE task_id=? AND slot=?',(row[0]['id'],row[2])).fetchone()]
            if not missing:return []
            db.execute('BEGIN IMMEDIATE')
            inserted=[]
            for task,scheduled,slot,skipped in missing:
                cursor = db.execute('''INSERT OR IGNORE INTO runs(task_id,slot,scheduled_at,status,finished,summary)
                    VALUES(?,?,?,?,?,?)''',(task['id'],slot,scheduled.isoformat(),
                    'skipped' if skipped else 'queued',self.clock().isoformat() if skipped else None,
                    'Пропущено: срок актуальности истёк' if skipped else None))
                if cursor.rowcount:inserted.append(cursor.lastrowid)
            return inserted

    def run_now(self, task_id):
        with self.lock:
            task = next(t for t in store.tasks() if t['id']==task_id)
            now = self.clock()
            with store.connect() as db:
                active = db.execute("SELECT id FROM runs WHERE task_id=? AND status='running'",(task_id,)).fetchone()
                if active: return active[0]
            run = self._enqueue(task,now,'manual-'+uuid4().hex)
            self._dispatch(now,manual_id=run)
            return run

    def tick(self, now=None):
        now = (now or self.clock()).astimezone(store.LOCAL)
        with self.lock:
            self.workers = {k:v for k,v in self.workers.items() if v.is_alive()}
            # Renew live workers, then recover abandoned leases from a previous process.
            with store.connect() as db:
                if self.workers:
                    db.execute("UPDATE runs SET lease_until=? WHERE status='running' AND owner=?",
                               ((now+timedelta(seconds=60)).isoformat(),self.owner))
                abandoned = list(db.execute("SELECT * FROM runs WHERE status='running' AND lease_until<=?",(now.isoformat(),)))
                for run in abandoned:
                    task = db.execute('SELECT max_attempts FROM tasks WHERE id=?',(run['task_id'],)).fetchone()
                    exhausted = not task or run['recoveries'] >= 3
                    db.execute("UPDATE runs SET status=?,retry_at=?,finished=?,error=?,owner=NULL,recoveries=recoveries+1 WHERE id=?",
                        ('failed' if exhausted else 'retry',now.isoformat(),now.isoformat() if exhausted else None,
                         'Предыдущий процесс завершился во время выполнения',run['id']))
                    if exhausted:
                        db.execute('''INSERT OR IGNORE INTO events(title,body,category,created,dedupe,task_id,run_id)
                            VALUES(?,?,?,?,?,?,?)''',('Не удалось восстановить задачу',
                            'Несколько запусков прерваны аварийным завершением. Проверь журнал и выполни задачу вручную.',
                            'Система',now.isoformat(),f"error-{run['task_id']}-{now.date()}",run['task_id'],run['id']))
            if store.get_setting('paused',False): return
            store.deliver_snoozes(now)
            tasks=store.tasks(); candidates=[]
            for task in tasks:
                if not task['enabled']: continue
                due = latest_due(task,now)
                if due:
                    skipped = task['policy']=='skip' and (now-due).total_seconds()>=task['grace_seconds']
                    candidates.append((task,due,due.isoformat(),skipped))
            self._enqueue_batch(candidates)
            self._dispatch(now,task_map={t['id']:t for t in tasks})

    def _dispatch(self, now, manual_id=None, task_map=None):
        if task_map is None:task_map = {t['id']:t for t in store.tasks()}
        with store.connect() as db:
            sql="""SELECT r.* FROM runs r JOIN tasks t ON t.id=r.task_id
                WHERE r.status IN ('queued','retry') AND (r.retry_at IS NULL OR r.retry_at<=?)
                AND (t.enabled=1 OR r.slot LIKE 'manual-%')"""
            params=[now.isoformat()]
            if manual_id is not None:sql+=' AND r.id=?';params.append(manual_id)
            rows = [dict(r) for r in db.execute(sql+' ORDER BY r.id',params)]
        for run in rows:
            task = task_map.get(run['task_id'])
            if not task: continue
            manual = run['slot'].startswith('manual-')
            if manual_id is not None and run['id']!=manual_id: continue
            if not task['enabled'] and not manual: continue
            if run['retry_at'] and parse_time(run['retry_at'])>now: continue
            if len(self.workers)>=2 and not self.inline: break
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                # The queue snapshot can become stale while another engine runs
                # or reschedules this attempt. Recheck eligibility under the lock.
                current=db.execute("""SELECT r.*,t.enabled FROM runs r JOIN tasks t ON t.id=r.task_id
                    WHERE r.id=? AND r.status IN ('queued','retry')
                    AND (r.retry_at IS NULL OR r.retry_at<=?)""",(run['id'],now.isoformat())).fetchone()
                if not current or (not current['enabled'] and not manual):continue
                run=dict(current)
                # Avoid overlapping manual and scheduled runs of the same task.
                if db.execute("SELECT 1 FROM runs WHERE task_id=? AND status='running'",(task['id'],)).fetchone():continue
                if (not manual and task['policy']=='skip' and
                    (now-parse_time(run['scheduled_at'])).total_seconds()>=task['grace_seconds']):
                    db.execute("UPDATE runs SET status='skipped',finished=?,summary='Срок актуальности истёк' WHERE id=?",
                               (now.isoformat(),run['id'])); continue
                changed = db.execute("""UPDATE runs SET status='running',attempts=attempts+1,started=?,
                    lease_until=?,owner=?,error=NULL WHERE id=? AND status IN ('queued','retry')""",
                    (now.isoformat(),(now+timedelta(seconds=60)).isoformat(),self.owner,run['id'])).rowcount
            if not changed:continue
            if self.inline:
                self._execute(task,run['id'])
            else:
                worker = threading.Thread(target=self._execute,args=(task,run['id']),
                                          name='orbita-task-'+task['id'],daemon=True)
                self.workers[run['id']] = worker; worker.start()

    def _execute(self, task, run_id):
        try:
            result = self.handlers[task['kind']](task,self.clock())
            self._success(task,run_id,result)
        except Exception as exc:
            logging.warning('Task %s failed: %s',task['kind'],type(exc).__name__)
            self._failure(task,run_id,type(exc).__name__)

    def _success(self,task,run_id,result):
        now=self.clock()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM runs WHERE id=? AND status='running' AND owner=?",(run_id,self.owner)).fetchone()
            if not row:return
            snapshot=(result.settings or {}).get('weather_snapshot')
            if snapshot:
                from location_service import location_key
                selected=db.execute("SELECT value FROM settings WHERE key='location_profile'").fetchone()
                if not selected or snapshot.get('location_key')!=location_key(json.loads(selected[0])):
                    db.execute("UPDATE runs SET status='cancelled',finished=?,summary='Местоположение изменилось во время загрузки',lease_until=NULL WHERE id=?",(now.isoformat(),run_id))
                    return
            if task['config'].get('project_id'):
                from project_service import reminder_is_current
                if not reminder_is_current(db,task):
                    db.execute("UPDATE runs SET status='cancelled',finished=?,summary='Проект больше не в работе',lease_until=NULL WHERE id=?",(now.isoformat(),run_id))
                    return
            key=result.notification_key or f'run-{run_id}'
            event=db.execute('''INSERT OR IGNORE INTO events(title,body,category,created,dedupe,task_id,run_id,action_state,target)
                VALUES(?,?,?,?,?,?,?,?,?)''',(result.title,result.body,result.category,now.isoformat(),key,
                task['id'],run_id,'pending' if result.reminder else '',result.target))
            if not event.rowcount and result.coalesce:
                db.execute('''UPDATE events SET title=?,body=?,created=?,seen=0,delivered=0,run_id=?,task_id=?,target=?
                    WHERE dedupe=?''',(result.title,result.body,now.isoformat(),run_id,task['id'],result.target,key))
            if result.reminder and event.rowcount:
                db.execute('UPDATE events SET root_id=id WHERE id=?',(event.lastrowid,))
            for key,value in (result.settings or {}).items():
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
            db.execute("UPDATE runs SET status='success',finished=?,summary=?,lease_until=NULL WHERE id=?",
                       (now.isoformat(),result.summary,run_id))
            if task['schedule']['type']=='once' and not row['slot'].startswith('manual-'):
                db.execute('UPDATE tasks SET enabled=0 WHERE id=?',(task['id'],))

    def _failure(self,task,run_id,error):
        now=self.clock()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM runs WHERE id=? AND status='running' AND owner=?",(run_id,self.owner)).fetchone()
            if not row:return
            exhausted=row['attempts']>=task['max_attempts']
            db.execute('''UPDATE runs SET status=?,retry_at=?,finished=?,error=?,summary=?,lease_until=NULL WHERE id=?''',
                ('failed' if exhausted else 'retry',(now+timedelta(seconds=task['retry_seconds'])).isoformat(),
                 now.isoformat() if exhausted else None,error,
                 'Попытки исчерпаны' if exhausted else 'Ожидает повторной попытки',run_id))
            if exhausted:
                # One error notification per task/day, even after repeated manual requests.
                db.execute('''INSERT OR IGNORE INTO events(title,body,category,created,dedupe,task_id,run_id)
                    VALUES(?,?,?,?,?,?,?)''',(task['name']+' · ошибка',
                    f'Не удалось выполнить задачу после {row["attempts"]} попыток. Причина: {error}. '
                    'Подробности доступны в журнале запусков. Предыдущие данные не обновлены.',
                    'Система',now.isoformat(),f'error-{task["id"]}-{now.date()}',task['id'],run_id))


def quiet_now(settings, now):
    if settings.get('dnd',False):return True
    if not settings.get('quiet_enabled',False):return False
    start,end=settings.get('quiet_start','22:00'),settings.get('quiet_end','08:00')
    from zoneinfo import ZoneInfo
    clock=now.astimezone(ZoneInfo(settings['timezone']) if settings.get('timezone') else store.LOCAL).strftime('%H:%M')
    return start<=clock<end if start<end else (clock>=start or clock<end) if start!=end else False
