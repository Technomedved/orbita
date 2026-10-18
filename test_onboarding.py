"""Neutral installation defaults, isolated profiles, migration and offline first run."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import desktop_store as store
import preferences_service as preferences
import project_service as projects
import learning_service as learning
import today_service
import agenda_service
import weather
from automation_defaults import WEATHER_NAME
from automation_models import new_task
from automation_engine import Engine
from release_layout import copy_public_files,verify_public_layout,PUBLIC_DOCS


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)/'Профиль пользователя'
        self.patch=patch.object(store,'HOME',self.home);self.patch.start();store.initialize()

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def test_stock_profile_is_empty_disabled_and_has_no_implicit_city(self):
        self.assertEqual(store.events(),[]);self.assertEqual(store.runs(),[]);self.assertEqual(projects.summaries(),[])
        self.assertEqual(learning.overview(),{});self.assertIsNone(store.get_setting('location_profile'))
        self.assertTrue(store.get_setting('onboarding_pending'))
        self.assertFalse(any(t['enabled'] for t in store.tasks()))
        task=next(t for t in store.tasks() if t['id']=='weather')
        self.assertEqual(task['name'],WEATHER_NAME);self.assertEqual(task['schedule']['days'],list(range(7)))
        with patch('weather.urlopen') as network:
            Engine(inline=True).tick()
            with self.assertRaises(ValueError):weather.forecast('2026-10-18')
            network.assert_not_called()

    def test_first_run_can_finish_without_weather_or_network_in_non_whole_hour_zone(self):
        preferences.bootstrap('Europe/Berlin');self.assertEqual(store.timezone_name(),'Europe/Berlin')
        preferences.complete('Asia/Kathmandu',False,False)
        self.assertFalse(store.get_setting('onboarding_pending'));self.assertTrue(store.get_setting('location_setup_complete'))
        self.assertFalse(store.get_setting('toasts'));self.assertFalse(store.get_setting('animations'));self.assertFalse(store.get_setting('topmost'))
        self.assertIsNone(store.get_setting('location_profile'))
        self.assertTrue(all(t['schedule']['timezone']=='Asia/Kathmandu' for t in store.tasks()))
        now=datetime(2026,10,18,20,tzinfo=timezone.utc)
        self.assertEqual(today_service.snapshot(now)['date'],'2026-10-19')
        self.assertEqual(agenda_service.snapshot(now)['date'],'2026-10-20')
        preferences.bootstrap('America/New_York');self.assertEqual(store.timezone_name(),'Asia/Kathmandu')

    def test_timezone_changes_preserve_existing_user_schedules(self):
        preferences.bootstrap('UTC')
        task=new_task('Своя задача','reminder',{'type':'daily','time':'12:05','timezone':'Europe/Berlin'},enabled=False)
        store.save_task(task);preferences.complete('America/New_York')
        self.assertEqual(next(t for t in store.tasks() if t['id']==task['id']),task)
        preferences.set_timezone('Asia/Tokyo');self.assertEqual(store.timezone_name(),'Asia/Tokyo')
        self.assertEqual(next(t for t in store.tasks() if t['id']==task['id']),task)

    def test_invalid_timezone_does_not_partially_save(self):
        before=store.get_settings();revision=store.revision()
        with self.assertRaises((KeyError,ValueError)):preferences.complete('Invalid/Zone',False,False)
        self.assertEqual(store.get_settings(),before);self.assertEqual(store.revision(),revision)
        preferences.bootstrap('Windows timezone unavailable');self.assertEqual(store.timezone_name(),'UTC')

    def test_profiles_do_not_share_data_or_preferences(self):
        preferences.bootstrap('Europe/Berlin');preferences.complete('Europe/Berlin')
        store.publish('Только первый профиль','Содержимое');projects.create('Проект первого профиля')
        learning.save_progress('diagnostic',answer='SELECT first_profile;')
        second=Path(self.temp.name)/'Другой профиль'
        with patch.object(store,'HOME',second):
            store.initialize();preferences.bootstrap('Asia/Tokyo')
            self.assertEqual(store.events(),[]);self.assertEqual(projects.summaries(),[]);self.assertEqual(learning.overview(),{})
            self.assertEqual(store.timezone_name(),'Asia/Tokyo');self.assertFalse(any(t['enabled'] for t in store.tasks()))
        self.assertEqual(store.timezone_name(),'Europe/Berlin');self.assertEqual(len(store.events()),1)
        self.assertEqual(learning.progress('diagnostic')['answer'],'SELECT first_profile;')

    def _v7(self,name):
        task=next(t for t in store.tasks() if t['id']=='weather');task['name']=name;task['enabled']=True
        task['schedule']={'type':'daily','time':'06:40','days':[1,5],'timezone':'America/New_York'}
        store.save_task(task);store.publish('История','Сохранить','Погода','history')
        learning.save_progress('diagnostic',answer='SELECT saved_answer;')
        with store.connect() as db:
            db.execute("DELETE FROM settings WHERE key='onboarding_pending'");db.execute('PRAGMA user_version=7')
        store._initialized.discard(str(self.home.resolve()));return task

    def test_v7_renames_only_old_title_preserving_identity_schedule_history_and_backup(self):
        before=self._v7('Погода для поездок');events=store.events();store.initialize()
        after=next(t for t in store.tasks() if t['id']=='weather')
        self.assertEqual(after,dict(before,name=WEATHER_NAME));self.assertEqual(store.events(),events)
        self.assertEqual(learning.progress('diagnostic')['answer'],'SELECT saved_answer;')
        self.assertFalse(store.get_setting('onboarding_pending',False))
        backups=list((self.home/'backups').glob('inbox-v7-*.sqlite'));self.assertEqual(len(backups),1)
        with closing(sqlite3.connect(backups[0])) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute("SELECT name FROM tasks WHERE id='weather'").fetchone()[0],'Погода для поездок')

    def test_v7_custom_weather_title_is_preserved(self):
        before=self._v7('Погода для сада');store.initialize()
        self.assertEqual(next(t for t in store.tasks() if t['id']=='weather'),before)

    def test_release_copies_only_public_documents_and_rejects_profile_files(self):
        root=Path(__file__).resolve().parent;destination=Path(self.temp.name)/'Готовое приложение'
        docs=destination/'docs';docs.mkdir(parents=True);(docs/'HANDOFF.md').write_text('private',encoding='utf-8')
        copy_public_files(root,destination);verify_public_layout(destination)
        self.assertEqual({p.name for p in docs.iterdir()},set(PUBLIC_DOCS)|{'MANUAL.md'})
        combined='\n'.join(p.read_text(encoding='utf-8') for p in docs.iterdir())
        for personal in ('C:\\Users\\','D:\\GPT','Погода для поездок'):self.assertNotIn(personal,combined)
        (destination/'mail.local.json').write_text('{}')
        with self.assertRaises(RuntimeError):verify_public_layout(destination)
