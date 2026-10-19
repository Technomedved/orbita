"""Real snapshot/restore/failure/concurrency tests in synthetic profiles only."""
from contextlib import closing
from datetime import datetime,timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
import backup_service as backups
import desktop_store as store
import health_service as health
from automation_engine import Engine,quiet_now
from automation_models import new_task
import learning_service as learning
import project_service as projects
from profile_access import access

ROOT=Path(__file__).resolve().parent


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'profile';self.copies=self.root/'copies';self.copies.mkdir()
        self.patch=patch.object(store,'HOME',self.home);self.patch.start();self.addCleanup(self.patch.stop)
        store.initialize()

    def backup(self,**kw):return backups.create(self.home,self.copies,**kw)

    def rewrite(self,path,change):
        with zipfile.ZipFile(path) as z:data={i.filename:z.read(i) for i in z.infolist()}
        change(data)
        target=self.copies/'changed.zip'
        with zipfile.ZipFile(target,'w') as z:
            for k,v in data.items():z.writestr(k,v)
        return target

    def test_complete_profile_restore_and_device_settings(self):
        project=projects.create('Synthetic project');learning.save_progress('diagnostic',answer='SELECT synthetic;',notes='Study notes')
        store.publish('Synthetic notification','Body',dedupe='one');store.set_setting('user_timezone','Europe/Berlin')
        task=new_task('Reminder','reminder',{'type':'daily','time':'19:00','timezone':'Europe/Berlin','days':[1,3]});task['enabled']=True;store.save_task(task)
        store.set_setting('window_geometry',[1,2,600,700]);store.set_setting('location_refresh_on_start',True)
        path=self.backup();metadata=backups.preview(path)
        self.assertEqual(metadata['counts']['projects'],1);self.assertEqual(metadata['counts']['learning_progress'],1)
        projects.create('Should disappear');store.set_setting('window_geometry',[5,6,610,710])
        result=backups.restore(self.home,path)
        self.assertTrue(Path(result['insurance']).is_file());self.assertTrue(store.get_setting('paused'))
        self.assertEqual(len(projects.summaries()),1);self.assertEqual(learning.progress('diagnostic')['answer'],'SELECT synthetic;')
        restored=next(t for t in store.tasks() if t['id']==task['id']);self.assertEqual(restored['schedule'],task['schedule']);self.assertTrue(restored['enabled'])
        self.assertEqual(store.get_setting('window_geometry'),[5,6,610,710]);self.assertFalse(store.get_setting('location_refresh_on_start'))
        self.assertTrue(all(e['delivered'] for e in store.events()))

    def test_receipts_and_completed_slots_survive_older_snapshot(self):
        now=datetime.now(store.LOCAL)
        task=new_task('Once','reminder',{'type':'once','at':(now-timedelta(minutes=1)).isoformat(),'timezone':'UTC'})
        task['enabled']=True;store.save_task(task);store.set_setting('paused',True);path=self.backup();store.set_setting('paused',False)
        engine=Engine(clock=lambda:now,inline=True);engine.tick();self.assertEqual(len(store.runs(task['id'])),1)
        store.publish('Later','Content',dedupe='later-publish')
        backups.restore(self.home,path,pause=False);Engine(clock=lambda:now,inline=True).tick()
        self.assertFalse(store.get_setting('paused'))
        self.assertEqual(len(store.runs(task['id'])),1);self.assertEqual(store.runs(task['id'])[0]['status'],'success')
        self.assertIsNone(store.publish('Later','Content',dedupe='later-publish'))

    def test_unsafe_broken_large_and_future_archives_do_not_change_data(self):
        store.publish('Keep','Body');path=self.backup();count=len(store.events())
        def future(data):
            manifest=json.loads(data['manifest.json']);manifest['format']=999;data['manifest.json']=json.dumps(manifest).encode()
        for change in [lambda d:d.update({'../escape':b'bad'}),lambda d:d.update({'inbox.sqlite':b'bad'}),future]:
            bad=self.rewrite(path,change)
            with self.assertRaises((ValueError,sqlite3.Error,zipfile.BadZipFile)):backups.restore(self.home,bad)
            self.assertEqual(len(store.events()),count);self.assertFalse((self.root/'escape').exists())
        broken=self.copies/'truncated.zip';broken.write_bytes(path.read_bytes()[:100])
        with self.assertRaises(zipfile.BadZipFile):backups.preview(broken)
        with patch.object(backups,'MAX_DATABASE',32),self.assertRaises(ValueError):backups.preview(path)

    def test_delivered_snooze_not_replayed_after_restore(self):
        now=datetime.now(store.LOCAL)
        task=new_task('Snooze','reminder',{'type':'once','at':(now-timedelta(minutes=1)).isoformat(),'timezone':'UTC'});task['enabled']=True;store.save_task(task)
        Engine(clock=lambda:now,inline=True).tick();event=store.events()[0]
        store.reminder_action(event['id'],'snooze',now);path=self.backup()
        store.deliver_snoozes(now+timedelta(minutes=16))
        backups.restore(self.home,path,pause=False)
        before=len(store.events());store.deliver_snoozes(now+timedelta(minutes=17))
        self.assertEqual(len(store.events()),before)

    def test_future_schema_and_executable_trigger_rejected(self):
        path=self.backup()
        with store.connect() as db:db.execute('PRAGMA user_version=999')
        with self.assertRaises(ValueError):self.backup()
        with store.connect() as db:
            db.execute('PRAGMA user_version=9');db.execute("CREATE TRIGGER dangerous AFTER INSERT ON events BEGIN DELETE FROM projects; END")
        with self.assertRaises(ValueError):self.backup()
        self.assertTrue(path.is_file())

    def test_disk_or_folder_failure_keeps_existing_copy(self):
        first=self.backup()
        with patch.object(backups,'validate_destination',side_effect=OSError(28,'Full')),self.assertRaises(OSError):self.backup()
        self.assertTrue(first.is_file());self.assertEqual(store.get_setting('backup_state')['state'],'error')
        with self.assertRaises(ValueError):backups.create(self.home,self.root/'missing')
        self.assertTrue(first.is_file())

    def test_failed_insurance_never_applies_archive(self):
        path=self.backup();store.publish('Keep current','Body')
        with patch.object(backups,'create',side_effect=PermissionError()),self.assertRaises(PermissionError):backups.restore(self.home,path)
        self.assertEqual(len(store.events()),1)

    def test_exception_after_apply_rolls_back(self):
        path=self.backup();store.publish('Keep after failure','Body')
        def fail(phase):
            if phase=='applied':raise OSError('Injected failure')
        with self.assertRaises(OSError):backups.restore(self.home,path,checkpoint=fail)
        self.assertEqual(len(store.events()),1);self.assertFalse((self.home/'.restore/journal.json').exists())

    def test_cleanup_failure_does_not_repeat_rollback_or_lose_new_writes(self):
        store.publish('Snapshot','Body');path=self.backup();store.publish('Current','Body')
        unlink=Path.unlink
        def locked(file,*args,**kwargs):
            if file.name=='journal.json' and file.parent.name=='.restore':raise PermissionError('Locked by scanner')
            return unlink(file,*args,**kwargs)
        for rollback in (False,True):
            before=len(store.events())
            def checkpoint(phase):
                if rollback and phase=='applied':raise OSError('Injected failure')
            with patch.object(Path,'unlink',new=locked):
                if rollback:
                    with self.assertRaises(OSError):backups.restore(self.home,path,checkpoint=checkpoint)
                    expected=before
                else:backups.restore(self.home,path);expected=1
                self.assertEqual(len(store.events()),expected)
                store.publish('After cleanup problem','Body')
                self.assertEqual(len(store.events()),expected+1)
            self.assertEqual(len(store.events()),expected+1)
            self.assertFalse((self.home/'.restore/journal.json').exists())

    def test_process_death_recovered_before_next_publisher(self):
        path=self.backup();store.publish('Keep through crash','Body')
        script="""import os,sys,desktop_store as s,backup_service as b
s.initialize()
def crash(phase):
    if phase==sys.argv[2]:os._exit(71)
b.restore(s.HOME,sys.argv[1],checkpoint=crash)
"""
        for phase in ('prepared','applying','applied'):
            r=subprocess.run([sys.executable,'-c',script,str(path),phase],cwd=ROOT,env=dict(os.environ,AUTOMATION_HOME=str(self.home)),timeout=30)
            self.assertEqual(r.returncode,71)
            self.assertTrue((self.home/'.restore/journal.json').exists())
            # Same path is recovered even if the Python store initialization cache is hot.
            self.assertEqual(len(store.events()),1);self.assertFalse((self.home/'.restore/journal.json').exists())

    def test_cross_process_publish_waits_for_exclusive_gate(self):
        ready=self.root/'started'
        script="import sys,pathlib,desktop_store as s;pathlib.Path(sys.argv[1]).write_text('ready');s.publish('Child','Body',dedupe='child')"
        with access(self.home,True):
            child=subprocess.Popen([sys.executable,'-c',script,str(ready)],cwd=ROOT,env=dict(os.environ,AUTOMATION_HOME=str(self.home)))
            deadline=time.monotonic()+5
            while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(ready.exists());time.sleep(.1);self.assertIsNone(child.poll())
        self.assertEqual(child.wait(15),0);self.assertEqual(len(store.events()),1)

    def test_snapshot_with_concurrent_writer_is_consistent(self):
        errors=[]
        def write():
            try:
                for i in range(30):store.publish('Synthetic '+str(i),'Body')
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=write);thread.start();path=self.backup();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertLessEqual(backups.preview(path)['counts']['events'],30)

    def test_retention_only_owns_recorded_valid_automatic_files(self):
        manual=self.backup();foreign=self.copies/'Orbita-auto-foreign.orbita.zip';foreign.write_bytes(manual.read_bytes())
        first=self.backup(automatic=True,keep=1);last=self.backup(automatic=True,keep=1)
        self.assertFalse(first.exists());self.assertTrue(last.exists());self.assertTrue(manual.exists());self.assertTrue(foreign.exists())
        with patch.object(backups,'preview',side_effect=ValueError('Failure')),self.assertRaises(ValueError):self.backup(automatic=True,keep=1)
        self.assertTrue(last.exists())

    def test_restore_disables_device_backup_path_only(self):
        task=next(t for t in store.tasks() if t['id']=='profile-backup');task['config']={'folder':str(self.copies),'keep':2};task['enabled']=True;store.save_task(task)
        path=self.backup();backups.restore(self.home,path)
        task=next(t for t in store.tasks() if t['id']=='profile-backup')
        self.assertFalse(task['enabled']);self.assertEqual(task['config']['folder'],'')

    def test_scheduled_backup_works_in_quiet_mode_and_deduplicates(self):
        task=next(t for t in store.tasks() if t['id']=='profile-backup');now=datetime.now(store.LOCAL)
        task['config']={'folder':str(self.copies),'keep':2};task['enabled']=True;task['schedule']={'type':'once','at':(now-timedelta(minutes=1)).isoformat(),'timezone':'UTC'};store.save_task(task)
        store.set_setting('dnd',True);self.assertTrue(quiet_now({'dnd':True},now))
        Engine(clock=lambda:now,inline=True).tick();Engine(clock=lambda:now,inline=True).tick()
        self.assertEqual(len(list(self.copies.glob('*.zip'))),1);self.assertEqual(store.runs(task['id'])[0]['status'],'success')

    def test_diagnostics_never_copy_paths_content_location_or_exception_text(self):
        secret='PERSONAL-SECRET-C:/Users/Someone/password=example'
        store.publish(secret,secret);projects.create(secret);learning.save_progress('diagnostic',answer=secret)
        store.set_setting('backup_state',{'state':'error','error':secret,'last_success':secret,'last_file':secret})
        model=health.snapshot({'running':True,'error':secret})
        text=json.dumps(health.diagnostic(model,health.integrity()))
        self.assertNotIn(secret,text);self.assertNotIn(str(self.home),text);self.assertIn('ExecutionError',text)

    def test_migration_eight_to_nine_has_checked_backup_and_disabled_template(self):
        store.set_setting('user_timezone','Europe/Berlin')
        with store.connect() as db:
            db.execute("DELETE FROM tasks WHERE id='profile-backup'");db.execute('DROP TABLE publication_receipts');db.execute('PRAGMA user_version=8')
        store._initialized.discard(str(self.home.resolve()));store.initialize()
        files=list((self.home/'backups').glob('inbox-v8-*.sqlite'));self.assertEqual(len(files),1)
        with closing(sqlite3.connect(files[0])) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertFalse(next(t for t in store.tasks() if t['id']=='profile-backup')['enabled'])
        self.assertEqual(next(t for t in store.tasks() if t['id']=='profile-backup')['schedule']['timezone'],'Europe/Berlin')
