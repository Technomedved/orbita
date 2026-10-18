"""Useful daily focus using real reminders, projects and the scheduler read model."""
import json
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout
from ui_components import label,btn,GlassCard
from automation_models import parse_time
from zoneinfo import ZoneInfo


class TodayOverview(QWidget):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.fingerprint=None
        self.box=QVBoxLayout(self);self.box.setContentsMargins(0,0,0,0);self.box.setSpacing(10)
        self.setObjectName('todayOverview');self.setStyleSheet('#todayOverview {background:transparent;}')

    def refresh(self,model):
        local=lambda value:parse_time(value).astimezone(ZoneInfo(model['timezone']))
        fingerprint=json.dumps(model,ensure_ascii=False,sort_keys=True)
        if fingerprint==self.fingerprint:return
        self.fingerprint=fingerprint
        while self.box.count():
            item=self.box.takeAt(0)
            if item.widget():item.widget().deleteLater()
        card=GlassCard('#365566');box=QVBoxLayout(card);box.setContentsMargins(18,16,18,16);box.setSpacing(10)
        heading=QHBoxLayout();heading.addWidget(label('В фокусе сегодня',18,'#eef8ff',True));heading.addStretch()
        heading.addWidget(btn('+ Напоминание',self.owner.edit_task,True));box.addLayout(heading)
        counts=model['counts']
        line=label(f"Включено автоматизаций: {counts['enabled_tasks']} · проектов в работе: {counts['active_projects']} · ждут действия: {counts['pending_reminders']}",12)
        line.setWordWrap(True);box.addWidget(line)
        if model['paused']:box.addWidget(label('Автоматизации приостановлены. Расписание показано для справки.',12,'#efca91'))
        if model['reminders']:
            box.addWidget(label('Напоминания',13,'#b9eede',True))
            for row in model['reminders']:
                item=QHBoxLayout();text=row['title']
                if row['snoozed_until']:text+=' · отложено до '+local(row['snoozed_until']).strftime('%H:%M' if local(row['snoozed_until']).date().isoformat()==model['date'] else '%d.%m %H:%M')
                title=label(text,12,'#e3eefa');title.setWordWrap(True);item.addWidget(title,1)
                item.addWidget(btn('Открыть',lambda checked=False,r=row:self.owner.open_event(r)));box.addLayout(item)
        if model['upcoming']:
            box.addWidget(label('Запуски и расписание',13,'#b9eede',True))
            states={'queued':'в очереди','running':'выполняется','retry':'повтор','overdue':'ожидает запуска'}
            for row in model['upcoming']:
                text=local(row['at']).strftime('%H:%M' if local(row['at']).date().isoformat()==model['date'] else '%d.%m %H:%M')+' · '+row['name']
                if row['state'] in states:text+=' · '+states[row['state']]
                note=label(text,12);note.setWordWrap(True);box.addWidget(note)
        elif not model['reminders']:box.addWidget(label('На сегодня плановых запусков нет.',12))
        if model['projects']:
            box.addWidget(label('Следующие шаги проектов',13,'#b9eede',True))
            for row in model['projects']:
                item=QHBoxLayout();note=label(row['title']+'\n'+(row['next_step'] or 'Все шаги отмечены. Проверь результат проекта.'),12)
                note.setWordWrap(True);item.addWidget(note,1);item.addWidget(btn('К проекту',lambda checked=False,key=row['id']:self.owner.open_project(key)));box.addLayout(item)
        else:
            actions=QHBoxLayout();actions.addWidget(btn('+ Проект',self.owner.projects_page.create_project));actions.addStretch();box.addLayout(actions)
        self.box.addWidget(card)
