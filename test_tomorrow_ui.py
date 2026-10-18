"""Next-day navigation, editing, honest forecast dates and passive preview."""
from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QDateTimeEdit,QLineEdit,QCheckBox
import desktop_store as store
import location_service as location
from automation_models import new_task
from orbita_glass import Window
from ui_theme import install_theme
from test_tomorrow import CITY,sample_snapshot

app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False);install_theme(app)


class TomorrowUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.patch=patch.object(store,'HOME',Path(self.temp.name));self.patch.start()
        store.initialize();location.save(CITY);self.now=datetime.now(store.local_zone())
        self.window=Window();self.window.show();QTest.qWait(40)

    def tearDown(self):
        self.window.engine.stop();self.window.timer.stop();self.window.location_refresher.cancel()
        for dialog in self.window.findChildren(QDialog):dialog.close()
        for toast in self.window.toasts:toast.close()
        self.window.quitting=True;self.window.tray.hide();self.window.close();self.window.revision_reader.close();self.window.deleteLater();QTest.qWait(40)
        self.patch.stop();self.temp.cleanup()

    def task(self,name,offset=1):
        at=(self.now+timedelta(days=offset)).replace(hour=9,minute=0,second=0,microsecond=0)
        task=new_task(name,'reminder',{'type':'once','at':at.isoformat(),'timezone':store.timezone_name()},enabled=True)
        store.save_task(task);return task

    def test_navigation_opens_tomorrow_and_existing_routes_still_work(self):
        button=next(b for b in self.window.navigation.buttons if b.text()=='Завтра')
        QTest.mouseClick(button,Qt.LeftButton);self.assertEqual(self.window.pages.currentIndex(),5)
        self.assertTrue(button.property('active'));self.assertIn((self.now+timedelta(days=1)).strftime('%d.%m.%Y'),self.window.tomorrow_page.date_label.text())
        for name,index in [('Автоматизации',1),('Журнал',2),('Обучение',3),('Проекты',4),('Сегодня',0)]:
            QTest.mouseClick(next(b for b in self.window.navigation.buttons if b.text()==name),Qt.LeftButton)
            self.assertEqual(self.window.pages.currentIndex(),index)

    def test_view_is_passive_and_shows_only_appropriate_plans(self):
        self.task('Tomorrow real task');self.task('Day after tomorrow',2)
        before=store.revision();self.window.switch_page(5);QTest.qWait(30)
        self.assertEqual([row['title'] for row in self.window.tomorrow_page.model['timeline']],['Tomorrow real task'])
        self.assertEqual(store.revision(),before);self.assertFalse(store.events());self.assertFalse(store.runs())
        self.assertFalse(self.window.toasts)

    def test_add_reminder_defaults_to_tomorrow_and_saves_without_early_run(self):
        self.window.switch_page(5)
        QTest.mouseClick(self.window.tomorrow_page.findChild(QPushButton,'addTomorrowReminder'),Qt.LeftButton);QTest.qWait(30)
        dialog=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        date=dialog.findChild(QDateTimeEdit);self.assertEqual(date.dateTime().toString('yyyy-MM-dd'),(self.now+timedelta(days=1)).date().isoformat())
        dialog.findChild(QLineEdit).setText('Завтрашнее дело')
        enabled=next(c for c in dialog.findChildren(QCheckBox) if c.text()=='Включить автоматизацию')
        self.assertFalse(enabled.isChecked());enabled.setChecked(True)
        QTest.mouseClick(next(b for b in dialog.findChildren(QPushButton) if b.text()=='Сохранить'),Qt.LeftButton);QTest.qWait(40)
        self.window.refresh_tomorrow()
        self.assertIn('Завтрашнее дело',[r['title'] for r in self.window.tomorrow_page.model['timeline']]);self.assertEqual(store.events(),[])

    def test_forecast_panels_render_different_dates_and_temperatures(self):
        today=sample_snapshot(self.now.date(),10,CITY,self.now)
        tomorrow=sample_snapshot((self.now+timedelta(days=1)).date(),20,CITY,self.now)
        store.set_setting('weather_snapshot',today);store.set_setting('weather_forecasts',{today['date']:today,tomorrow['date']:tomorrow})
        self.window.tick();self.window.switch_page(5)
        self.assertEqual(self.window.periods[0].temperature.text(),'+10°')
        self.assertEqual(self.window.tomorrow_page.weather.periods[0].temperature.text(),'+20°')
        self.assertNotIn('УСТАРЕЛ',self.window.tomorrow_page.weather.stamp.text())
        self.assertIn((self.now+timedelta(days=1)).strftime('%d.%m.%Y'),self.window.tomorrow_page.weather.stamp.text())

    def test_today_only_cache_does_not_masquerade_as_tomorrow(self):
        today=sample_snapshot(self.now.date(),10,CITY,self.now);store.set_setting('weather_snapshot',today)
        self.window.tick();self.window.switch_page(5)
        self.assertEqual(self.window.periods[0].temperature.text(),'+10°')
        self.assertEqual(self.window.tomorrow_page.weather.periods[0].temperature.text(),'—°')
        self.assertIn('пока нет',self.window.tomorrow_page.weather.stamp.text())

    def test_future_entry_opens_the_original_task_editor(self):
        task=self.task('Подготовка к встрече');self.window.switch_page(5)
        item=self.window.tomorrow_page.model['timeline'][0];self.window.tomorrow_page.open_item(item)
        dialog=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        self.assertEqual(dialog.findChild(QLineEdit).text(),task['name'])
        self.assertFalse(any(b.text()=='Выполнено' for b in self.window.tomorrow_page.findChildren(QPushButton)))

    def test_hidden_tomorrow_weather_stops_animation(self):
        self.window.switch_page(5);QTest.qWait(30);self.window.hide();QTest.qWait(30)
        self.assertTrue(all(not card.art.timer.isActive() for card in self.window.tomorrow_page.weather.periods))

    def test_long_timeline_is_loaded_in_batches(self):
        for index in range(23):self.task('Item '+str(index))
        self.window.switch_page(5);page=self.window.tomorrow_page
        self.assertEqual(len(page.model['timeline']),23);self.assertEqual(page.visible_count,20)
        more=next(b for b in page.findChildren(QPushButton) if b.text().startswith('Показать ещё'))
        QTest.mouseClick(more,Qt.LeftButton);QTest.qWait(30);self.assertEqual(page.visible_count,40)
        self.assertFalse(any(b.text().startswith('Показать ещё') and b.isVisible() for b in page.findChildren(QPushButton)))
