"""Location, IANA calendars, migration and race checks; no live device or network."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
from zoneinfo import ZoneInfo
import desktop_store as store
import location_service as location
from automation_models import new_task,latest_due,next_due,wall_time,Result,parse_time
from automation_engine import Engine,quiet_now
from automation_handlers import weather_result
import weather
import today_service

MOSCOW=dict(name='Москва',latitude=55.75,longitude=37.62,timezone='Europe/Moscow',source='manual')
BERLIN=dict(name='Берлин',latitude=52.52,longitude=13.41,timezone='Europe/Berlin',source='manual')


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.patch=patch.object(store,'HOME',self.home);self.patch.start();store.initialize()

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def test_fresh_profile_is_unset_and_all_templates_disabled(self):
        self.assertIsNone(location.current());self.assertFalse(store.get_setting('location_setup_complete',False))
        self.assertTrue(all(not t['enabled'] for t in store.tasks()));self.assertEqual(store.timezone_name(),'UTC')

    def test_ambiguous_city_results_keep_region_and_timezone(self):
        payload={'results':[dict(name='Александровка',latitude=52,longitude=42,timezone='Europe/Moscow',admin1='Область 1',country='Россия'),
                            dict(name='Александровка',latitude=54,longitude=40,timezone='Europe/Moscow',admin1='Область 2'),dict(name='broken')]}
        calls=[]
        result=location.search_cities('Александровка',lambda url:(calls.append(url) or payload))
        self.assertEqual(len(result),2);self.assertNotEqual(result[0]['region'],result[1]['region'])
        self.assertEqual(parse_qs(urlparse(calls[0]).query)['name'],['Александровка'])
        self.assertIsNone(location.current())

    def test_device_rounds_coordinates_before_request_and_uses_returned_zone(self):
        calls=[]
        result=location.from_device(55.755812,37.617143,35,lambda url:(calls.append(url) or {'timezone':'Europe/Moscow'}))
        query=parse_qs(urlparse(calls[0]).query)
        self.assertEqual(query['latitude'],['55.76']);self.assertEqual(query['longitude'],['37.62'])
        self.assertEqual(result['timezone'],'Europe/Moscow');self.assertEqual(result['accuracy_m'],35)
        self.assertEqual(result['source'],'device');self.assertIsNone(location.current())

    def test_bad_location_and_hours_do_not_write(self):
        before=store.revision()
        for bad in [dict(MOSCOW,latitude=float('nan')),dict(MOSCOW,longitude=181),dict(MOSCOW,timezone='Nowhere/Bad'),dict(MOSCOW,name='')]:
            with self.assertRaises(ValueError):location.save(bad)
        with self.assertRaises(ValueError):location.save(MOSCOW,[9,30,17])
        self.assertEqual(before,store.revision());self.assertIsNone(location.current())

    def test_saved_profile_and_hours_persist_without_opt_in(self):
        location.save(MOSCOW,[7,12,21]);store._initialized.discard(str(self.home.resolve()));store.initialize()
        self.assertEqual(location.current()['name'],'Москва');self.assertEqual(store.get_setting('weather_hours'),[7,12,21])
        self.assertFalse(store.get_setting('location_refresh_on_start'));self.assertTrue(store.get_setting('location_setup_complete'))

    def test_first_place_sets_unconfigured_templates_but_not_a_reminder(self):
        task=new_task('UTC appointment','reminder',{'type':'daily','time':'09:00'},enabled=False);store.save_task(task)
        location.save(BERLIN)
        tasks={t['id']:t for t in store.tasks()}
        self.assertEqual(tasks['learning-db2']['schedule']['timezone'],'Europe/Berlin')
        self.assertEqual(tasks['audit']['schedule']['timezone'],'Europe/Berlin')
        self.assertEqual(tasks[task['id']]['schedule']['timezone'],'UTC')
        self.assertTrue(all(not t['enabled'] for t in tasks.values()))

    def test_changing_place_does_not_shift_existing_reminder_or_enable_tasks(self):
        location.save(MOSCOW);task=new_task('Meeting','reminder',{'type':'daily','time':'09:00','timezone':'Europe/Moscow'},enabled=True);store.save_task(task)
        before=next(t for t in store.tasks() if t['id']==task['id']);location.save(BERLIN)
        after=next(t for t in store.tasks() if t['id']==task['id']);self.assertEqual(before,after)
        self.assertEqual(next(t for t in store.tasks() if t['id']=='weather')['schedule']['timezone'],'Europe/Berlin')

    def test_manual_choice_cannot_enable_automatic_device_access(self):
        location.save(MOSCOW,refresh_on_start=True);self.assertFalse(store.get_setting('location_refresh_on_start'))
        location.save(dict(MOSCOW,source='device'),refresh_on_start=True);self.assertTrue(store.get_setting('location_refresh_on_start'))
        location.save(BERLIN);self.assertFalse(store.get_setting('location_refresh_on_start'))

    def test_missing_location_handler_does_not_contact_weather(self):
        with patch('weather.forecast') as fetch:
            with self.assertRaises(ValueError):weather_result({},datetime.now(store.LOCAL))
        fetch.assert_not_called()

    def test_forecast_request_contains_selected_coordinates_and_timezone(self):
        payload={'hourly':dict(time=['2026-10-18T09:00'],**{field:[1] for field in weather.FIELDS})}
        from io import BytesIO
        with patch('weather.urlopen',return_value=BytesIO(json.dumps(payload).encode())) as get:
            weather.forecast('2026-10-18',location=BERLIN)
        query=parse_qs(urlparse(get.call_args.args[0]).query)
        self.assertEqual(query['latitude'],['52.52']);self.assertEqual(query['timezone'],['Europe/Berlin'])

    def test_weather_uses_selected_calendar_day_across_midnight(self):
        tokyo=dict(MOSCOW,timezone='Asia/Tokyo');location.save(tokyo)
        now=datetime(2026,10,18,23,tzinfo=timezone.utc)
        with patch('weather.forecast',return_value={'time':['2026-10-19T09:00','2026-10-20T09:00']}) as fetch,patch('weather.render',return_value='body'):
            result=weather_result({},now)
        self.assertEqual(fetch.call_args.args[0],'2026-10-19');self.assertEqual(result.settings['weather_snapshot']['date'],'2026-10-19')

    def test_old_weather_response_is_cancelled_after_place_changes(self):
        location.save(MOSCOW);now=datetime.now(store.LOCAL)
        def handler(task,at):
            snapshot={'location_key':location.location_key(MOSCOW)};location.save(BERLIN)
            return Result('Old forecast','Body','Погода',settings={'weather_snapshot':snapshot})
        engine=Engine({'weather':handler},clock=lambda:now,inline=True);run=engine.run_now('weather')
        self.assertEqual(store.runs('weather')[0]['status'],'cancelled');self.assertEqual(store.events(),[])
        self.assertIsNone(store.get_setting('weather_snapshot'))

    def test_dashboard_and_quiet_hours_use_profile_zone(self):
        location.save(BERLIN);now=datetime(2026,10,18,22,30,tzinfo=timezone.utc)
        self.assertEqual(today_service.snapshot(now)['date'],'2026-10-19')
        self.assertTrue(quiet_now({'quiet_enabled':True,'quiet_start':'00:00','quiet_end':'01:00','timezone':'Europe/Berlin'},now))

    def test_v5_backup_preserves_data_and_legacy_slot_deduplication(self):
        now=datetime(2026,10,18,10,tzinfo=store.LOCAL)
        task=new_task('Old reminder','reminder',{'type':'daily','time':'10:00','timezone':'Asia/Yekaterinburg'},enabled=True,now=now-timedelta(days=1));store.save_task(task)
        Engine({'reminder':lambda *args:Result('Old','body','Напоминания')},clock=lambda:now,inline=True).tick()
        store.set_setting('custom_setting',{'preserved':True})
        with store.connect() as db:
            for row in db.execute('SELECT id,schedule FROM tasks').fetchall():
                spec=json.loads(row['schedule']);spec.pop('timezone',None);db.execute('UPDATE tasks SET schedule=? WHERE id=?',(json.dumps(spec),row['id']))
            db.execute('PRAGMA user_version=5')
        store._initialized.discard(str(self.home.resolve()));store.initialize()
        self.assertEqual(location.current()['source'],'legacy');self.assertEqual(store.get_setting('custom_setting'),{'preserved':True})
        self.assertFalse(store.get_setting('location_setup_complete',False));self.assertFalse(store.get_setting('location_refresh_on_start',False))
        Engine({'reminder':lambda *args:Result('Duplicate','body','Напоминания')},clock=lambda:now,inline=True).tick()
        self.assertEqual(len(store.events()),1);self.assertEqual(len(store.runs(task['id'])),1)
        copies=list((self.home/'backups').glob('inbox-v5-*.sqlite'));self.assertEqual(len(copies),1)
        with closing(sqlite3.connect(copies[0])) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)
            self.assertEqual(db.execute('SELECT title FROM events').fetchone()[0],'Old')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')


class CalendarTests(unittest.TestCase):
    def task(self,zone,time='09:00'):
        return new_task('Calendar','reminder',{'type':'daily','time':time,'days':list(range(7)),'timezone':zone},enabled=True,
                        now=datetime(2026,1,1,tzinfo=timezone.utc))

    def test_new_unbound_task_defaults_to_utc(self):self.assertEqual(new_task('New','reminder',{'type':'daily','time':'09:00'})['schedule']['timezone'],'UTC')

    def test_half_hour_and_quarter_hour_zones(self):
        now=datetime(2026,10,18,3,15,tzinfo=timezone.utc)
        self.assertEqual(latest_due(self.task('Asia/Kathmandu'),now),now)
        self.assertEqual(next_due(self.task('Asia/Kathmandu'),now),now+timedelta(days=1))

    def test_spring_gap_is_skipped(self):
        task=self.task('Europe/Berlin','02:30');now=datetime(2026,3,29,0,tzinfo=timezone.utc)
        due=next_due(task,now).astimezone(ZoneInfo('Europe/Berlin'))
        self.assertEqual((due.day,due.hour),(30,2))
        self.assertIsNone(wall_time(datetime(2026,3,29).date(),'02:30',ZoneInfo('Europe/Berlin')))

    def test_fall_overlap_chooses_first_occurrence(self):
        task=self.task('Europe/Berlin','02:30')
        first=latest_due(task,datetime(2026,10,25,0,45,tzinfo=timezone.utc))
        second=latest_due(task,datetime(2026,10,25,1,45,tzinfo=timezone.utc))
        self.assertEqual(first,second);self.assertEqual(first.astimezone(timezone.utc).hour,0)

    def test_weekday_uses_place_calendar_across_utc_date(self):
        task=self.task('America/Los_Angeles','23:30');task['schedule']['days']=[6]
        now=datetime(2026,10,19,6,30,tzinfo=timezone.utc)
        self.assertEqual(latest_due(task,now),now)
