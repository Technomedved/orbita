"""Glass project cards and editor; data and reminders belong to project_service."""
from datetime import datetime,timedelta
import sqlite3

from PySide6.QtCore import Qt,QTimer,QDateTime,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,
    QComboBox,QPlainTextEdit,QDialog,QTabWidget,QScrollArea,QCheckBox,QProgressBar,
    QMessageBox,QDateTimeEdit,QInputDialog)

import project_service as projects
import desktop_store as store
from automation_models import parse_time,schedule_text
from ui_components import GlassCard,label,btn,SaveGuardDialog
from ui_theme import STYLE


class ProjectsPage(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.fingerprint=None;self.visible_count=20
        self.setObjectName('projectsContent');self.setStyleSheet('#projectsContent {background:transparent;}')
        layout=QVBoxLayout(self);layout.setContentsMargins(0,2,6,12);layout.setSpacing(12)
        layout.addWidget(label('Проекты',24,'#f0f5ff',True))
        note=label('Компьютеры, 3D-печать, дача и личные планы — шаги и материалы в одном месте.',13)
        note.setWordWrap(True);layout.addWidget(note)
        controls=QHBoxLayout();controls.addWidget(btn('+ Проект',self.create_project,True))
        self.scope=QComboBox();self.scope.setObjectName('projectFilter')
        for key,title in [('current','Текущие'),('all','Все проекты'),('completed','Завершённые'),('archived','Архив')]:self.scope.addItem(title,key)
        controls.addWidget(self.scope);layout.addLayout(controls)
        self.search=QLineEdit();self.search.setObjectName('projectSearch');self.search.setPlaceholderText('Поиск по названию и заметкам')
        layout.addWidget(self.search)
        self.cards=QVBoxLayout();self.cards.setSpacing(12);layout.addLayout(self.cards);layout.addStretch()
        self.search_timer=QTimer(self);self.search_timer.setSingleShot(True);self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self.search_changed);self.scope.currentIndexChanged.connect(self.filter_changed)

    def search_changed(self):
        self.visible_count=20;self.search_timer.start()

    def filter_changed(self):
        self.visible_count=20;self.refresh()

    def more_projects(self):
        self.visible_count+=20;self.refresh()

    def refresh(self):
        self.search_timer.stop()
        rows=projects.summaries(self.search.text(),self.scope.currentData(),limit=self.visible_count+1)
        fingerprint=tuple((r['id'],r['updated'],r['total'],r['done'],r['next_step'],r['state']) for r in rows)
        if fingerprint==self.fingerprint:return
        self.fingerprint=fingerprint
        while self.cards.count():
            item=self.cards.takeAt(0)
            if item.widget():item.widget().deleteLater()
        if not rows:
            card=GlassCard();box=QVBoxLayout(card);box.setContentsMargins(20,20,20,20)
            text=label('Текущих проектов нет. Создай проект с чистого листа или по шаблону; завершённые доступны через фильтр.' if not self.search.text() and self.scope.currentData()=='current'
                       else 'По этим условиям проектов нет. Измени поиск или фильтр.',14)
            text.setWordWrap(True);box.addWidget(text);self.cards.addWidget(card)
        for record in rows[:self.visible_count]:
            card=GlassCard('#3d5069');box=QVBoxLayout(card);box.setContentsMargins(18,16,18,16);box.setSpacing(10)
            title=label(record['title'],18,'#edf5ff',True);title.setWordWrap(True);box.addWidget(title)
            box.addWidget(label(projects.CATEGORIES[record['category']]+' · '+projects.STATES[record['state']],12,'#a3eed8'))
            box.addWidget(label(f"Шаги: {record['done']} из {record['total']}",12))
            bar=QProgressBar();bar.setRange(0,max(1,record['total']));bar.setValue(record['done']);bar.setTextVisible(False);bar.setFixedHeight(7)
            bar.setStyleSheet('QProgressBar {border:none;background:#334157;border-radius:3px;} QProgressBar::chunk {background:#a3eed8;border-radius:3px;}')
            box.addWidget(bar)
            text=label('Следующий шаг: '+(record['next_step'] or 'добавь шаг или проверь результат'),13)
            text.setWordWrap(True);box.addWidget(text)
            if record['notes']:
                excerpt=label(record['notes'][:160].replace('\n',' '),12);excerpt.setWordWrap(True);box.addWidget(excerpt)
            box.addWidget(btn('Открыть проект',lambda checked=False,key=record['id']:self.owner.open_project(key)))
            self.cards.addWidget(card)
        if len(rows)>self.visible_count:
            more=btn('Показать ещё 20',self.more_projects);more.setObjectName('moreProjects');self.cards.addWidget(more)

    def create_project(self):
        win=self.owner.dialog('Новый проект',550);box=QVBoxLayout(win);form=QFormLayout()
        title=QLineEdit();title.setMaxLength(160);title.setObjectName('newProjectTitle');title.setPlaceholderText('Например: корпус для датчика')
        template=QComboBox();template.setObjectName('newProjectTemplate')
        for key,(name,_,_) in projects.TEMPLATES.items():template.addItem(name,key)
        category=QComboBox()
        for key,name in projects.CATEGORIES.items():category.addItem(name,key)
        template.currentIndexChanged.connect(lambda:category.setCurrentIndex(category.findData(projects.TEMPLATES[template.currentData()][1])))
        form.addRow('Название',title);form.addRow('Начать',template);form.addRow('Направление',category);box.addLayout(form)
        note=label('Шаблон добавит редактируемые шаги. Напоминания создаются отдельно, когда выберешь время.',12);note.setWordWrap(True);box.addWidget(note)
        error=label('',12,'#ffb8b8');error.setWordWrap(True);box.addWidget(error)
        def save():
            try:project_id=projects.create(title.text(),template.currentData(),category.currentData())
            except (ValueError,sqlite3.Error,OSError) as exc:error.setText(str(exc));return
            win.close();self.refresh();self.owner.open_project(project_id)
        box.addWidget(btn('Создать',save,True));box.addWidget(btn('Отмена',win.close));win.show();title.setFocus()


class ProjectDialog(SaveGuardDialog):
    def __init__(self,owner,project_id):
        super().__init__(owner);self.owner=owner;self.project_id=project_id;self.dirty=False
        self.record=projects.get(project_id);self.setWindowTitle('Проект · '+self.record['title']);self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(STYLE+'QDialog {background:#1c273c;}')
        area=owner.screen().availableGeometry();self.resize(min(850,area.width()-50),min(810,area.height()-55))
        root=QVBoxLayout(self);root.setContentsMargins(20,18,20,18);root.setSpacing(12)
        self.title=QLineEdit(self.record['title']);self.title.setMaxLength(160);self.title.setObjectName('projectTitle');root.addWidget(self.title)
        properties=QHBoxLayout();self.state=QComboBox();self.category=QComboBox()
        for key,name in projects.STATES.items():self.state.addItem(name,key)
        for key,name in projects.CATEGORIES.items():self.category.addItem(name,key)
        self.state.setCurrentIndex(self.state.findData(self.record['state']));self.category.setCurrentIndex(self.category.findData(self.record['category']))
        properties.addWidget(self.state);properties.addWidget(self.category);root.addLayout(properties)
        self.progress=label('',13,'#a3eed8');self.progress.setWordWrap(True);root.addWidget(self.progress)
        self.tabs=QTabWidget();self.tabs.setStyleSheet('QTabWidget::pane {border:none;} QTabBar::tab {background:#26344b;padding:10px 18px;border-radius:8px;margin-right:4px;} QTabBar::tab:selected {background:#3b5963;color:#c9f8eb;}')
        root.addWidget(self.tabs,1)
        steps_page=QWidget();steps_box=QVBoxLayout(steps_page);steps_box.setContentsMargins(0,8,0,0)
        add_row=QHBoxLayout();self.new_step=QLineEdit();self.new_step.setObjectName('newProjectStep');self.new_step.setMaxLength(300);self.new_step.setPlaceholderText('Что сделать следующим шагом?')
        add_row.addWidget(self.new_step);add_row.addWidget(btn('Добавить',self.add_step));steps_box.addLayout(add_row)
        self.new_step.returnPressed.connect(self.add_step)
        step_scroll=QScrollArea();step_scroll.setWidgetResizable(True);step_content=QWidget();self.steps_box=QVBoxLayout(step_content);self.steps_box.setContentsMargins(0,0,6,0);step_scroll.setWidget(step_content)
        steps_box.addWidget(step_scroll);self.tabs.addTab(steps_page,'Шаги')
        self.notes=QPlainTextEdit(self.record['notes']);self.notes.setObjectName('projectNotes');self.notes.setPlaceholderText('Размеры, решения, комплектующие, параметры печати, оставшиеся вопросы…')
        self.notes.setStyleSheet('QPlainTextEdit {background:#19253a;border:1px solid #41516c;border-radius:12px;padding:12px;}')
        self.tabs.addTab(self.notes,'Заметки')
        link_page=QWidget();link_box=QVBoxLayout(link_page);link_box.setContentsMargins(0,8,0,0)
        self.link_label=QLineEdit();self.link_label.setMaxLength(160);self.link_label.setPlaceholderText('Название: модель, инструкция, комплектующая…');self.link_label.setObjectName('projectLinkLabel')
        self.link_url=QLineEdit();self.link_url.setPlaceholderText('https://…');self.link_url.setObjectName('projectLinkUrl')
        link_box.addWidget(self.link_label);link_box.addWidget(self.link_url);link_box.addWidget(btn('Добавить ссылку',self.add_link))
        link_note=label('Ссылки открываются в браузере только по нажатию. Цены и содержимое сайтов здесь не отслеживаются.',12);link_note.setWordWrap(True);link_box.addWidget(link_note)
        link_scroll=QScrollArea();link_scroll.setWidgetResizable(True);link_content=QWidget();self.links_box=QVBoxLayout(link_content);self.links_box.setContentsMargins(0,0,6,0);link_scroll.setWidget(link_content);link_box.addWidget(link_scroll)
        self.tabs.addTab(link_page,'Ссылки')
        self.reminder_status=label('',12);self.reminder_status.setWordWrap(True);root.addWidget(self.reminder_status)
        self.notification=None;self.notification_bar=QWidget();notification_actions=QHBoxLayout(self.notification_bar);notification_actions.setContentsMargins(0,0,0,0)
        notification_actions.addWidget(label('Напоминание',12))
        done=btn('Выполнено',lambda:self.act_notification('done'));done.setObjectName('projectReminderDone');notification_actions.addWidget(done)
        snooze=btn('Отложить на 15 минут',lambda:self.act_notification('snooze'));snooze.setObjectName('projectReminderSnooze');notification_actions.addWidget(snooze)
        root.addWidget(self.notification_bar);self.notification_bar.hide()
        self.saved=label('Изменения сохраняются автоматически',11);self.saved.setWordWrap(True);root.addWidget(self.saved)
        actions=QHBoxLayout();actions.addWidget(btn('Напомнить',self.reminder));actions.addWidget(btn('Сохранить',self.flush,True));actions.addWidget(btn('Закрыть',self.close));root.addLayout(actions)
        self.debounce=QTimer(self);self.debounce.setSingleShot(True);self.debounce.timeout.connect(self.flush)
        self.title.textChanged.connect(self.changed);self.notes.textChanged.connect(self.changed);self.category.currentIndexChanged.connect(self.changed)
        self.state.currentIndexChanged.connect(self.changed)
        self.refresh_details()

    def changed(self):
        self.dirty=True;self.saved.setText('Есть изменения…');self.debounce.start(650)

    def show_notification(self,row):
        self.notification=row
        self.notification_bar.setVisible(bool(row.get('root_id') and row.get('action_state') in ('pending','snoozed')))

    def act_notification(self,action):
        if not self.notification or not self.flush():return
        try:store.reminder_action(self.notification['id'],action)
        except (sqlite3.Error,OSError) as exc:self.error(exc);return
        self.notification_bar.hide();self.owner.tick()

    def error(self,exc):
        self.saved.setText('Не сохранено: '+str(exc));return False

    def flush(self):
        if not self.dirty:return True
        try:projects.save(self.project_id,title=self.title.text(),category=self.category.currentData(),state=self.state.currentData(),notes=self.notes.toPlainText())
        except (ValueError,sqlite3.Error,OSError) as exc:return self.error(exc)
        self.dirty=False;self.debounce.stop();self.setWindowTitle('Проект · '+self.title.text().strip());self.saved.setText('Сохранено '+datetime.now(store.LOCAL).strftime('%H:%M:%S'))
        self.owner.projects_page.refresh();self.refresh_reminder();return True

    def refresh_reminder(self):
        record=projects.get(self.project_id);task_id=record['reminder_task_id']
        task=next((t for t in store.tasks() if t['id']==task_id),None)
        text='Напоминание ещё не настроено'
        if task:text=('Напоминание включено: ' if task['enabled'] else 'Напоминание выключено: ')+schedule_text(task)
        if record['state']!='active':text+='\nНа паузе, после завершения и в архиве напоминание выключается. При возвращении включи его отдельно.'
        self.reminder_status.setText(text)

    def refresh_details(self):
        self.record=projects.get(self.project_id)
        for layout in (self.steps_box,self.links_box):
            while layout.count():
                item=layout.takeAt(0)
                if item.widget():item.widget().deleteLater()
        steps=self.record['steps'];done=sum(bool(s['done']) for s in steps)
        next_step=next((s['title'] for s in steps if not s['done']),None)
        self.progress.setText(f'Шаги: {done} из {len(steps)}'+('\nДальше: '+next_step if next_step else '\nДобавь следующий шаг или отметь проект завершённым.'))
        if not steps:self.steps_box.addWidget(label('Добавь первый шаг — список можно менять по ходу работы.',13))
        for step in steps:
            card=GlassCard();box=QVBoxLayout(card);box.setContentsMargins(14,10,14,10)
            check=QCheckBox();check.setChecked(bool(step['done']));check.setObjectName('projectStep_'+step['id']);check.setAccessibleName(step['title']);check.setToolTip(step['title'])
            check.setStyleSheet('QCheckBox {padding:3px 0;}')
            step_row=QHBoxLayout();step_row.addWidget(check)
            step_title=label(step['title'],13,'#8293ab' if step['done'] else '#edf2ff');step_title.setWordWrap(True);step_row.addWidget(step_title,1);box.addLayout(step_row)
            check.toggled.connect(lambda value,key=step['id']:self.check_step(key,value))
            actions=QHBoxLayout();actions.addWidget(btn('Изменить',lambda checked=False,s=step:self.rename_step(s)))
            actions.addWidget(btn('Убрать',lambda checked=False,key=step['id']:self.remove_step(key)));actions.addStretch();box.addLayout(actions);self.steps_box.addWidget(card)
        self.steps_box.addStretch()
        for link in self.record['links']:
            card=GlassCard();box=QVBoxLayout(card);name=label(link['label'],14,'#eef4ff',True);name.setWordWrap(True);box.addWidget(name)
            url=label(link['url'],11);url.setWordWrap(True);box.addWidget(url)
            actions=QHBoxLayout();actions.addWidget(btn('Открыть в браузере',lambda checked=False,url=link['url']:self.open_link(url)))
            actions.addWidget(btn('Убрать',lambda checked=False,key=link['id']:self.remove_link(key)));box.addLayout(actions);self.links_box.addWidget(card)
        if not self.record['links']:self.links_box.addWidget(label('Добавь ссылки на модели, инструкции или выбранные товары.',13))
        self.links_box.addStretch();self.refresh_reminder()

    def mutate(self,action):
        if not self.flush():return False
        try:action()
        except (ValueError,sqlite3.Error,OSError) as exc:return self.error(exc)
        self.refresh_details();self.owner.projects_page.refresh();self.saved.setText('Сохранено');return True

    def add_step(self):
        if self.mutate(lambda:projects.add_step(self.project_id,self.new_step.text())):self.new_step.clear()

    def check_step(self,key,done):
        if not self.mutate(lambda:projects.edit_step(self.project_id,key,done=done)):self.refresh_details()

    def rename_step(self,step):
        text,ok=QInputDialog.getText(self,'Изменить шаг','Что нужно сделать?',text=step['title'])
        if ok:self.mutate(lambda:projects.edit_step(self.project_id,step['id'],title=text))

    def remove_step(self,key):
        if QMessageBox.question(self,'Убрать шаг','Убрать этот шаг из чек-листа?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.mutate(lambda:projects.remove_step(self.project_id,key))

    def add_link(self):
        if self.mutate(lambda:projects.add_link(self.project_id,self.link_label.text(),self.link_url.text())):
            self.link_label.clear();self.link_url.clear()

    def remove_link(self,key):
        if QMessageBox.question(self,'Убрать ссылку','Убрать ссылку из этого проекта?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:
            self.mutate(lambda:projects.remove_link(self.project_id,key))

    def open_link(self,url):
        try:url=projects.validate_url(url)
        except ValueError as exc:self.error(exc);return
        if not QDesktopServices.openUrl(QUrl(url)):self.error(ValueError('Не удалось открыть браузер. Скопируй адрес ссылки.'))

    def reminder(self):
        if not self.flush():return
        record=projects.get(self.project_id)
        if record['state']!='active':self.saved.setText('Чтобы настроить напоминание, верни проект в работу.');return
        task=next((t for t in store.tasks() if t['id']==record['reminder_task_id']),None)
        win=QDialog(self);win.setWindowTitle('Напоминание о проекте');win.resize(490,310);box=QVBoxLayout(win)
        from zoneinfo import ZoneInfo
        zone_name=task['schedule'].get('timezone',store.timezone_name()) if task else store.timezone_name();zone=ZoneInfo(zone_name)
        at=datetime.now(zone)+timedelta(hours=1)
        if task and task['schedule']['type']=='once' and parse_time(task['schedule']['at'])>datetime.now(store.LOCAL):at=parse_time(task['schedule']['at']).astimezone(zone)
        date=QDateTimeEdit(QDateTime.fromString(at.strftime('%Y-%m-%d %H:%M'),'yyyy-MM-dd HH:mm'));date.setCalendarPopup(True);date.setDisplayFormat('dd.MM.yyyy HH:mm');date.setObjectName('projectReminderDate')
        box.addWidget(label('Когда напомнить · '+zone_name,13));box.addWidget(date)
        enabled=QCheckBox('Включить напоминание');enabled.setObjectName('projectReminderEnabled');enabled.setChecked(bool(task and task['enabled']));box.addWidget(enabled)
        note=label('Откроет этот проект и подскажет следующий незавершённый шаг. Повторная настройка изменит существующее напоминание.',12);note.setWordWrap(True);box.addWidget(note)
        error=label('',12,'#ffb8b8');error.setWordWrap(True);box.addWidget(error)
        def save():
            try:
                from automation_models import wall_time
                wall=datetime.strptime(date.dateTime().toString('yyyy-MM-dd HH:mm'),'%Y-%m-%d %H:%M')
                stamp=wall_time(wall.date(),wall.strftime('%H:%M'),zone)
                if stamp is None:raise ValueError('Этот час отсутствует из-за перехода времени.')
                projects.save_reminder(self.project_id,stamp.isoformat(),enabled.isChecked(),zone_name)
            except (ValueError,sqlite3.Error,OSError) as exc:error.setText(str(exc));return
            win.close();self.refresh_reminder();self.owner.tick()
        box.addWidget(btn('Сохранить',save,True));box.addWidget(btn('Отмена',win.close));win.show()

    def closeEvent(self,event):
        if not self.flush():event.ignore();return
        self.owner.projects_page.refresh();event.accept()
