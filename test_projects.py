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
import project_service as projects
import learning_service as learning
from automation_engine import Engine
from automation_handlers import reminder_result


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'HOME',Path(self.temp.name));self.patch.start();store.initialize()

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_no_projects_are_created_by_migration_or_reading(self):
        self.assertEqual(projects.summaries(),[])
        self.assertFalse(any(t['config'].get('project_id') for t in store.tasks()))

    def test_template_notes_steps_and_links_survive_new_process(self):
        key=projects.create('Крепление на принтер','print')
        record=projects.get(key);self.assertEqual(len(record['steps']),5)
        projects.save(key,notes='Отверстия 4 мм\nПроверить посадку')
        projects.edit_step(key,record['steps'][0]['id'],done=True)
        projects.add_link(key,'Модель','https://example.com/model')
        script="import json,project_service as p;print(json.dumps(p.get('"+key+"'),ensure_ascii=False))"
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).parent,env=dict(os.environ,AUTOMATION_HOME=self.temp.name),capture_output=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        loaded=json.loads(result.stdout);self.assertEqual(loaded['notes'],'Отверстия 4 мм\nПроверить посадку')
        self.assertEqual(loaded['steps'][0]['done'],1);self.assertEqual(loaded['links'][0]['url'],'https://example.com/model')
        self.assertEqual(loaded['state'],'active')

    def test_next_step_and_search_are_derived_from_real_checklist(self):
        key=projects.create('ПК для дома','pc');record=projects.get(key)
        projects.edit_step(key,record['steps'][0]['id'],done=True)
        rows=projects.summaries('пк');self.assertEqual(rows[0]['done'],1);self.assertEqual(rows[0]['next_step'],record['steps'][1]['title'])
        for step in record['steps']:projects.edit_step(key,step['id'],done=True)
        self.assertIsNone(projects.summaries()[0]['next_step']);self.assertEqual(projects.get(key)['state'],'active')

    def test_project_edits_cannot_modify_other_project_steps(self):
        a=projects.create('One');b=projects.create('Two');step=projects.add_step(a,'Original')
        with self.assertRaises(ValueError):projects.edit_step(b,step,title='Wrong')
        projects.remove_step(b,step)
        self.assertEqual(projects.get(a)['steps'][0]['title'],'Original')

    def test_links_are_deduplicated_and_executable_schemes_rejected(self):
        key=projects.create('Ссылки')
        first=projects.add_link(key,'Инструкция','https://example.com/manual')
        self.assertEqual(projects.add_link(key,'Другая подпись','https://example.com/manual'),first)
        self.assertEqual(len(projects.get(key)['links']),1)
        for url in ['file:///C:/evil.exe','javascript:alert(1)','https://login:password@example.com','https://','https://example.com\n/evil','https://example.com:wrong']:
            with self.subTest(url=url),self.assertRaises(ValueError):projects.add_link(key,'Bad',url)

    def test_reminder_defaults_disabled_and_reconfiguration_reuses_one_task(self):
        key=projects.create('Корпус');at=(datetime.now(store.LOCAL)+timedelta(hours=1)).isoformat()
        first=projects.save_reminder(key,at);second=projects.save_reminder(key,at,True)
        self.assertEqual(first,second)
        task=next(t for t in store.tasks() if t['id']==first);self.assertTrue(task['enabled'])
        self.assertEqual(sum(t['config'].get('project_id')==key for t in store.tasks()),1)
        b=projects.create('Ещё один');tid=projects.save_reminder(b,at)
        self.assertFalse(next(t for t in store.tasks() if t['id']==tid)['enabled'])

    def test_due_run_deduplication_and_snooze_preserve_project_navigation(self):
        key=projects.create('Компьютер','pc');at=datetime.now(store.LOCAL)+timedelta(minutes=5)
        tid=projects.save_reminder(key,at.isoformat(),True)
        engine=Engine(clock=lambda:at,inline=True);engine.tick();engine.tick()
        self.assertEqual(len(store.runs(tid)),1);self.assertEqual(len(store.events()),1)
        event=store.events()[0];self.assertEqual(event['target'],'project:'+key);self.assertEqual(event['category'],'Проекты')
        self.assertIn('Следующий шаг',event['body'])
        store.reminder_action(event['id'],'snooze',now=at);store.deliver_snoozes(at+timedelta(minutes=15))
        self.assertEqual(store.events()[0]['target'],'project:'+key)
        self.assertEqual(projects.get(key)['steps'][0]['done'],0)

    def test_archive_cancels_snooze_and_requires_explicit_reenable_after_restore(self):
        key=projects.create('Дача','dacha');at=datetime.now(store.LOCAL)+timedelta(minutes=5)
        tid=projects.save_reminder(key,at.isoformat(),True);Engine(clock=lambda:at,inline=True).tick()
        store.reminder_action(store.events()[0]['id'],'snooze',now=at)
        projects.save(key,state='archived');store.deliver_snoozes(at+timedelta(minutes=20))
        self.assertEqual(len(store.events()),1);self.assertEqual(store.events()[0]['action_state'],'cancelled')
        store.reminder_action(store.events()[0]['id'],'snooze',now=at)
        with store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM snoozes WHERE status='pending'").fetchone()[0],0)
        projects.save(key,state='active');self.assertFalse(next(t for t in store.tasks() if t['id']==tid)['enabled'])
        self.assertEqual(len(projects.get(key)['steps']),5)

    def test_archive_during_worker_result_prevents_stale_notification(self):
        key=projects.create('Race');at=datetime.now(store.LOCAL)+timedelta(minutes=5)
        tid=projects.save_reminder(key,at.isoformat(),True)
        def handler(task,now):
            result=reminder_result(task,now);projects.save(key,state='archived');return result
        Engine(handlers={'reminder':handler},clock=lambda:at,inline=True).tick()
        self.assertEqual(store.events(),[]);self.assertEqual(store.runs(tid)[0]['status'],'cancelled')

    def test_reschedule_during_worker_result_cancels_old_result(self):
        key=projects.create('Reschedule');at=datetime.now(store.LOCAL)+timedelta(minutes=5)
        tid=projects.save_reminder(key,at.isoformat(),True)
        def handler(task,now):
            result=reminder_result(task,now);projects.save_reminder(key,(at+timedelta(hours=2)).isoformat(),True);return result
        Engine(handlers={'reminder':handler},clock=lambda:at,inline=True).tick()
        self.assertEqual(store.events(),[]);self.assertEqual(store.runs(tid)[0]['status'],'cancelled')
        self.assertTrue(next(t for t in store.tasks() if t['id']==tid)['enabled'])

    def test_completed_or_paused_project_blocks_reenabling_from_generic_task_editor(self):
        key=projects.create('Paused');tid=projects.save_reminder(key,(datetime.now(store.LOCAL)+timedelta(hours=1)).isoformat())
        for state in ('paused','completed','archived'):
            projects.save(key,state=state);task=next(t for t in store.tasks() if t['id']==tid);task['enabled']=True
            with self.assertRaises(ValueError):store.save_task(task)
        projects.save(key,state='active');self.assertEqual(projects.summaries()[0]['id'],key)

    def test_v4_migration_preserves_learning_and_settings_with_verified_backup(self):
        learning.save_progress('diagnostic',answer='Unfinished SQL',notes='Вернусь позже')
        store.set_setting('window_geometry',[20,30,650,850]);store.publish('Old','Body',dedupe='old')
        with store.connect() as db:
            db.execute('PRAGMA user_version=4')
            before=list(db.execute('SELECT * FROM learning_progress'))
            for table in ('project_links','project_steps','projects'):db.execute('DROP TABLE '+table)
        store._initialized.discard(str(store.HOME.resolve()));store.initialize()
        self.assertEqual(learning.progress('diagnostic')['answer'],'Unfinished SQL')
        self.assertEqual(store.get_setting('window_geometry'),[20,30,650,850]);self.assertEqual(store.events()[0]['dedupe'],'old')
        backups=list((store.HOME/'backups').glob('inbox-v4-*.sqlite'));self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT answer FROM learning_progress').fetchone()[0],'Unfinished SQL')


if __name__=='__main__':unittest.main()
