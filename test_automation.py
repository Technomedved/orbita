from datetime import datetime,timedelta
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import desktop_store as store
from automation_models import new_task, latest_due, next_due, Result, validate_schedule
from automation_engine import Engine, quiet_now
from automation_handlers import audit_result


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(store,'HOME',Path(self.temp.name)); self.patch.start()
        self.now=datetime(2026,10,16,8,0,tzinfo=store.LOCAL)
        self.clock=lambda:self.now
        store.initialize()
        self.calls=[]
        def handler(task,now):
            self.calls.append(task['id'])
            return Result(task['name'],'Body','Напоминания',reminder=task['kind']=='reminder')
        self.handler=handler
        self.engine=Engine({'reminder':handler,'weather':handler,'audit':handler},self.clock,inline=True)

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def task(self,kind='reminder',spec=None,enabled=True):
        spec=dict(spec or {'type':'once','at':self.now.isoformat()},timezone='Asia/Yekaterinburg')
        task=new_task('Example',kind,spec or {'type':'once','at':self.now.isoformat()},
                      enabled=enabled,now=self.now-timedelta(days=1))
        store.save_task(task); return task

    def test_schedule_weekday_and_next(self):
        task=self.task(spec={'type':'daily','time':'08:00','days':[0,1,2,3,4]})
        self.assertEqual(latest_due(task,self.now),self.now)
        self.assertEqual(next_due(task,self.now).weekday(),0)
        self.assertEqual(latest_due(task,self.now+timedelta(days=1)),self.now)

    def test_invalid_schedules_rejected(self):
        for spec in [{'type':'daily','time':'26:00'}, {'type':'daily','time':'08:00','days':[]},
                     {'type':'once','at':'2026-10-16T08:00:00'}, {'type':'weekly','time':'08:00','days':[1,2]}]:
            with self.assertRaises((ValueError,KeyError)):validate_schedule(spec)

    def test_once_is_durable_and_no_duplicate_after_restart(self):
        task=self.task(); self.engine.tick(); self.engine.tick()
        second=Engine(self.engine.handlers,self.clock,inline=True); second.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(store.events()),1)
        self.assertFalse(next(t for t in store.tasks() if t['id']==task['id'])['enabled'])

    def test_weather_missed_window_is_logged_not_run(self):
        task=self.task('weather',{'type':'daily','time':'08:00','days':[4]})
        task['policy']='skip'; store.save_task(task)
        self.now+=timedelta(hours=2); self.engine.tick()
        self.assertEqual(self.calls,[])
        self.assertEqual(store.runs(task['id'])[0]['status'],'skipped')

    def test_latest_catchup_coalesces_week_offline(self):
        task=self.task(spec={'type':'daily','time':'08:00','days':list(range(7))})
        self.now+=timedelta(days=10,hours=4); self.engine.tick()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(store.runs(task['id'])),1)

    def test_snooze_survives_restart_and_fires_once(self):
        self.task(); self.engine.tick(); original=store.events()[0]
        store.reminder_action(original['id'],'snooze',self.now)
        self.now+=timedelta(minutes=14); self.engine.tick(); self.assertEqual(len(store.events()),1)
        self.now+=timedelta(minutes=1)
        Engine(self.engine.handlers,self.clock,inline=True).tick()
        self.engine.tick(); self.assertEqual(len(store.events()),2)
        self.assertEqual(store.events()[0]['action_state'],'pending')
        store.reminder_action(original['id'],'done',self.now)
        self.assertTrue(all(e['action_state']=='done' for e in store.events()))

    def test_done_cancels_snooze(self):
        self.task(); self.engine.tick(); event=store.events()[0]
        store.reminder_action(event['id'],'snooze',self.now)
        store.reminder_action(event['id'],'done',self.now)
        self.now+=timedelta(hours=1); self.engine.tick()
        self.assertEqual(len(store.events()),1)

    def test_failure_retry_bounds_and_error_dedup(self):
        task=self.task('weather'); task['max_attempts']=2; task['retry_seconds']=60; store.save_task(task)
        def fail(*args):raise OSError('offline')
        engine=Engine({'weather':fail},self.clock,inline=True)
        engine.tick(); self.assertEqual(store.runs(task['id'])[0]['status'],'retry')
        self.now+=timedelta(seconds=30); engine.tick()
        self.assertEqual(store.runs(task['id'])[0]['attempts'],1)
        self.now+=timedelta(seconds=30); engine.tick()
        self.assertEqual(store.runs(task['id'])[0]['status'],'failed')
        engine.run_now(task['id']); self.now+=timedelta(seconds=60); engine.tick()
        self.assertEqual(len(store.events()),1)

    def test_abandoned_lease_recovers(self):
        task=self.task()
        run=self.engine._enqueue(task,self.now,self.now.isoformat())
        with store.connect() as db:
            db.execute("UPDATE runs SET status='running',attempts=1,owner='dead',lease_until=? WHERE id=?",
                       ((self.now-timedelta(seconds=1)).isoformat(),run))
        self.engine.tick()
        self.assertEqual(store.runs(task['id'])[0]['status'],'success')
        self.assertEqual(len(store.events()),1)

    def test_atomic_result_rollback_and_recovery(self):
        task=self.task(); task['max_attempts']=2; store.save_task(task)
        run=self.engine._enqueue(task,self.now,self.now.isoformat())
        with store.connect() as db:
            db.execute("UPDATE runs SET status='running',attempts=1,owner=?,lease_until=? WHERE id=?",
                       (self.engine.owner,(self.now+timedelta(seconds=60)).isoformat(),run))
            db.execute("CREATE TRIGGER reject_success BEFORE UPDATE ON runs WHEN NEW.status='success' BEGIN SELECT RAISE(ABORT,'simulated crash'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.engine._success(task,run,Result('Title','Body','Напоминания',reminder=True))
        self.assertEqual(store.events(),[])
        with store.connect() as db:db.execute('DROP TRIGGER reject_success')
        self.now+=timedelta(seconds=61); self.engine.tick()
        self.assertEqual(len(store.events()),1)

    def test_two_engines_cannot_execute_same_slot_twice(self):
        task=self.task()
        def work():Engine(self.engine.handlers,self.clock,inline=True).tick()
        threads=[threading.Thread(target=work) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(store.runs(task['id'])),1)

    def test_pause_stops_schedules_not_manual(self):
        task=self.task(); store.set_setting('paused',True); self.engine.tick()
        self.assertEqual(self.calls,[])
        self.engine.run_now(task['id']); self.assertEqual(len(self.calls),1)

    def test_quiet_hours_cross_midnight(self):
        settings={'quiet_enabled':True,'quiet_start':'22:00','quiet_end':'08:00'}
        self.assertFalse(quiet_now(settings,self.now))
        self.assertTrue(quiet_now(settings,self.now.replace(hour=23)))
        self.assertTrue(quiet_now(settings,self.now.replace(hour=7)))
        self.assertTrue(quiet_now({'dnd':True},self.now))

    def test_audit_uses_actual_runs(self):
        self.task(); self.engine.tick()
        result=audit_result({},self.now)
        self.assertIn('Успешных запусков: 1',result.body)
        self.assertIn('Данных пока мало',result.body)
        self.assertFalse(next(t for t in store.tasks() if t['id']=='audit')['enabled'])

    def test_weather_failure_keeps_previous_snapshot(self):
        store.set_setting('weather_snapshot',{'date':'2026-10-15','old':True})
        task=self.task('weather'); task['max_attempts']=1; store.save_task(task)
        def fail(*args):raise OSError('offline')
        Engine({'weather':fail},self.clock,inline=True).tick()
        self.assertTrue(store.get_setting('weather_snapshot')['old'])

    def test_disabling_task_stops_pending_retry(self):
        task=self.task('weather'); task['max_attempts']=2; store.save_task(task)
        def fail(*args):raise OSError('offline')
        engine=Engine({'weather':fail},self.clock,inline=True); engine.tick()
        task['enabled']=False; store.save_task(task)
        self.now+=timedelta(hours=1); engine.tick()
        self.assertEqual(store.runs(task['id'])[0]['attempts'],1)

    def test_lease_recovery_is_bounded_and_reports_error(self):
        task=self.task(); run=self.engine._enqueue(task,self.now,self.now.isoformat())
        with store.connect() as db:
            db.execute("UPDATE runs SET status='running',recoveries=3,attempts=4,lease_until=? WHERE id=?",
                       ((self.now-timedelta(seconds=1)).isoformat(),run))
        self.engine.tick()
        self.assertEqual(store.runs(task['id'])[0]['status'],'failed')
        self.assertEqual(len(store.events()),1)


class MigrationTests(unittest.TestCase):
    def test_failed_migration_rolls_back_schema(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'HOME',Path(folder)):
            path=Path(folder)/'inbox.sqlite'
            with closing(sqlite3.connect(path)) as db,db:
                db.executescript('CREATE TABLE events(id INTEGER PRIMARY KEY,title TEXT,body TEXT,category TEXT,created TEXT,seen INTEGER,dedupe TEXT UNIQUE); CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);')
                db.execute("INSERT INTO settings VALUES('bad','invalid-json')")
            with self.assertRaises(json.JSONDecodeError):store.initialize()
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],0)
                self.assertNotIn('delivered',{r[1] for r in db.execute('PRAGMA table_info(events)')})
            self.assertEqual(len(list((Path(folder)/'backups').glob('*.sqlite'))),1)

    def test_legacy_backup_preserves_history_settings_and_schedule(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'HOME',Path(folder)):
            path=Path(folder)/'inbox.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('CREATE TABLE events(id INTEGER PRIMARY KEY,title TEXT,body TEXT,category TEXT,created TEXT,seen INTEGER,dedupe TEXT UNIQUE); CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);')
                db.execute("INSERT INTO events VALUES(7,'Old','Body','Погода','2026-10-15T08:00:00+05:00',0,'old')")
                db.executemany('INSERT INTO settings VALUES(?,?)',[('weather_enabled','true'),('topmost','false'),('weather_day','"2026-10-16"')])
            store.initialize(); store.initialize()
            self.assertEqual(store.events()[0]['id'],7)
            self.assertFalse(store.get_setting('topmost'))
            self.assertTrue(next(t for t in store.tasks() if t['id']=='weather')['enabled'])
            self.assertEqual(len(store.pending_events()),0)
            self.assertEqual(len(list((Path(folder)/'backups').glob('*.sqlite'))),1)
            backup=next((Path(folder)/'backups').glob('*.sqlite'))
            with closing(sqlite3.connect(backup)) as db:self.assertEqual(db.execute('SELECT title FROM events').fetchone()[0],'Old')

    def test_newer_schema_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'HOME',Path(folder)):
            with closing(sqlite3.connect(Path(folder)/'inbox.sqlite')) as db, db:db.execute('PRAGMA user_version=99')
            with self.assertRaises(RuntimeError):store.initialize()


if __name__=='__main__':unittest.main()
