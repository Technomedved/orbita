"""Shared weather panels and the next-day planning screen, without running plans."""
from datetime import datetime,timedelta
import json
from zoneinfo import ZoneInfo
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout
from ui_components import label,btn,GlassCard
import desktop_store as store
import agenda_service
import weather_service


class WeatherPanel(QWidget):
    def __init__(self,owner,card_factory,day_offset=0):
        super().__init__();self.owner=owner;self.day_offset=day_offset;self.fingerprint=None
        self.setObjectName('weatherPanel'+str(day_offset));self.setStyleSheet('#'+self.objectName()+' {background:transparent;}')
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0);box.setSpacing(12)
        header=QHBoxLayout();self.heading=label('Погода',13);self.heading.setWordWrap(True);header.addWidget(self.heading,1)
        header.addWidget(btn('Местоположение',owner.configure_location));box.addLayout(header)
        row=QHBoxLayout();row.setSpacing(10);self.periods=[]
        for title,hour,tint in [('Утро','09:00','#655454'),('День','13:00','#365f6c'),('Вечер','17:00','#55466e')]:
            card=card_factory(title,hour,tint);self.periods.append(card);row.addWidget(card,1)
        box.addLayout(row);self.stamp=label('',11);self.stamp.setWordWrap(True);box.addWidget(self.stamp)
        actions=QHBoxLayout();self.update_button=btn('↻  Обновить',owner.fetch_weather,True)
        self.update_button.setToolTip('Обновить прогноз на сегодня и завтра одним запуском')
        actions.addWidget(self.update_button);actions.addStretch();box.addLayout(actions)

    def set_busy(self,busy,has_location):
        self.update_button.setDisabled(busy)
        self.update_button.setText('Получаю…' if busy else '↻  Обновить' if has_location else 'Выбрать место')

    def render(self,profile,zone,hours,cache,legacy,now,last_status=None):
        day=now.astimezone(zone).date()+timedelta(days=self.day_offset)
        snapshot=weather_service.select(cache,legacy,day,profile)
        stale=False
        try:stale=bool(snapshot and weather_service.is_stale(snapshot,now))
        except (ValueError,KeyError,TypeError):snapshot=None
        fingerprint=json.dumps([profile,str(day),hours,snapshot,stale,last_status],sort_keys=True)
        if fingerprint==self.fingerprint:return
        self.fingerprint=fingerprint;place=profile['name'] if profile else 'Место не выбрано'
        self.heading.setText(('Погода на завтра · ' if self.day_offset else 'Погода · ')+place)
        self.stamp.setStyleSheet('color:#a9b6cd;font-size:11px;')
        for card,hour in zip(self.periods,hours):card.hour_label.setText(f'{hour:02d}:00')
        if not profile:
            for card in self.periods:card.clear('Выбери местоположение')
            self.stamp.setText('Место ещё не выбрано. Разреши определение или найди город вручную.');return
        if not snapshot:
            for card in self.periods:card.clear('Ожидает прогноза на этот день')
            self.stamp.setText(f'Для выбранного места пока нет сохранённого прогноза на {day:%d.%m.%Y}. Нажми «Обновить».');return
        try:
            for card,hour in zip(self.periods,hours):
                try:card.apply(snapshot['hourly'],snapshot['date'],hour)
                except (ValueError,IndexError):card.clear('Этот час отсутствует в прогнозе')
            fetched=datetime.fromisoformat(snapshot['fetched']).astimezone(zone)
            state=('УСТАРЕЛ · ' if stale else '')+('НЕ ОБНОВЛЁН · ' if last_status in ('failed','retry') else '')
            self.stamp.setText(state+f'Прогноз на {day:%d.%m.%Y} · получен {fetched:%d.%m %H:%M} · Open-Meteo\n'
                               f'Время: {zone}. Часы карточек настраиваются в выборе места.')
            if state:self.stamp.setStyleSheet('color:#efca91;font-size:11px;')
        except (KeyError,ValueError,TypeError,IndexError):
            for card in self.periods:card.clear('Данные неполные')
            self.stamp.setText('Сохранённый прогноз неполный. Обнови данные.')


class TomorrowPage(QWidget):
    def __init__(self,owner,card_factory):
        super().__init__();self.owner=owner;self.fingerprint=None;self.model=None;self.visible_count=20
        self.setObjectName('tomorrowContent');self.setStyleSheet('#tomorrowContent {background:transparent;}')
        box=QVBoxLayout(self);box.setContentsMargins(0,2,6,8);box.setSpacing(14)
        box.addWidget(label('Завтра, с ясным планом',24,'#f0f5ff',True))
        self.date_label=label('',12);self.date_label.setWordWrap(True);box.addWidget(self.date_label)
        self.focus=QVBoxLayout();box.addLayout(self.focus)
        self.weather=WeatherPanel(owner,card_factory,1);box.addWidget(self.weather)
        box.addWidget(label('Лента на завтра',20,'#edf3ff',True))
        note=label('Это план по включённым расписаниям и отложенным напоминаниям. Результаты появятся после выполнения задач.',12)
        note.setWordWrap(True);box.addWidget(note)
        self.feed=QVBoxLayout();self.feed.setSpacing(10);box.addLayout(self.feed);box.addStretch()

    def clear(self,box):
        while box.count():
            item=box.takeAt(0)
            if item.widget():item.widget().deleteLater()

    def refresh(self,model,force=False):
        fingerprint=json.dumps(model,sort_keys=True,ensure_ascii=False)
        if not force and fingerprint==self.fingerprint:return
        if self.model and self.model['date']!=model['date']:self.visible_count=20
        self.model=model;self.fingerprint=fingerprint;self.clear(self.focus);self.clear(self.feed)
        day=datetime.fromisoformat(model['date']);week=['понедельник','вторник','среда','четверг','пятница','суббота','воскресенье']
        self.date_label.setText(f"{day:%d.%m.%Y} · {week[day.weekday()]} · {model['timezone']}")
        card=GlassCard('#365566');box=QVBoxLayout(card);box.setContentsMargins(18,16,18,16);box.setSpacing(12)
        heading=QHBoxLayout();heading.addWidget(label('В фокусе завтра',18,'#eef8ff',True));heading.addStretch()
        add=btn('+ Напоминание',lambda:self.owner.edit_task(day_offset=1),True);add.setObjectName('addTomorrowReminder');heading.addWidget(add);box.addLayout(heading)
        counts=model['counts'];stats=label(f"Событий в плане: {counts['events']} · напоминаний: {counts['reminders']} · проектов: {counts['projects']}",12)
        stats.setWordWrap(True);box.addWidget(stats)
        if model['paused']:
            note=label('Общая пауза включена: план показан для справки. Для выполнения задач нужно продолжить автоматизации.',12,'#efca91');note.setWordWrap(True);box.addWidget(note)
        if model['timeline']:
            first=model['timeline'][0];next_item=label('Первое в плане: '+datetime.fromisoformat(first['at']).strftime('%H:%M')+' · '+first['title'],13,'#c3f5e5')
            next_item.setWordWrap(True);box.addWidget(next_item)
        else:box.addWidget(label('План на завтра пока пуст. Можно добавить напоминание.',12))
        for project in model['projects'][:3]:
            row=QHBoxLayout();text=label(project['title']+'\n'+(project['next_step'] or 'Все шаги отмечены. Проверь результат проекта.'),12)
            text.setWordWrap(True);row.addWidget(text,1);row.addWidget(btn('К проекту',lambda checked=False,key=project['id']:self.owner.open_project(key)));box.addLayout(row)
        self.focus.addWidget(card)
        states={'scheduled':'Запланировано','snoozed':'Отложенное напоминание','retry':'Повтор попытки','queued':'В очереди','running':'Выполняется'}
        kinds={'weather':'Погода','reminder':'Напоминание','audit':'Аудит','learning':'Обучение'}
        for item in model['timeline'][:self.visible_count]:
            card=GlassCard('#3b4b60');box=QVBoxLayout(card);box.setContentsMargins(18,14,18,14);box.setSpacing(9)
            stamp=datetime.fromisoformat(item['at']).strftime('%H:%M')
            meta=label(stamp+' · '+kinds.get(item['kind'],'Задача')+' · '+states[item['state']],11,'#a3eed8');meta.setWordWrap(True);box.addWidget(meta)
            title=label(item['title'],16,'#edf3ff',True);title.setWordWrap(True);box.addWidget(title)
            if item['body']:
                body=label(item['body'][:240]+('…' if len(item['body'])>240 else ''),12);body.setWordWrap(True);box.addWidget(body)
            if item['task_timezone']!=model['timezone']:
                tz=label('Время показано в '+model['timezone']+' · пояс задачи: '+item['task_timezone'],11);tz.setWordWrap(True);box.addWidget(tz)
            actions=QHBoxLayout()
            actions.addWidget(btn('Открыть напоминание' if item['source']=='snooze' else 'Настроить',lambda checked=False,value=item:self.open_item(value)))
            if item['project_id']:actions.addWidget(btn('К проекту',lambda checked=False,key=item['project_id']:self.owner.open_project(key)))
            actions.addStretch();box.addLayout(actions);self.feed.addWidget(card)
        if not model['timeline']:self.feed.addWidget(label('На эту дату нет запланированных событий.',13))
        if len(model['timeline'])>self.visible_count:self.feed.addWidget(btn(f"Показать ещё · осталось {len(model['timeline'])-self.visible_count}",self.more))

    def open_item(self,item):
        if item['source']=='snooze':
            event=agenda_service.event(item['event_id'])
            if event:self.owner.open_event(event)
        else:
            task=next((t for t in store.tasks() if t['id']==item['task_id']),None)
            if task:self.owner.edit_task(task)

    def more(self):
        self.visible_count+=20;self.refresh(self.model,force=True)
