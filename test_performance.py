"""Data preservation and bounded work, without machine-specific timing assertions."""
from contextlib import contextmanager,closing
from datetime import datetime,timedelta
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import desktop_store as store
from automation_engine import Engine
from automation_models import new_task,Result
import project_service as projects
import today_service


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.patch=patch.object(store,'HOME',self.home);self.patch.start();store.initialize()
        self.now=datetime(2026,10,18,10,tzinfo=store.LOCAL)

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def task(self,i):
        task=new_task(f'Task {i}','reminder',{'type':'daily','time':'08:00','timezone':'Asia/Yekaterinburg'},
                      enabled=True,now=self.now-timedelta(days=1))
        store.save_task(task);return task

    def test_v6_backup_and_index_migration_preserve_every_table(self):
        task=self.task(1);store.publish('Сохранить','История','Напоминания','same-key')
        store.set_setting('weather_day','2026-10-10')  # legacy setting must not be imported a second time
        store.set_setting('animations',False);projects.create('Мой проект','print')
        with store.connect() as db:
            db.execute("INSERT INTO runs(task_id,slot,scheduled_at,status) VALUES(?,?,?,'success')",(task['id'],'old',self.now.isoformat()))
            for name in ('runs_task_latest','runs_day','events_root','events_action','snoozes_due','snoozes_event','snoozes_root'):
                db.execute('DROP INDEX '+name)
            db.execute('PRAGMA user_version=6')
            tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            before={t:list(map(tuple,db.execute('SELECT * FROM '+t))) for t in tables}
        store._initialized.discard(str(self.home.resolve()));store.initialize()
        backups=list((self.home/'backups').glob('inbox-v6-*.sqlite'));self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],6)
            for t in tables:self.assertEqual(list(db.execute('SELECT * FROM '+t)),before[t])
        with store.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],store.SCHEMA_VERSION)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            for t in tables:self.assertEqual(list(map(tuple,db.execute('SELECT * FROM '+t))),before[t])
            self.assertIsNotNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='events_root'").fetchone())

    def test_idle_scheduler_connections_do_not_grow_per_task_or_write_revision(self):
        for i in range(75):
            task=self.task(i);due=self.now.replace(hour=8)
            with store.connect() as db:db.execute("INSERT INTO runs(task_id,slot,scheduled_at,status) VALUES(?,?,?,'success')",(task['id'],due.isoformat(),due.isoformat()))
        revision=store.revision();original=store.connect;calls=[]
        @contextmanager
        def counted():
            calls.append(1)
            with original() as db:yield db
        with patch.object(store,'connect',counted):Engine(clock=lambda:self.now,inline=True).tick()
        self.assertLessEqual(len(calls),7);self.assertEqual(store.revision(),revision)

    def test_concurrent_batch_and_restart_execute_each_slot_once(self):
        tasks=[self.task(i) for i in range(20)];calls=[];barrier=threading.Barrier(2);errors=[]
        def handler(task,now):calls.append(task['id']);return Result(task['name'],'Body','Напоминания')
        def work():
            try:
                engine=Engine({'reminder':handler},lambda:self.now,inline=True);barrier.wait();engine.tick()
            except Exception as exc:errors.append(exc)
        workers=[threading.Thread(target=work) for _ in range(2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(20)
        self.assertFalse(any(w.is_alive() for w in workers));self.assertEqual(errors,[])
        Engine({'reminder':handler},lambda:self.now,inline=True).tick()
        self.assertCountEqual(calls,[t['id'] for t in tasks]);self.assertEqual(len(store.runs()),20)

    def test_ready_retry_and_disabled_manual_are_kept_future_retry_waits(self):
        task=self.task(1);Engine({'reminder':lambda t,n:Result('A','B','Напоминания')},lambda:self.now,inline=True).tick()
        with store.connect() as db:
            db.execute("INSERT INTO runs(task_id,slot,scheduled_at,status,retry_at) VALUES(?,?,?,'retry',?)",(task['id'],'future',self.now.isoformat(),(self.now+timedelta(hours=1)).isoformat()))
        calls=[];engine=Engine({'reminder':lambda t,n:(calls.append(t['id']) or Result('A','B','Напоминания'))},lambda:self.now,inline=True)
        engine.tick();self.assertEqual(calls,[])
        task['enabled']=False;store.save_task(task);engine.run_now(task['id']);self.assertEqual(calls,[task['id']])
        task['enabled']=True;store.save_task(task);engine.tick(self.now+timedelta(hours=1))
        self.assertEqual(len(calls),2);self.assertTrue(all(r['status']=='success' for r in store.runs()))

    def test_latest_run_uses_id_and_today_keeps_only_latest_reminder_in_chain(self):
        task=self.task(1)
        with store.connect() as db:
            for slot,stamp in [('late',self.now),('manual-earlier',self.now-timedelta(days=1))]:
                db.execute("INSERT INTO runs(task_id,slot,scheduled_at,status) VALUES(?,?,?,'success')",(task['id'],slot,stamp.isoformat()))
            root=db.execute("INSERT INTO events(title,body,category,created,action_state) VALUES('R','B','Напоминания',?,'snoozed')",(self.now.isoformat(),)).lastrowid
            db.execute('UPDATE events SET root_id=id WHERE id=?',(root,))
            db.execute("INSERT INTO events(title,body,category,created,action_state,root_id) VALUES('R','B','Напоминания',?,'pending',?)",(self.now.isoformat(),root))
        self.assertEqual(store.latest_runs()[task['id']]['slot'],'manual-earlier')
        revision=store.revision();model=today_service.snapshot(self.now)
        self.assertEqual(model['counts']['pending_reminders'],1);self.assertEqual(store.revision(),revision)

    def test_dispatch_rechecks_retry_deadline_after_queue_snapshot(self):
        task=self.task(1)
        with store.connect() as db:
            run=db.execute("INSERT INTO runs(task_id,slot,scheduled_at,status) VALUES(?,?,?,'queued')",(task['id'],'stale',self.now.isoformat())).lastrowid
        original=store.connect;calls=[];connections=0
        @contextmanager
        def rescheduled():
            nonlocal connections
            connections+=1
            if connections==2:
                with original() as db:db.execute("UPDATE runs SET status='retry',retry_at=? WHERE id=?",((self.now+timedelta(hours=1)).isoformat(),run))
            with original() as db:yield db
        engine=Engine({'reminder':lambda t,n:(calls.append(t['id']) or Result('A','B','Напоминания'))},lambda:self.now,inline=True)
        with patch.object(store,'connect',rescheduled):engine._dispatch(self.now,task_map={task['id']:task})
        self.assertEqual(calls,[]);self.assertEqual(store.runs()[0]['attempts'],0)

    def test_project_search_unicode_filter_and_limit_keep_same_order(self):
        keys=[projects.create(f'КОРПУС {i}','print') for i in range(25)]
        projects.save(keys[-1],state='archived')
        all_rows=projects.summaries('корпус','current');limited=projects.summaries('корпус','current',limit=10)
        self.assertEqual(len(all_rows),24);self.assertEqual(limited,all_rows[:10])
        self.assertEqual(len(projects.summaries('корпус','archived',limit=10)),1)
        with self.assertRaises(ValueError):projects.summaries(limit=0)
