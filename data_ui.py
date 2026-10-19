"""Glass-styled data maintenance and health UI; operations run off the UI thread."""
import json
from pathlib import Path
import threading
from PySide6.QtCore import QObject,Signal,Slot,Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QScrollArea,QWidget,QLineEdit,
    QFileDialog,QProgressBar,QCheckBox,QSpinBox,QTextEdit,QMessageBox,QApplication)
from ui_components import GlassCard,label,btn
from ui_theme import STYLE
import desktop_store as store
import backup_service as backups
import health_service as health


def failure_text(exc):
    if isinstance(exc,PermissionError):return 'Нет доступа к файлу или папке. Проверьте права и выберите доступную папку.'
    if isinstance(exc,FileNotFoundError):return 'Файл или папка недоступны. Проверьте подключение диска и выбранный путь.'
    if isinstance(exc,TimeoutError):return 'Операция не завершилась за отведённое время. Проверьте занятые файлы и повторите.'
    if isinstance(exc,OSError):return 'Ошибка записи или чтения. Проверьте свободное место и доступность диска.'
    if isinstance(exc,ValueError):return 'Проверка не пройдена: '+str(exc)
    return 'Операция не выполнена. Рабочие данные защищены; проверьте файл и повторите. Тип: '+type(exc).__name__


class DraftBridge(QObject):
    request=Signal(object)
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.request.connect(self.flush)
    def flush(self,ticket):
        if not ticket['cancelled']:
            ticket['ok']=not getattr(self.owner,'maintenance',False) and self.owner.flush_drafts()
        ticket['event'].set()
    def wait(self):
        ticket={'event':threading.Event(),'ok':False,'cancelled':False}
        self.request.emit(ticket)
        if not ticket['event'].wait(20):ticket['cancelled']=True;return False
        return ticket['ok']


class Job(QObject):
    finished=Signal(object,object)


class DataDialog(QDialog):
    def __init__(self,owner):
        super().__init__(owner);self.owner=owner;self.busy=False;self.checks=None
        self.setObjectName('dataDialog');self.setWindowTitle('Данные и состояние Орбиты')
        self.setAttribute(Qt.WA_DeleteOnClose);self.setWindowModality(Qt.ApplicationModal)
        self.setStyleSheet(STYLE+'QDialog {background:#1c273c;}');self.resize(650,min(780,self.screen().availableGeometry().height()-60))
        root=QVBoxLayout(self);root.setContentsMargins(20,20,20,20)
        root.addWidget(label('Данные и состояние',23,'#c3f5e5',True))
        scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();self.body=QVBoxLayout(content);scroll.setWidget(content);root.addWidget(scroll,1)
        self.health_text=label('',13);self.health_text.setWordWrap(True);self.body.addWidget(self.health_text)
        row=QHBoxLayout();row.addWidget(btn('Обновить состояние',self.refresh));row.addWidget(btn('Проверить базу',self.check_database));self.body.addLayout(row)
        self.body.addWidget(btn('Диагностический отчёт…',self.report))
        path=label('Данные: '+str(store.HOME),12);path.setWordWrap(True);path.setTextInteractionFlags(Qt.TextSelectableByMouse);self.body.addWidget(path)
        self.body.addWidget(btn('Открыть папку данных',lambda:owner.open_folder(store.HOME)))
        card=GlassCard();box=QVBoxLayout(card);box.addWidget(label('Резервные копии',19,'#ecf5ff',True))
        task=next(t for t in store.tasks() if t['id']=='profile-backup')
        self.folder=QLineEdit(task['config'].get('folder',''));self.folder.setObjectName('backupFolder');self.folder.setPlaceholderText('Выберите папку для копий')
        box.addWidget(self.folder)
        row=QHBoxLayout();row.addWidget(btn('Выбрать папку',self.choose_folder));row.addWidget(btn('Открыть папку',self.open_folder));box.addLayout(row)
        self.backup_button=btn('Создать резервную копию',self.create,True);self.backup_button.setObjectName('createBackup');box.addWidget(self.backup_button)
        note=label(backups.EXCLUDED+'\nКопия содержит личные данные и не шифруется. Контрольная сумма проверяет целостность, а не автора файла. Максимум базы — 512 MiB.',12);note.setWordWrap(True);box.addWidget(note)
        self.keep=QSpinBox();self.keep.setRange(1,100);self.keep.setValue(task['config'].get('keep',7));self.keep.setPrefix('Хранить автоматических копий: ');box.addWidget(self.keep)
        box.addWidget(btn('Сохранить папку и лимит',self.save_config));box.addWidget(btn('Расписание автоматического резервирования…',self.schedule))
        self.body.addWidget(card)
        self.body.addWidget(btn('Выбрать копию для восстановления…',self.select_restore))
        self.pause=QCheckBox('После восстановления оставить плановые задачи на общей паузе');self.pause.setChecked(True);self.pause.setObjectName('restorePaused');self.body.addWidget(self.pause)
        text=label('Восстановление заменяет профиль целиком. Индивидуальные состояния обычных задач и их пояса сохраняются. Старые всплывающие сообщения не воспроизводятся; история остаётся в ленте. Расписание копий отключается до выбора папки. Геолокация при запуске требует повторного включения. Положение окна и закрепление остаются от этого устройства; Windows-автозапуск не меняется. Внешние ссылки проектов нужно проверить.',12);text.setWordWrap(True);self.body.addWidget(text)
        self.progress=QProgressBar();self.progress.setRange(0,0);self.progress.hide();root.addWidget(self.progress)
        self.message=label('',12,'#c3f5e5');self.message.setWordWrap(True);self.message.setObjectName('dataMessage');root.addWidget(self.message)
        root.addWidget(btn('Закрыть',self.close));self.refresh()

    def scheduler(self):
        engine=self.owner.engine
        running=bool(engine.loop_thread and engine.loop_thread.is_alive() and not engine.stop_event.is_set())
        backup_running=self.busy or any(r['status']=='running' and r['task_id']=='profile-backup' for r in store.runs(limit=20))
        return {'running':running,'error':engine.last_error,'backup_running':backup_running}

    def refresh(self):
        model=health.snapshot(self.scheduler());self.model=model
        stamp=lambda value:store.display_time(value).strftime('%d.%m.%Y %H:%M') if value else 'ещё не выполнялось'
        states={'not_started':'ещё не выполнялось','running':'выполняется','success':'успешно','error':'ошибка','interrupted':'предыдущая операция прервана'}
        weather='не настроена' if not model['weather']['configured'] else stamp(model['weather']['last_success'])
        self.health_text.setText(f"Орбита {model['version']} · схема {model['schema']}\nПланировщик: {'работает' if model['scheduler']['running'] else 'остановлен'} · {'общая пауза' if model['paused'] else 'плановые задачи разрешены'}\nВключено задач: {model['enabled_tasks']} · ожидают запуска: {model['waiting_runs']}\nПогода · последнее успешное обновление: {weather}\nРезервирование: {states.get(model['backup']['state'],'неизвестное состояние')}\nПоследняя успешная копия: {stamp(model['backup']['last_success'])}\nЗадач с последней ошибкой: {model['failed_latest_tasks']}")
        automatic='не настроено' if not model['backup']['automatic_configured'] else 'включено' if model['backup']['automatic_enabled'] else 'выключено'
        self.health_text.setText(self.health_text.text()+'\nАвтоматическое резервирование: '+automatic)
        if model['scheduler'].get('error'):self.health_text.setText(self.health_text.text()+'\nПланировщик сообщил об ошибке. Проверьте журнал и доступность папки данных.')
        if model['backup']['state'] in ('error','interrupted'):self.health_text.setText(self.health_text.text()+'\nПроверьте доступ и свободное место в папке копий, затем повторите резервирование.')

    def run_job(self,fn,done,text,failed=None):
        if self.busy:return
        self.busy=True;self.body.parentWidget().setEnabled(False);self.progress.show();self.message.setText(text)
        self.job=Job(self)
        self._done=done;self._failed=failed
        self.job.finished.connect(self.job_finished,Qt.QueuedConnection)
        job=self.job
        def work():
            try:value=fn();error=None
            except Exception as exc:value=None;error=exc
            job.finished.emit(value,error)
        self.thread=threading.Thread(target=work,name='orbita-profile-operation',daemon=False);self.thread.start()

    @Slot(object,object)
    def job_finished(self,value,error):
        done,failed=self._done,self._failed
        self.busy=False;self.body.parentWidget().setEnabled(True);self.progress.hide()
        if error:
            recovery_message=failed(error) if failed else None
            self.message.setText(recovery_message or failure_text(error))
        else:done(value)
        if not getattr(self.owner,'maintenance',False) and not self.busy:self.refresh()

    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Папка резервных копий',self.folder.text())
        if folder:self.folder.setText(folder)

    def open_folder(self):
        try:folder=backups.validate_destination(self.folder.text(),store.HOME)
        except Exception as exc:self.message.setText(failure_text(exc));return
        self.owner.open_folder(folder)

    def save_config(self):
        try:
            folder=backups.validate_destination(self.folder.text(),store.HOME)
            task=next(t for t in store.tasks() if t['id']=='profile-backup');task['config']={'folder':str(folder),'keep':self.keep.value()};store.save_task(task)
        except Exception as exc:self.message.setText(failure_text(exc));return False
        self.message.setText('Папка и лимит сохранены. Расписание включается отдельно.');self.refresh();return True

    def schedule(self):
        if self.save_config():self.owner.edit_task(next(t for t in store.tasks() if t['id']=='profile-backup'),parent=self)

    def create(self):
        if not self.owner.flush_drafts():self.message.setText('Черновики не сохранены. Копия не начата.');return
        folder=self.folder.text()
        self.run_job(lambda:backups.create(store.HOME,folder),lambda p:self.message.setText('Копия создана и проверена:\n'+str(p)),'Создаётся согласованный снимок и проверяется архив…')

    def check_database(self):
        def done(value):self.checks=value;self.message.setText('Проверка базы: '+json.dumps(value,ensure_ascii=False))
        self.run_job(health.integrity,done,'Проверяется целостность базы…')

    def report(self):
        self.refresh();payload=health.diagnostic(self.model,self.checks)
        win=QDialog(self);win.setWindowTitle('Просмотр диагностического отчёта');win.resize(600,500);win.setStyleSheet(self.styleSheet());box=QVBoxLayout(win)
        note=label('Технические сведения и количества объектов. Без базы, содержимого записей, точного места, персональных путей и журналов. Передача только вручную.',12);note.setWordWrap(True);box.addWidget(note)
        view=QTextEdit();view.setReadOnly(True);view.setPlainText(json.dumps(payload,ensure_ascii=False,indent=2));box.addWidget(view)
        def save():
            path,_=QFileDialog.getSaveFileName(win,'Сохранить отчёт','Orbita-diagnostics.json','JSON (*.json)')
            if path:
                try:Path(path).write_text(view.toPlainText(),encoding='utf-8')
                except OSError as exc:QMessageBox.warning(win,'Отчёт не сохранён',failure_text(exc));return
                win.accept()
        box.addWidget(btn('Сохранить файл…',save,True));box.addWidget(btn('Закрыть',win.reject));win.exec()

    def select_restore(self):
        path,_=QFileDialog.getOpenFileName(self,'Выберите копию','','Копии Орбиты (*.orbita.zip)')
        if path:self.run_job(lambda:backups.preview(path),lambda metadata:self.confirm_restore(path,metadata),'Проверяются архив, формат и база…')

    def confirm_restore(self,path,metadata):
        names={'projects':'Проекты','tasks':'Автоматизации','events':'События','runs':'Запуски','learning_progress':'Учебные записи','project_steps':'Шаги проектов','project_links':'Ссылки','snoozes':'Отложенные напоминания','learning_profiles':'Учебные профили','publication_receipts':'Ключи защиты публикаций от повторов'}
        summary='\n'.join(f'{names[k]}: {v}' for k,v in metadata['counts'].items())
        text=f"Копия от {metadata['created']}\nОрбита {metadata['app_version']} · схема {metadata['schema']}\n\n{summary}\n\nПрофиль будет заменён после создания проверенной страховочной копии. Для того же профиля сохраняется защита от уже обработанных на этом устройстве запусков и JSON-публикаций. Приложение перезапустится.\n"+('Плановые задачи останутся на общей паузе.' if self.pause.isChecked() else 'Плановые задачи применят сохранённые правила пропусков. Очередь и отложенные напоминания продолжатся.')
        if QMessageBox.question(self,'Восстановить профиль?',text,QMessageBox.Yes|QMessageBox.Cancel,QMessageBox.Cancel)==QMessageBox.Yes:self.start_restore(path)

    def start_restore(self,path):
        if not self.owner.flush_drafts():self.message.setText('Не удалось сохранить черновики. Восстановление не начато.');return
        # Close stale editors while still connected to the original profile.
        for dialog in list(self.owner.learning_dialogs.values())+list(self.owner.project_dialogs.values()):dialog.close()
        self.owner.maintenance=True;self.owner.timer.stop();self.owner.location_refresher.cancel()
        for toast in self.owner.toasts:toast.close()
        self.owner.toast_queue=[];self.owner.revision_reader.close()
        pause=self.pause.isChecked()
        def work():
            self.owner.engine.stop()
            if any(w.is_alive() for w in self.owner.engine.workers.values()) or (self.owner.engine.loop_thread and self.owner.engine.loop_thread.is_alive()):raise TimeoutError('Workers still active')
            return backups.restore(store.HOME,path,pause)
        def finished(value):
            self.owner.restart_requested=True;self.owner.quitting=True;self.owner.tray.hide();QApplication.instance().exit(42)
        def resume(error):
            try:
                store._initialized.discard(str(store.HOME.resolve()))
                self.owner.revision_reader=store.RevisionReader();self.owner.maintenance=False
                self.owner.engine.start();self.owner.timer.start(1300);self.owner.last_revision=-1;self.refresh()
            except Exception:
                self.owner.maintenance=True
                return 'Восстановление не завершено. Полностью выйдите через трей и запустите Орбиту для восстановления по журналу; задачи остановлены.'
        self.run_job(work,finished,'Останавливаются задачи, создаётся страховочная копия и восстанавливается профиль…',resume)

    def reject(self):
        if not self.busy:super().reject()

    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
