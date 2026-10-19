"""UI integration, synthetic profiles, no real registry or application restart."""
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox
from PySide6.QtTest import QTest
import desktop_store as store
import backup_service as backups
import project_service as projects
from orbita_glass import Window

app=QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)


class DataUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patch=patch.object(store,'HOME',self.root/'profile');self.patch.start()
        self.window=Window();self.window.engine.stop();self.window.show();self.window.open_data();QTest.qWait(30)
        self.dialog=self.window.data_dialog;self.folder=self.root/'copies';self.folder.mkdir();self.dialog.folder.setText(str(self.folder))

    def tearDown(self):
        self.window.engine.stop();self.window.quitting=True;self.window.timer.stop();self.window.tray.hide()
        for child in self.window.findChildren(QDialog):child.close()
        for toast in self.window.toasts:toast.close()
        try:self.window.revision_reader.close()
        except sqlite3.Error:pass
        self.window.close();self.window.deleteLater();QTest.qWait(30)
        self.patch.stop();self.temp.cleanup()

    def wait(self):
        deadline=time.monotonic()+15
        while self.dialog.busy and time.monotonic()<deadline:
            QTest.qWait(20);time.sleep(.01) # let Python workers run as a real event loop does
        self.assertFalse(self.dialog.busy)

    def test_backup_flushes_open_project_draft(self):
        key=projects.create('Before');self.window.open_project(key);editor=self.window.project_dialogs[key]
        editor.title.setText('Draft saved in snapshot');self.dialog.create();self.wait()
        path=next(self.folder.glob('*.orbita.zip'))
        with tempfile.TemporaryDirectory() as work:
            backups.validated_archive(path,work)
            db=sqlite3.connect(Path(work)/'inbox.sqlite')
            try:self.assertEqual(db.execute('SELECT title FROM projects').fetchone()[0],'Draft saved in snapshot')
            finally:db.close()

    def test_failed_draft_save_does_not_create_copy(self):
        with patch.object(self.window,'flush_drafts',return_value=False):self.dialog.create()
        self.assertEqual(list(self.folder.glob('*')),[]);self.assertIn('не сохранены',self.dialog.message.text())

    def test_disabled_auto_backup_config_and_schedule_editor(self):
        self.assertTrue(self.dialog.save_config());task=next(t for t in store.tasks() if t['id']=='profile-backup')
        self.assertFalse(task['enabled']);self.assertEqual(task['config']['folder'],str(self.folder.resolve()))
        self.dialog.schedule();QTest.qWait(20)
        self.assertTrue(any(d.windowTitle()=='Настройка автоматизации' for d in self.dialog.findChildren(QDialog)))

    def test_backup_notification_opens_data_without_duplicate_dialogs(self):
        row={'id':store.publish('Copy','Saved'),'target':'data:backups'}
        existing=self.dialog;self.window.open_event(row);self.assertIs(self.window.data_dialog,existing)

    def test_worker_bridge_flushes_on_main_thread_and_propagates_failure(self):
        result=[]
        with patch.object(self.window,'flush_drafts',return_value=False) as flush:
            thread=threading.Thread(target=lambda:result.append(self.window.draft_bridge.wait()));thread.start()
            deadline=time.monotonic()+3
            while thread.is_alive() and time.monotonic()<deadline:QTest.qWait(15)
            thread.join(1);self.assertEqual(result,[False]);flush.assert_called_once()

    def test_restore_restarts_without_old_readers_and_defaults_to_pause(self):
        store.publish('Kept','Body');path=backups.create(store.HOME,self.folder);store.publish('Replaced','Body')
        self.assertTrue(self.dialog.pause.isChecked())
        with patch.object(QApplication,'exit') as exit_app:
            self.dialog.start_restore(path);self.wait()
            self.assertTrue(self.window.restart_requested);exit_app.assert_called_once_with(42)
        self.assertEqual(len(store.events()),1);self.assertTrue(store.get_setting('paused'))

    def test_restore_failure_resumes_original_profile(self):
        with patch('data_ui.backups.restore',side_effect=ValueError('Injected invalid archive')):
            self.dialog.start_restore(self.root/'missing.zip');self.wait();QTest.qWait(50)
        self.assertFalse(self.window.maintenance);self.assertFalse(self.window.restart_requested)
        self.assertIsInstance(self.window.revision_reader.value(),int);self.assertTrue(self.window.timer.isActive())

    def test_health_check_and_close_during_operation(self):
        self.dialog.check_database();self.dialog.close();self.assertTrue(self.dialog.isVisible());self.wait()
        self.assertEqual(self.dialog.checks,{'integrity':'ok','references':'ok'})
