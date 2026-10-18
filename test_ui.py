"""Qt integration checks in an isolated database; never changes Windows autostart."""
from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog,QPushButton,QLineEdit,QCheckBox,QSystemTrayIcon

import desktop_store as store
import learning_service as learning
import project_service as projects
from automation_models import new_task
from orbita_glass import Window,STYLE

app=QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False); app.setStyle('Fusion'); app.setStyleSheet(STYLE)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.object(store,'HOME',Path(self.temp.name)); self.patch.start()
        self.window=Window(); self.window.show(); QTest.qWait(100)

    def tearDown(self):
        self.window.engine.stop()
        self.window.quitting=True; self.window.timer.stop(); self.window.tray.hide()
        for child in self.window.findChildren(QDialog):child.close()
        for toast in self.window.toasts:toast.close()
        self.window.close(); self.window.deleteLater(); QTest.qWait(40)
        self.window.revision_reader.close()
        self.patch.stop(); self.temp.cleanup()

    def test_close_keeps_engine_alive_and_hidden_art_timers_stop(self):
        self.window.close(); QTest.qWait(100)
        if QSystemTrayIcon.isSystemTrayAvailable():self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window.engine.loop_thread.is_alive())
        self.assertTrue(all(not card.art.timer.isActive() for card in self.window.periods))
        self.window.reveal(); QTest.qWait(50)
        self.assertTrue(self.window.isVisible())

    def test_hidden_feed_is_deferred_and_catches_up_when_revealed(self):
        store.set_setting('dnd',True);self.window.tick();self.window.hide()
        with patch.object(self.window,'redraw',wraps=self.window.redraw) as redraw:
            store.publish('Пришло в фоне','Сохранённый результат');self.window.tick()
            self.assertEqual(redraw.call_count,0);self.assertTrue(self.window.feed_dirty)
            self.window.reveal();QTest.qWait(50)
            self.assertEqual(redraw.call_count,1);self.assertFalse(self.window.feed_dirty)
            self.assertIn('Пришло в фоне',str(self.window.fingerprint))

    def test_motion_setting_persists_and_new_scene_respects_it(self):
        art=self.window.periods[0].art;art.set_scene('sun');QTest.qWait(80)
        self.assertTrue(art.timer.isActive())
        self.window.settings();dialog=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        check=dialog.findChild(QCheckBox,'weatherAnimations');check.setChecked(False)
        save=next(b for b in dialog.findChildren(QPushButton) if b.text()=='Сохранить');save.click();QTest.qWait(40)
        self.assertFalse(store.get_setting('animations'));art.set_scene('snow')
        phase=art.phase;QTest.qWait(100);self.assertEqual(art.phase,phase);self.assertFalse(art.timer.isActive())
        store.set_setting('animations',True);self.window.tick();art.set_scene('rain')
        self.assertTrue(art.timer.isActive());self.window.showMinimized();QTest.qWait(50)
        self.assertFalse(art.timer.isActive());self.window.reveal();QTest.qWait(50);self.assertTrue(art.timer.isActive())

    def test_missing_forecast_is_static_and_large_task_list_expands_on_request(self):
        self.assertTrue(all(not c.art.timer.isActive() for c in self.window.periods))
        for i in range(43):store.save_task(new_task(f'Задача {i}','reminder',{'type':'daily','time':'19:00'},enabled=False))
        self.window.switch_page(1);QTest.qWait(60)
        def count():return sum(b.text()=='Запустить сейчас' for b in self.window.findChildren(QPushButton) if b.isVisible())
        self.assertEqual(count(),20)
        self.window.findChild(QPushButton,'moreTasks').click();QTest.qWait(60);self.assertEqual(count(),40)

    def test_projects_are_batched_and_search_is_debounced(self):
        for i in range(43):projects.create(f'Корпус {i}')
        self.window.switch_page(4);QTest.qWait(60)
        def count():return sum(b.text()=='Открыть проект' for b in self.window.findChildren(QPushButton) if b.isVisible())
        self.assertEqual(count(),20)
        self.window.projects_page.findChild(QPushButton,'moreProjects').click();QTest.qWait(60);self.assertEqual(count(),40)
        with patch('project_service.summaries',wraps=projects.summaries) as summaries:
            for text in ('К','Ко','Корпус 4'):self.window.projects_page.search.setText(text)
            self.assertEqual(summaries.call_count,0);QTest.qWait(260);self.assertEqual(summaries.call_count,1)
        self.assertEqual(self.window.projects_page.visible_count,20)

    def test_full_exit_keeps_unsaved_learning_answer_when_storage_fails(self):
        import sqlite3
        self.window.open_learning('diagnostic')
        dialog=self.window.learning_dialogs['diagnostic']
        dialog.answer.setPlainText('SELECT my_unsaved_answer;')
        with patch('learning_service.save_progress',side_effect=sqlite3.OperationalError('disk full')):
            self.window.quit_app()
        self.assertFalse(self.window.quitting)
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.dirty)
        self.assertEqual(dialog.answer.toPlainText(),'SELECT my_unsaved_answer;')

    def test_new_reminder_editor_saves_disabled(self):
        self.window.edit_task()
        dialog=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        name=dialog.findChild(QLineEdit); name.setText('Проверить модель')
        save=next(b for b in dialog.findChildren(QPushButton) if b.text()=='Сохранить')
        QTest.mouseClick(save,Qt.LeftButton); QTest.qWait(100)
        task=next(t for t in store.tasks() if t['kind']=='reminder')
        self.assertEqual(task['name'],'Проверить модель'); self.assertFalse(task['enabled'])
        self.window.switch_page(1); self.window.switch_page(2)

    def test_dnd_retains_notification_then_displays_it(self):
        store.set_setting('dnd',True); store.publish('Example','Body')
        self.window.tick(); self.assertFalse(self.window.toasts)
        self.assertEqual(len(store.pending_events()),1)
        store.set_setting('dnd',False); self.window.tick()
        self.assertTrue(self.window.toasts[0].isVisible())
        self.assertEqual(len(store.pending_events()),0)

    def test_notification_action_snoozes_real_run(self):
        task=new_task('Проверить деталь','reminder',{'type':'once','at':datetime.now(store.LOCAL).isoformat()},
                      {'body':'Измерить перед печатью'},enabled=True)
        store.save_task(task); self.window.engine.tick(); QTest.qWait(250); self.window.tick()
        row=next(e for e in store.events() if e['task_id']==task['id'])
        self.window.open_event(row)
        dialog=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        snooze=next(b for b in dialog.findChildren(QPushButton) if b.text()=='Отложить на 15 минут')
        QTest.mouseClick(snooze,Qt.LeftButton)
        self.assertEqual(store.events()[0]['action_state'],'snoozed')
        with store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM snoozes WHERE status='pending'").fetchone()[0],1)

    def test_learning_notification_opens_exact_lesson_from_hidden_panel(self):
        self.window.engine.run_now('learning-db2')
        for _ in range(60):
            if any(e['category']=='Обучение' for e in store.events()):break
            QTest.qWait(50)
        self.assertTrue(any(e['category']=='Обучение' for e in store.events()),store.runs('learning-db2'))
        row=next(e for e in store.events() if e['category']=='Обучение')
        self.window.hide(); self.window.tick(); QTest.qWait(500)
        toast=next(t for t in self.window.toasts if t.isVisible())
        open_button=next(b for b in toast.findChildren(QPushButton) if b.text()=='Открыть занятие')
        QTest.mouseClick(open_button,Qt.LeftButton); QTest.qWait(80)
        self.assertTrue(self.window.isVisible()); self.assertEqual(self.window.pages.currentIndex(),3)
        dialog=self.window.learning_dialogs['diagnostic']; self.assertTrue(dialog.isVisible())
        self.assertEqual(learning.progress('diagnostic')['state'],'in_progress')

    def test_learning_autosave_hints_and_solution_visibility(self):
        self.window.open_learning('joins'); dialog=self.window.learning_dialogs['joins']
        dialog.tabs.setCurrentIndex(1)
        dialog.answer.setPlainText('SELECT d.DOC_ID FROM ORB_DOCS d;')
        dialog.notes.setPlainText('Сравню число строк вручную.'); QTest.qWait(750)
        self.assertEqual(learning.progress('joins')['answer'],'SELECT d.DOC_ID FROM ORB_DOCS d;')
        self.assertFalse(dialog.solution_visible); self.assertEqual(dialog.solution_view.toPlainText(),'')
        dialog.hint(); self.assertEqual(learning.progress('joins')['hints_revealed'],1)
        dialog.solution(); self.assertTrue(learning.progress('joins')['solution_revealed'])
        dialog.close(); QTest.qWait(80)
        self.window.open_learning('joins'); reopened=self.window.learning_dialogs['joins']
        self.assertIn('ORB_DOCS',reopened.answer.toPlainText()); self.assertFalse(reopened.solution_visible)
        self.assertEqual(learning.progress('joins')['hints_revealed'],1)

    def test_learning_close_flushes_pending_answer(self):
        self.window.open_learning('nulls'); dialog=self.window.learning_dialogs['nulls']
        dialog.answer.setPlainText('SELECT 1; -- pending autosave')
        dialog.close(); QTest.qWait(40)
        self.assertEqual(learning.progress('nulls')['answer'],'SELECT 1; -- pending autosave')
        self.assertEqual(learning.progress('nulls')['state'],'in_progress')

    def test_diagnostic_self_assessment_completion_changes_plan(self):
        self.window.open_learning('diagnostic'); dialog=self.window.learning_dialogs['diagnostic']
        for combo in dialog.assessment_boxes.values():combo.setCurrentIndex(combo.findData('comfortable'))
        dialog.assessment_boxes['windows'].setCurrentIndex(dialog.assessment_boxes['windows'].findData('needs_work'))
        dialog.toggle_complete()
        self.assertEqual(learning.progress('diagnostic')['state'],'completed_user')
        self.assertEqual(learning.recommended_order()[0],'windows')

    def test_codex_question_preview_contains_latest_unsaved_answer(self):
        from PySide6.QtWidgets import QPlainTextEdit
        self.window.open_learning('dates'); dialog=self.window.learning_dialogs['dates']
        dialog.answer.setPlainText('SELECT VERSION_ID FROM ORB_VERSIONS;')
        dialog.question()
        preview=dialog.findChild(QPlainTextEdit,'codexQuestion')
        self.assertIsNotNone(preview); self.assertIn('SELECT VERSION_ID FROM ORB_VERSIONS;',preview.toPlainText())
        self.assertIn('Платформа: не указана',preview.toPlainText())

    def test_project_template_creation_autosave_and_close_preserve_notes(self):
        from PySide6.QtWidgets import QComboBox
        self.window.switch_page(4);self.window.projects_page.create_project()
        form=next(d for d in self.window.findChildren(QDialog) if d.windowTitle()=='Новый проект')
        form.findChild(QLineEdit,'newProjectTitle').setText('Крепление датчика')
        template=form.findChild(QComboBox,'newProjectTemplate');template.setCurrentIndex(template.findData('print'))
        create=next(b for b in form.findChildren(QPushButton) if b.text()=='Создать');QTest.mouseClick(create,Qt.LeftButton);QTest.qWait(70)
        record=projects.summaries()[0];self.assertEqual(record['total'],5)
        dialog=self.window.project_dialogs[record['id']];dialog.notes.setPlainText('Проверить зазор 0,3 мм');dialog.close();QTest.qWait(50)
        self.assertEqual(projects.get(record['id'])['notes'],'Проверить зазор 0,3 мм')
        self.window.open_project(record['id']);self.assertEqual(self.window.project_dialogs[record['id']].notes.toPlainText(),'Проверить зазор 0,3 мм')

    def test_project_checklist_updates_actual_next_step_without_completing_project(self):
        key=projects.create('ПК','pc');record=projects.get(key);self.window.open_project(key);dialog=self.window.project_dialogs[key]
        check=dialog.findChild(QCheckBox,'projectStep_'+record['steps'][0]['id']);QTest.mouseClick(check,Qt.LeftButton);QTest.qWait(60)
        self.assertEqual(projects.get(key)['steps'][0]['done'],1)
        self.assertIn(record['steps'][1]['title'],dialog.progress.text());self.assertEqual(projects.get(key)['state'],'active')

    def test_project_reminder_form_is_disabled_until_explicitly_enabled(self):
        key=projects.create('Дача');self.window.open_project(key);dialog=self.window.project_dialogs[key];dialog.reminder()
        form=next(d for d in dialog.findChildren(QDialog) if d.windowTitle()=='Напоминание о проекте')
        self.assertFalse(form.findChild(QCheckBox,'projectReminderEnabled').isChecked())
        save=next(b for b in form.findChildren(QPushButton) if b.text()=='Сохранить');QTest.mouseClick(save,Qt.LeftButton);QTest.qWait(40)
        task_id=projects.get(key)['reminder_task_id'];self.assertIsNotNone(task_id)
        self.assertFalse(next(t for t in store.tasks() if t['id']==task_id)['enabled'])

    def test_project_toast_opens_project_and_snooze_keeps_target(self):
        key=projects.create('Проект уведомления','pc')
        task_id=projects.save_reminder(key,(datetime.now(store.LOCAL)+timedelta(hours=1)).isoformat())
        self.window.engine.run_now(task_id)
        for _ in range(60):
            if any(e.get('target')=='project:'+key for e in store.events()):break
            QTest.qWait(50)
        self.window.hide();self.window.tick();QTest.qWait(500)
        toast=next(t for t in self.window.toasts if t.isVisible())
        open_button=next(b for b in toast.findChildren(QPushButton) if b.text()=='Открыть проект')
        QTest.mouseClick(open_button,Qt.LeftButton);QTest.qWait(60)
        self.assertTrue(self.window.isVisible());self.assertEqual(self.window.pages.currentIndex(),4)
        dialog=self.window.project_dialogs[key];self.assertTrue(dialog.notification_bar.isVisible())
        snooze=dialog.findChild(QPushButton,'projectReminderSnooze');QTest.mouseClick(snooze,Qt.LeftButton)
        with store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM snoozes WHERE status='pending'").fetchone()[0],1)
        self.assertEqual(projects.get(key)['steps'][0]['done'],0)

    def test_full_exit_preserves_project_draft_on_storage_error(self):
        import sqlite3
        key=projects.create('Не потерять');self.window.open_project(key);dialog=self.window.project_dialogs[key]
        dialog.notes.setPlainText('Несохранённый размер')
        with patch('project_service.save',side_effect=sqlite3.OperationalError('disk full')):self.window.quit_app()
        self.assertFalse(self.window.quitting);self.assertTrue(dialog.isVisible());self.assertTrue(dialog.dirty)
        self.assertEqual(dialog.notes.toPlainText(),'Несохранённый размер')

    def test_production_interface_has_no_demo_buttons_and_settings_are_global(self):
        names=[b.text() for b in self.window.findChildren(QPushButton)]
        self.assertNotIn('Тест уведомления',names);self.assertNotIn('Анимации',names)
        self.window.switch_page(4)
        settings=self.window.findChild(QPushButton,'openSettings')
        self.assertTrue(settings.isVisible());QTest.mouseClick(settings,Qt.LeftButton);QTest.qWait(50)
        self.assertTrue(any(d.isVisible() and d.windowTitle()=='Настройки Орбиты' for d in self.window.findChildren(QDialog)))

    def test_navigation_adapts_to_narrow_and_wide_windows(self):
        self.window.resize(550,700);QTest.qWait(60);self.assertEqual(self.window.navigation.columns,3)
        self.window.resize(760,700);QTest.qWait(60);self.assertEqual(self.window.navigation.columns,6)
        self.assertTrue(all(b.isVisible() for b in self.window.nav_buttons))

    def test_escape_preserves_pending_project_and_learning_text(self):
        key=projects.create('Escape');self.window.open_project(key);project=self.window.project_dialogs[key]
        project.notes.setPlainText('Pending notes');QTest.keyClick(project,Qt.Key_Escape);QTest.qWait(40)
        self.assertEqual(projects.get(key)['notes'],'Pending notes')
        self.window.open_learning('diagnostic');lesson=self.window.learning_dialogs['diagnostic']
        lesson.answer.setPlainText('SELECT pending_answer;');QTest.keyClick(lesson,Qt.Key_Escape);QTest.qWait(40)
        self.assertEqual(learning.progress('diagnostic')['answer'],'SELECT pending_answer;')

    def test_task_editor_keeps_save_visible_while_content_scrolls(self):
        from PySide6.QtWidgets import QScrollArea
        self.window.edit_task();dialog=next(d for d in self.window.findChildren(QDialog) if d.isVisible())
        scroll=dialog.findChild(QScrollArea,'taskEditorScroll');self.assertIsNotNone(scroll)
        dialog.resize(560,420);QTest.qWait(60)
        save=next(b for b in dialog.findChildren(QPushButton) if b.text()=='Сохранить')
        self.assertFalse(scroll.isAncestorOf(save));self.assertTrue(save.isVisible())

    def test_today_dashboard_opens_actual_project(self):
        key=projects.create('Next step','print');self.window.switch_page(0);QTest.qWait(40)
        button=next(b for b in self.window.today_overview.findChildren(QPushButton) if b.text()=='К проекту')
        QTest.mouseClick(button,Qt.LeftButton);QTest.qWait(40)
        self.assertIn(key,self.window.project_dialogs);self.assertTrue(self.window.project_dialogs[key].isVisible())


if __name__=='__main__':unittest.main()
