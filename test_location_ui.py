"""Foreground location UX with fake native/network boundaries; no OS changes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QPushButton
import desktop_store as store
import location_service as location
from location_ui import DeviceLocator
from orbita_glass import Window
from ui_theme import install_theme

app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False);install_theme(app)
CITY=dict(name='Казань',latitude=55.79,longitude=49.12,timezone='Europe/Moscow',source='manual',region='Татарстан · Россия')


class LocationUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'HOME',Path(self.temp.name));self.patch.start()
        self.window=Window();self.window.show();QTest.qWait(30)

    def tearDown(self):
        self.window.engine.stop();self.window.timer.stop();self.window.location_refresher.cancel()
        for d in self.window.findChildren(QDialog):d.close()
        self.window.quitting=True;self.window.tray.hide();self.window.close();self.window.revision_reader.close();self.window.deleteLater();QTest.qWait(40)
        self.patch.stop();self.temp.cleanup()

    def wait_for(self,predicate):
        for _ in range(60):
            if predicate():return
            QTest.qWait(20)
        self.fail('UI did not reach expected state')

    def dialog(self):
        self.window.configure_location();QTest.qWait(30);return self.window.location_dialog

    def test_first_offer_does_not_access_device_until_consent_and_later_is_remembered(self):
        with patch.object(DeviceLocator,'request') as request:
            self.window.offer_location_setup();QTest.qWait(30)
            self.assertIsNotNone(self.window.welcome_dialog);self.assertIsNone(self.window.location_dialog)
            request.assert_not_called();self.window.welcome_dialog.reject();QTest.qWait(30)
            self.window.offer_location_setup();self.assertIsNone(self.window.location_dialog);self.assertIsNone(self.window.welcome_dialog);request.assert_not_called()
        self.assertIsNone(location.current());self.assertTrue(store.get_setting('location_setup_complete'))

    def test_city_search_preview_does_not_save_until_explicit_save(self):
        dialog=self.dialog();dialog.query.setText('Казань')
        with patch('location_service.search_cities',return_value=[CITY]):
            QTest.mouseClick(dialog.search,Qt.LeftButton);self.wait_for(lambda:dialog.results.count()==1)
        self.assertIsNone(location.current());dialog.results.setCurrentRow(0);self.assertTrue(dialog.save_button.isEnabled())
        dialog.hours[0].setValue(6)
        with patch.object(self.window.engine,'run_now') as run:
            QTest.mouseClick(dialog.save_button,Qt.LeftButton);QTest.qWait(30)
            run.assert_called_once_with('weather')
        self.assertEqual(location.current()['name'],'Казань');self.assertEqual(store.get_setting('weather_hours'),[6,13,17])
        self.assertIn('Казань',self.window.clock.text());self.assertIn('Europe/Moscow',self.window.clock.text())

    def test_welcome_saves_zone_without_weather_and_new_reminder_uses_it(self):
        self.window.offer_location_setup();dialog=self.window.welcome_dialog
        dialog.zone.setCurrentText('Asia/Tokyo');dialog.toasts.setChecked(False)
        with patch.object(DeviceLocator,'request') as request:
            dialog.accept();QTest.qWait(30);request.assert_not_called()
        self.assertFalse(store.get_setting('onboarding_pending'));self.assertIsNone(location.current())
        self.assertEqual(str(self.window.display_zone),'Asia/Tokyo');self.assertFalse(store.get_setting('toasts'))
        self.window.edit_task();form=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        next(b for b in form.findChildren(QPushButton) if b.text()=='Сохранить').click();QTest.qWait(30)
        task=next(t for t in store.tasks() if t['kind']=='reminder')
        self.assertEqual(task['schedule']['timezone'],'Asia/Tokyo');self.assertFalse(task['enabled'])
        self.assertEqual(store.runs(),[])

    def test_welcome_weather_opens_preview_without_requesting_device(self):
        self.window.offer_location_setup()
        with patch.object(DeviceLocator,'request') as request,patch('location_service.search_cities') as search:
            self.window.welcome_dialog.open_weather();QTest.qWait(30)
            self.assertIsNotNone(self.window.location_dialog);self.assertIsNone(location.current())
            request.assert_not_called();search.assert_not_called()

    def test_welcome_storage_failure_retains_editable_dialog(self):
        self.window.offer_location_setup();dialog=self.window.welcome_dialog
        with patch('preferences_service.complete',side_effect=OSError('disk full')):dialog.accept()
        self.assertTrue(dialog.isVisible());self.assertIn('не сохранены',dialog.error.text())
        self.assertTrue(store.get_setting('onboarding_pending'));self.assertTrue(dialog.zone.isEnabled())

    def test_denial_preserves_saved_place_and_enables_manual_search(self):
        location.save(CITY);dialog=self.dialog()
        with patch.object(dialog.locator,'request',side_effect=lambda:dialog.locator.failed.emit('Доступ запрещён системой')):
            QTest.mouseClick(dialog.detect,Qt.LeftButton)
        self.assertIn('запрещён',dialog.status.text());self.assertTrue(dialog.search.isEnabled())
        self.assertEqual(location.current()['name'],'Казань')

    def test_device_result_is_preview_only_with_opt_in_off(self):
        dialog=self.dialog();device=dict(CITY,source='device',accuracy_m=120)
        with patch('location_service.from_device',return_value=device),patch.object(dialog.locator,'request',side_effect=lambda:dialog.locator.found.emit(55.79,49.12,120)):
            QTest.mouseClick(dialog.detect,Qt.LeftButton);self.wait_for(lambda:dialog.save_button.isEnabled())
        self.assertEqual(dialog.profile['source'],'device');self.assertIsNone(location.current())
        self.assertTrue(dialog.refresh_on_start.isEnabled());self.assertFalse(dialog.refresh_on_start.isChecked())

    def test_late_network_result_does_not_replace_manual_selection(self):
        dialog=self.dialog();dialog.name.setText('Моё место');dialog.lat.setValue(10);dialog.lon.setValue(20);dialog.zone.setCurrentText('Asia/Kathmandu')
        old_token=dialog.generation;dialog.choose_coordinates()
        dialog.network_done(old_token,'device',dict(CITY,source='device'),'')
        self.assertEqual(dialog.profile['name'],'Моё место');self.assertEqual(dialog.profile['timezone'],'Asia/Kathmandu')
        self.assertIsNone(location.current())

    def test_network_failure_retains_place_and_retry_is_available(self):
        location.save(CITY);dialog=self.dialog();dialog.query.setText('Другой город')
        with patch('location_service.search_cities',side_effect=OSError('offline')):
            QTest.mouseClick(dialog.search,Qt.LeftButton);self.wait_for(lambda:dialog.search.isEnabled())
        self.assertIn('недоступен',dialog.status.text());self.assertEqual(location.current()['name'],'Казань')

    def test_forecast_from_different_place_clears_old_values(self):
        from datetime import datetime
        from test_tomorrow import sample_snapshot
        location.save(CITY);self.window.tick();now=datetime.now(store.local_zone())
        self.window.apply_snapshot(sample_snapshot(now.date(),99,CITY,now))
        self.assertEqual(self.window.periods[0].temperature.text(),'+99°')
        self.window.apply_snapshot({'location_key':'somewhere_else'})
        self.assertEqual(self.window.periods[0].temperature.text(),'—°');self.assertIn('пока нет',self.window.forecast_stamp.text())

    def test_os_access_error_is_readable_and_terminates_wait(self):
        from PySide6.QtPositioning import QGeoPositionInfoSource
        locator=DeviceLocator(self.window);messages=[];locator.failed.connect(messages.append);locator.active=True
        locator.source_error(QGeoPositionInfoSource.Error.AccessError)
        self.assertFalse(locator.active);self.assertIn('ОС',messages[0]);self.assertFalse(locator.deadline.isActive())

    def test_startup_refresh_is_opt_in_and_ignores_result_after_manual_change(self):
        refresher=self.window.location_refresher
        with patch.object(refresher.locator,'request') as request:
            refresher.start();request.assert_not_called()
            location.save(dict(CITY,source='device'),refresh_on_start=True);refresher.start();request.assert_called_once()
            location.save(dict(CITY,name='Другой город',latitude=50))
            refresher.resolved(0,'startup',dict(CITY,source='device'),'')
            self.assertEqual(location.current()['name'],'Другой город')

    def test_location_dialog_keeps_save_outside_scroll_on_small_window(self):
        from PySide6.QtWidgets import QScrollArea
        dialog=self.dialog();dialog.resize(560,480);QTest.qWait(30)
        scroll=dialog.findChild(QScrollArea);self.assertFalse(scroll.isAncestorOf(dialog.save_button));self.assertTrue(dialog.save_button.isVisible())

    def test_automatic_location_change_does_not_bypass_global_pause(self):
        location.save(CITY);store.set_setting('paused',True)
        with patch.object(self.window.engine,'run_now') as run:
            self.window.location_changed(automatic=True);run.assert_not_called()
        self.assertFalse(self.window.weather_refresh_pending);self.assertIn('Казань',self.window.clock.text())
