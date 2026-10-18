from contextlib import closing
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import desktop_store as store
import learning_service as learning
from db2_content import LESSONS,BY_ID,TABLES,fixture_sql
from automation_engine import Engine


def records(table):
    return [dict(zip([c[0] for c in TABLES[table]['columns']],row)) for row in TABLES[table]['rows']]


class ContentTests(unittest.TestCase):
    """Independent Python reasoning checks expected rows, not Db2 SQL execution."""
    def test_catalog_and_fixture_integrity(self):
        self.assertEqual(len(LESSONS),7)
        self.assertEqual(len(BY_ID),7)
        self.assertEqual(sum(len(t['rows']) for t in TABLES.values()),25)
        for item in LESSONS:
            for key in ['goal','explanation','task','solution','solution_notes','checks','sources']:
                self.assertTrue(item[key],(item['id'],key))
            self.assertGreaterEqual(len(item['hints']),3)
            self.assertTrue(all(len(row)==len(item['expected']['columns']) for row in item['expected']['rows']))
        sql=fixture_sql()
        self.assertEqual(sql.count('CREATE TABLE '),4)
        self.assertEqual(sql.count('INSERT INTO '),25)
        self.assertNotIn('DROP TABLE',sql)
        employees={r['EMPLOYEE_ID'] for r in records('ORB_EMPLOYEES')}
        docs={r['DOC_ID'] for r in records('ORB_DOCS')}
        self.assertTrue(all(r['OWNER_ID'] is None or r['OWNER_ID'] in employees for r in records('ORB_DOCS')))
        self.assertTrue(all(r['DOC_ID'] in docs for r in records('ORB_VERSIONS')+records('ORB_GRANTS')))

    def test_published_counts(self):
        versions=records('ORB_VERSIONS')
        actual=[[d['DOC_ID'],sum(v['DOC_ID']==d['DOC_ID'] and v['STATE']=='PUBLISHED' for v in versions)] for d in records('ORB_DOCS')]
        self.assertEqual(actual,BY_ID['joins']['expected']['rows'])

    def test_independent_child_counts(self):
        actual=[]
        for doc in records('ORB_DOCS'):
            key=doc['DOC_ID']; versions=[v for v in records('ORB_VERSIONS') if v['DOC_ID']==key]
            grants=[g for g in records('ORB_GRANTS') if g['DOC_ID']==key]
            actual.append([key,len(versions),len(grants),len({g['EMPLOYEE_ID'] for g in grants if g['EMPLOYEE_ID'] is not None})])
        self.assertEqual(actual,BY_ID['aggregation']['expected']['rows'])

    def test_nulls_and_audit_flags(self):
        employees={e['EMPLOYEE_ID']:e for e in records('ORB_EMPLOYEES')}
        active={key for key,e in employees.items() if e['ACTIVE']=='Y'}
        readers={g['DOC_ID'] for g in records('ORB_GRANTS') if g['ACCESS_CODE']=='READ' and g['EMPLOYEE_ID'] in active}
        self.assertEqual([[d['DOC_ID'],d['TITLE']] for d in records('ORB_DOCS') if d['DOC_ID'] not in readers],BY_ID['nulls']['expected']['rows'])
        has_versions={v['DOC_ID'] for v in records('ORB_VERSIONS')}
        flags=[[d['DOC_ID'],int(d['DOC_ID'] not in has_versions),int(d['OWNER_ID'] not in active),int(d['DOC_ID'] not in readers)] for d in records('ORB_DOCS')]
        self.assertEqual([row for row in flags if any(row[1:])],BY_ID['cte']['expected']['rows'])

    def test_latest_version_ties(self):
        actual=[]
        for doc in records('ORB_DOCS'):
            versions=[v for v in records('ORB_VERSIONS') if v['DOC_ID']==doc['DOC_ID']]
            latest=max(versions,key=lambda v:(v['CREATED_AT'],v['VERSION_NO'],v['VERSION_ID'])) if versions else None
            actual.append([doc['DOC_ID']]+([latest['VERSION_ID'],latest['VERSION_NO'],latest['STATE']] if latest else [None,None,None]))
        self.assertEqual(actual,BY_ID['windows']['expected']['rows'])

    def test_half_open_date_interval(self):
        actual=[[v['VERSION_ID'],v['DOC_ID'],v['CREATED_AT']] for v in records('ORB_VERSIONS')
                if v['STATE']=='PUBLISHED' and '2026-10-03 00:00:00'<=v['CREATED_AT']<'2026-10-05 00:00:00']
        actual.sort(key=lambda row:(row[1],row[0]))
        self.assertEqual(actual,BY_ID['dates']['expected']['rows'])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.patch=patch.object(store,'HOME',Path(self.temp.name)); self.patch.start()
        store.initialize()

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def test_autosave_persists_across_process_without_executing_sql(self):
        text='DROP TABLE events;\nSELECT "учебный ответ";'
        learning.start('joins'); learning.save_progress('joins',answer=text,notes='Проверю в учебной Db2 позже')
        env=dict(os.environ,AUTOMATION_HOME=self.temp.name,PYTHONIOENCODING='utf-8')
        result=subprocess.run([sys.executable,'-c','import json,learning_service as l; print(json.dumps(l.progress("joins")))'],
                              capture_output=True,text=True,encoding='utf-8',env=env,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        saved=json.loads(result.stdout); self.assertEqual(saved['answer'],text); self.assertEqual(saved['state'],'in_progress')
        with store.connect() as db:self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='events'").fetchone())

    def test_hints_solution_and_completion_preserve_answer(self):
        learning.save_progress('joins',answer='SELECT d.DOC_ID ...',notes='Черновик')
        self.assertFalse(learning.progress('joins')['solution_revealed'])
        self.assertEqual(learning.reveal_hint('joins'),1)
        learning.reveal_solution('joins'); learning.complete('joins')
        learning.save_progress('joins',notes='Самостоятельно сравнил')
        row=learning.progress('joins')
        self.assertEqual(row['answer'],'SELECT d.DOC_ID ...'); self.assertTrue(row['solution_revealed'])
        self.assertEqual(row['hints_revealed'],1); self.assertEqual(row['state'],'completed_user')

    def test_self_assessment_orders_topics_with_prerequisites(self):
        assessment={key:'comfortable' for key in learning.TOPICS}; assessment['windows']='needs_work'
        learning.save_progress('diagnostic',assessment=assessment); learning.complete('diagnostic')
        order=learning.recommended_order()
        self.assertEqual(order[0],'windows'); self.assertLess(order.index('joins'),order.index('aggregation'))
        self.assertLess(order.index('nulls'),order.index('cte')); self.assertLess(order.index('aggregation'),order.index('cte'))
        learning.complete('windows'); self.assertNotIn('windows',learning.recommended_order())

    def test_notification_never_advances_unfinished_lesson_or_duplicates_card(self):
        task=next(t for t in store.tasks() if t['id']=='learning-db2'); self.assertFalse(task['enabled'])
        from zoneinfo import ZoneInfo
        now=datetime(2026,10,20,19,30,tzinfo=ZoneInfo(task['schedule']['timezone']))
        task['enabled']=True; task['created']=(now-timedelta(days=1)).isoformat(); store.save_task(task)
        engine=Engine(clock=lambda:now,inline=True)
        engine.tick(); engine.tick()
        first=store.events()[0]; self.assertEqual(first['target'],'lesson:db2:diagnostic')
        learning.start('diagnostic'); store.mark_seen(first['id'])
        now+=timedelta(days=2); engine.tick()
        self.assertEqual(len(store.events()),1); self.assertEqual(store.events()[0]['id'],first['id'])
        self.assertIn('Продолжить',store.events()[0]['title'])
        self.assertEqual(len(store.runs(task['id'])),2)
        self.assertEqual(learning.progress('joins')['state'],'not_started')
        self.assertEqual(learning.progress('diagnostic')['state'],'in_progress')

    def test_completed_diagnostic_selects_next_and_preserves_old_notification_target(self):
        engine=Engine(inline=True); engine.run_now('learning-db2')
        learning.complete('diagnostic'); engine.run_now('learning-db2')
        self.assertEqual({e['target'] for e in store.events()},{'lesson:db2:diagnostic','lesson:db2:joins'})

    def test_all_completed_is_not_automatic_sql_verification(self):
        for item in LESSONS:learning.complete(item['id'])
        self.assertIsNone(learning.current_lesson())
        Engine(inline=True).run_now('learning-db2')
        row=store.events()[0]; self.assertEqual(row['target'],'course:db2')
        self.assertIn('не автоматическая проверка',row['body'])

    def test_codex_question_is_self_contained_and_does_not_reveal_solution(self):
        learning.set_profile(platform='z/OS',server_version='13 (со слов пользователя)')
        learning.save_progress('joins',answer='SELECT 42;',notes='Не понимаю нулевые строки')
        question=learning.codex_question('joins','Почему пропадает 105?')
        for expected in ['z/OS','SELECT 42;','Почему пропадает 105?','ORB_VERSIONS','1007','null','SQLite']:
            self.assertIn(expected,question)
        self.assertNotIn(BY_ID['joins']['solution'],question)

    def test_invalid_changes_do_not_overwrite_progress(self):
        learning.save_progress('joins',answer='SELECT 1;')
        with self.assertRaises(ValueError):learning.save_progress('joins',state='verified')
        with self.assertRaises(ValueError):learning.save_progress('joins',hints_revealed=99)
        self.assertEqual(learning.progress('joins')['answer'],'SELECT 1;')


class LearningMigrationTests(unittest.TestCase):
    def test_v3_migration_preserves_history_settings_and_existing_schedule(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'HOME',Path(folder)):
            with closing(sqlite3.connect(Path(folder)/'inbox.sqlite')) as db,db:
                db.executescript('''CREATE TABLE events(id INTEGER PRIMARY KEY,title TEXT,body TEXT,category TEXT,
                    created TEXT,seen INTEGER,dedupe TEXT UNIQUE,task_id TEXT,run_id INTEGER,action_state TEXT DEFAULT '',
                    root_id INTEGER,delivered INTEGER DEFAULT 0);
                    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
                    CREATE TABLE tasks(id TEXT PRIMARY KEY,name TEXT,kind TEXT,enabled INTEGER,schedule TEXT,
                        config TEXT,policy TEXT,grace_seconds INTEGER,max_attempts INTEGER,retry_seconds INTEGER,created TEXT);
                    PRAGMA user_version=3;''')
                db.execute("INSERT INTO events(id,title,body,category,created,seen,dedupe,delivered) VALUES(12,'Old','Body','Проекты','2026-10-16T08:00:00+05:00',0,'old',0)")
                db.execute("INSERT INTO settings VALUES('window_geometry','[50,60,670,800]')")
                old_schedule=json.dumps({'type':'daily','time':'07:45','days':[0,2]})
                db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    ('weather','My weather','weather',1,old_schedule,'{}','skip',1800,2,120,'2026-10-15T08:00:00+05:00'))
            store.initialize()
            self.assertEqual(store.events()[0]['id'],12); self.assertEqual(store.events()[0]['delivered'],0)
            self.assertEqual(store.get_setting('window_geometry'),[50,60,670,800])
            self.assertIsNone(store.events()[0]['target'])
            self.assertFalse(next(t for t in store.tasks() if t['id']=='learning-db2')['enabled'])
            weather=next(t for t in store.tasks() if t['id']=='weather')
            self.assertTrue(weather['enabled']); self.assertEqual(weather['schedule'],dict(json.loads(old_schedule),timezone='Asia/Yekaterinburg'))
            self.assertEqual(weather['grace_seconds'],1800); self.assertEqual(weather['max_attempts'],2)
            self.assertEqual(len(list((Path(folder)/'backups').glob('*.sqlite'))),1)
            learning.save_progress('joins',answer='Saved after migration')
            store.initialize(); self.assertEqual(learning.progress('joins')['answer'],'Saved after migration')


if __name__=='__main__':unittest.main()
