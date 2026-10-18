from datetime import datetime,timedelta
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import desktop_store as store
import project_service as projects
from automation_models import new_task
from automation_engine import Engine
from today_service import snapshot


class TodayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'HOME',Path(self.temp.name));self.patch.start()
        store.initialize();self.now=datetime(2026,10,20,10,tzinfo=store.LOCAL)

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def test_empty_dashboard_is_read_only_and_does_not_start_learning(self):
        before=store.revision();data=snapshot(self.now)
        self.assertEqual(data['counts'],{'enabled_tasks':0,'active_projects':0,'pending_reminders':0})
        self.assertEqual(data['upcoming'],[]);self.assertEqual(before,store.revision())
        with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_progress').fetchone()[0],0)
        json.dumps(data)

    def test_today_schedule_excludes_disabled_tasks_and_tomorrow(self):
        for name,hours,enabled in [('Today',1,True),('Tomorrow',25,True),('Disabled',2,False)]:
            store.save_task(new_task(name,'reminder',{'type':'once','at':(self.now+timedelta(hours=hours)).isoformat()},enabled=enabled,now=self.now))
        data=snapshot(self.now);self.assertEqual(data['counts']['enabled_tasks'],2)
        self.assertEqual([r['name'] for r in data['upcoming']],['Today'])

    def test_overdue_once_keeps_original_time(self):
        original=self.now-timedelta(days=1)
        task=new_task('Overdue','reminder',{'type':'once','at':original.isoformat()},enabled=True,now=original)
        store.save_task(task);row=snapshot(self.now)['upcoming'][0]
        self.assertEqual(datetime.fromisoformat(row['at']),original);self.assertEqual(row['state'],'overdue')

    def test_snooze_has_one_action_and_new_event_is_used_after_delivery(self):
        task=new_task('Read','reminder',{'type':'once','at':self.now.isoformat()},now=self.now)
        store.save_task(task);Engine(clock=lambda:self.now,inline=True).run_now(task['id'])
        row=snapshot(self.now)['reminders'][0]
        store.reminder_action(row['id'],'snooze',now=self.now)
        data=snapshot(self.now);self.assertEqual(data['counts']['pending_reminders'],1)
        self.assertEqual(data['reminders'][0]['snoozed_until'],(self.now+timedelta(minutes=15)).isoformat())
        store.deliver_snoozes(self.now+timedelta(minutes=15));new=snapshot(self.now)['reminders']
        self.assertEqual(len(new),1);self.assertNotEqual(new[0]['id'],row['id'])
        store.reminder_action(new[0]['id'],'done',now=self.now)
        self.assertEqual(snapshot(self.now)['counts']['pending_reminders'],0)

    def test_demo_history_is_retained_but_not_shown_or_delivered(self):
        demo=store.publish('Old demo','Synthetic','Демо');normal=store.publish('Result','Actual','Проекты')
        self.assertEqual(len(store.events()),2)
        self.assertEqual([r['id'] for r in store.user_events()],[normal])
        self.assertEqual([r['id'] for r in store.pending_events()],[normal])
        self.assertTrue(any(r['id']==demo and not r['delivered'] for r in store.events()))

    def test_only_active_projects_contribute_next_steps(self):
        key=projects.create('Active','pc');record=projects.get(key)
        projects.edit_step(key,record['steps'][0]['id'],done=True)
        paused=projects.create('Paused','dacha');projects.save(paused,state='paused')
        data=snapshot(self.now)
        self.assertEqual(data['counts']['active_projects'],1)
        self.assertEqual(data['projects'][0]['next_step'],record['steps'][1]['title'])
        projects.save(key,state='completed');self.assertEqual(snapshot(self.now)['projects'],[])

    def test_pause_changes_presentation_without_changing_tasks(self):
        task=new_task('Later','reminder',{'type':'once','at':(self.now+timedelta(hours=1)).isoformat()},enabled=True,now=self.now)
        store.save_task(task);store.set_setting('paused',True)
        data=snapshot(self.now);self.assertTrue(data['paused']);self.assertEqual(len(data['upcoming']),1)
        self.assertEqual(store.runs(),[])
