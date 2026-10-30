"""Day-plan projections and two-day weather. All data/network are isolated."""
from datetime import datetime,timedelta,timezone,time
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
from zoneinfo import ZoneInfo
import desktop_store as store
import location_service as location
import agenda_service as agenda
import today_service
import weather_service
import weather
import project_service as projects
from automation_models import new_task,Result,parse_time
from automation_engine import Engine
from automation_handlers import weather_result

CITY=dict(name='Казань',latitude=55.79,longitude=49.12,timezone='Europe/Moscow',source='manual')


def sample_snapshot(day,temperature,place,now):
    hourly={'time':[f'{day}T{hour:02d}:00' for hour in range(24)]}
    for key,value in {'temperature_2m':temperature,'apparent_temperature':temperature-2,'relative_humidity_2m':75,
                      'precipitation_probability':10,'precipitation':0,'snowfall':0,'wind_speed_10m':2,
                      'wind_gusts_10m':4,'weather_code':3,'is_day':1}.items():hourly[key]=[value]*24
    return {'date':str(day),'fetched':now.isoformat(),'hourly':hourly,'location':place,'location_key':location.location_key(place)}


class TomorrowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'HOME',Path(self.temp.name));self.patch.start();store.initialize()
        location.save(CITY);self.zone=ZoneInfo(CITY['timezone']);self.now=datetime(2026,10,18,12,tzinfo=self.zone)
        self.day=(self.now+timedelta(days=1)).date()

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def task(self,name='Tomorrow',spec=None,enabled=True,now=None):
        at=datetime.combine(self.day,time(9),self.zone)
        task=new_task(name,'reminder',spec or {'type':'once','at':at.isoformat(),'timezone':str(self.zone)},
                      {'body':'Содержательное напоминание'},enabled=enabled,now=now or self.now-timedelta(days=1));store.save_task(task);return task

    def test_once_daily_weekly_and_disabled_are_filtered_by_target_day(self):
        self.task('Once');self.task('Daily',{'type':'daily','time':'10:00','days':list(range(7)),'timezone':str(self.zone)})
        self.task('Weekly',{'type':'weekly','time':'11:00','days':[0],'timezone':str(self.zone)})
        self.task('Tuesday',{'type':'weekly','time':'11:00','days':[1],'timezone':str(self.zone)})
        self.task('Disabled',enabled=False)
        data=agenda.snapshot(self.now)
        self.assertEqual([r['title'] for r in data['timeline']],['Once','Daily','Weekly'])
        self.assertEqual(data['counts']['reminders'],3);self.assertEqual(data['date'],'2026-10-19')

    def test_half_open_day_includes_midnight_and_excludes_following_midnight(self):
        start=datetime.combine(self.day,time.min,self.zone)
        for name,at in [('Start',start),('End',start+timedelta(days=1)),('Before',start-timedelta(seconds=1))]:
            self.task(name,{'type':'once','at':at.isoformat(),'timezone':'Europe/Moscow'})
        self.assertEqual([r['title'] for r in agenda.snapshot(self.now)['timeline']],['Start'])

    def test_plan_reads_do_not_create_runs_events_or_learning_progress(self):
        self.task();revision=store.revision()
        for _ in range(3):agenda.snapshot(self.now)
        self.assertEqual(store.revision(),revision);self.assertEqual(store.runs(),[]);self.assertEqual(store.events(),[])
        with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_progress').fetchone()[0],0)

    def test_timezone_is_selected_location_not_system_or_utc_date(self):
        place=dict(CITY,timezone='America/Los_Angeles');location.save(place)
        now=datetime(2026,10,19,2,tzinfo=timezone.utc)
        task=self.task('LA evening',{'type':'once','at':'2026-10-20T05:00:00+00:00','timezone':'UTC'})
        data=agenda.snapshot(now);self.assertEqual(data['date'],'2026-10-19')
        self.assertEqual(datetime.fromisoformat(data['timeline'][0]['at']).hour,22)

    def test_project_requires_a_reminder_on_the_day(self):
        # Validation and new_task creation must use the same clock as the day projection.
        with patch.object(projects,'datetime',wraps=datetime) as project_clock, \
                patch('automation_models.datetime',wraps=datetime) as model_clock:
            project_clock.now.return_value=model_clock.now.return_value=self.now.astimezone(store.LOCAL)
            undated=projects.create('Без даты','pc');due=projects.create('Завтрашняя печать','print')
            with self.assertRaisesRegex(ValueError,'будущее время'):
                projects.save_reminder(due,self.now.isoformat(),True,'Europe/Moscow')
            projects.save_reminder(due,datetime.combine(self.day,time(14),self.zone).isoformat(),True,'Europe/Moscow')
            data=agenda.snapshot(self.now);self.assertEqual([p['id'] for p in data['projects']],[due])
            self.assertIsNotNone(data['projects'][0]['next_step']);self.assertEqual(data['counts']['projects'],1)
            projects.save(due,state='archived');self.assertEqual(agenda.snapshot(self.now)['timeline'],[])

    def test_snooze_crossing_midnight_moves_focus_and_deduplicates(self):
        now=self.now.replace(hour=23,minute=50);task=self.task()
        engine=Engine(clock=lambda:now,inline=True);engine.run_now(task['id']);row=store.events()[0]
        store.reminder_action(row['id'],'snooze',now)
        self.assertEqual(today_service.snapshot(now)['counts']['pending_reminders'],0)
        data=agenda.snapshot(now);snoozes=[r for r in data['timeline'] if r['source']=='snooze']
        self.assertEqual(len(snoozes),1);self.assertEqual(datetime.fromisoformat(snoozes[0]['at']).strftime('%H:%M'),'00:05')
        before=store.revision();agenda.snapshot(now);self.assertEqual(before,store.revision())
        store.reminder_action(row['id'],'done',now);self.assertFalse(any(r['source']=='snooze' for r in agenda.snapshot(now)['timeline']))

    def test_retry_due_tomorrow_is_in_plan_without_executing(self):
        now=self.now.replace(hour=23,minute=59)
        task=self.task(spec={'type':'once','at':now.isoformat(),'timezone':'Europe/Moscow'})
        task['max_attempts']=2;task['retry_seconds']=600;store.save_task(task)
        def fail(*args):raise OSError('offline')
        Engine({'reminder':fail},clock=lambda:now,inline=True).tick()
        data=agenda.snapshot(now);self.assertEqual(len(data['timeline']),1)
        self.assertEqual(data['timeline'][0]['state'],'retry');self.assertEqual(store.runs(task['id'])[0]['attempts'],1)

    def test_terminal_future_slot_is_not_scheduled_again_in_preview(self):
        task=self.task();at=parse_time(task['schedule']['at'])
        with store.connect() as db:db.execute("INSERT INTO runs(task_id,slot,scheduled_at,status) VALUES(?,?,?,'success')",(task['id'],at.isoformat(),at.isoformat()))
        self.assertEqual(agenda.snapshot(self.now)['timeline'],[])

    def test_global_pause_keeps_plan_and_all_data_unchanged(self):
        self.task();store.set_setting('paused',True);before=store.revision()
        data=agenda.snapshot(self.now);self.assertTrue(data['paused']);self.assertEqual(data['counts']['events'],1)
        self.assertEqual(before,store.revision());self.assertFalse(store.runs())

    def test_fall_25_hour_day_can_contain_two_slots_of_one_utc_task(self):
        location.save(dict(CITY,timezone='America/New_York'))
        now=datetime(2026,10,31,12,tzinfo=ZoneInfo('America/New_York'))
        self.task(spec={'type':'daily','time':'04:30','days':list(range(7)),'timezone':'UTC'},now=now-timedelta(days=1))
        rows=agenda.snapshot(now)['timeline'];self.assertEqual(len(rows),2)
        self.assertEqual([datetime.fromisoformat(row['at']).hour for row in rows],[0,23]);self.assertNotEqual(rows[0]['id'],rows[1]['id'])

    def test_spring_missing_wall_hour_is_not_in_plan(self):
        location.save(dict(CITY,timezone='Europe/Berlin'))
        now=datetime(2027,3,27,12,tzinfo=ZoneInfo('Europe/Berlin'))
        self.task(spec={'type':'daily','time':'02:30','days':list(range(7)),'timezone':'Europe/Berlin'},now=now-timedelta(days=1))
        self.assertEqual(agenda.snapshot(now)['timeline'],[])

    def test_midnight_rolls_target_day_forward(self):
        before=self.now.replace(hour=23,minute=59);after=before+timedelta(minutes=2)
        self.assertEqual(agenda.snapshot(before)['date'],'2026-10-19');self.assertEqual(agenda.snapshot(after)['date'],'2026-10-20')

    def test_weather_cache_keeps_dates_distinct_and_does_not_relabel_today(self):
        today=sample_snapshot(self.now.date(),10,CITY,self.now);tomorrow=sample_snapshot(self.day,20,CITY,self.now)
        cache={today['date']:today,tomorrow['date']:tomorrow}
        self.assertEqual(weather_service.select(cache,today,self.day,CITY)['hourly']['temperature_2m'][9],20)
        self.assertIsNone(weather_service.select({},today,self.day,CITY))
        self.assertIsNone(weather_service.select(cache,None,self.day,dict(CITY,latitude=10)))
        next_day=self.now+timedelta(days=1)
        self.assertIs(weather_service.select(cache,today,next_day.date(),CITY),tomorrow)
        self.assertIsNone(weather_service.select(cache,today,next_day.date()+timedelta(days=1),CITY))

    def test_future_day_is_fresh_by_age_not_by_difference_from_today(self):
        snapshot=sample_snapshot(self.day,20,CITY,self.now)
        self.assertFalse(weather_service.is_stale(snapshot,self.now+timedelta(hours=1)))
        self.assertTrue(weather_service.is_stale(snapshot,self.now+timedelta(hours=7)))

    def test_one_fetch_returns_two_atomic_date_snapshots(self):
        first=sample_snapshot(self.now.date(),10,CITY,self.now);second=sample_snapshot(self.day,20,CITY,self.now)
        hourly={key:first['hourly'][key]+second['hourly'][key] for key in first['hourly']}
        with patch('weather.forecast',return_value=hourly) as fetch:
            result=weather_result({},self.now)
        fetch.assert_called_once();self.assertEqual(fetch.call_args.kwargs['end_day'],str(self.day))
        self.assertEqual(len(result.settings['weather_forecasts']),2)
        self.assertEqual(result.settings['weather_snapshot']['date'],str(self.now.date()))
        self.assertIn(str(self.day),result.body)

    def test_partial_second_day_failure_preserves_existing_cache(self):
        old=sample_snapshot(self.day,20,CITY,self.now);store.set_setting('weather_forecasts',{old['date']:old})
        first=sample_snapshot(self.now.date(),10,CITY,self.now)
        with patch('weather.forecast',return_value=first['hourly']):
            Engine(clock=lambda:self.now,inline=True).run_now('weather')
        self.assertEqual(store.get_setting('weather_forecasts'),{old['date']:old});self.assertEqual(store.events(),[])
        self.assertEqual(store.runs('weather')[0]['status'],'retry')

    def test_weather_epochs_preserve_fall_overlap_in_selected_zone(self):
        place=dict(CITY,timezone='Europe/Berlin')
        times=[datetime(2026,10,25,h,tzinfo=timezone.utc).timestamp() for h in (0,1,8)]
        payload={'hourly':dict(time=times,**{field:[10,20,30] for field in weather.FIELDS})}
        with patch('weather.urlopen',return_value=BytesIO(json.dumps(payload).encode())) as fetch:
            hourly=weather.forecast('2026-10-25',attempts=1,location=place)
        self.assertEqual(hourly['time'],['2026-10-25T02:00','2026-10-25T02:00','2026-10-25T09:00'])
        self.assertEqual(weather.period_index(hourly,'2026-10-25',2),0)
        query=parse_qs(urlparse(fetch.call_args.args[0]).query);self.assertEqual(query['timeformat'],['unixtime'])

    def test_half_hour_forecast_grid_chooses_nearest_and_keeps_real_timestamp(self):
        hourly={'time':['2026-10-19T08:30','2026-10-19T09:30','2026-10-19T13:30']}
        self.assertEqual(weather.period_index(hourly,'2026-10-19',9),0)
        self.assertEqual(weather.period_index(hourly,'2026-10-19',13),2)
