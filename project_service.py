"""Local project workflow. No Qt, browser, Windows or network dependencies."""
from datetime import datetime
import json
from urllib.parse import urlsplit
from uuid import uuid4

import desktop_store as store
from automation_models import new_task,parse_time

STATES={'active':'В работе','paused':'На паузе','completed':'Завершён','archived':'В архиве'}
CATEGORIES={'other':'Личный проект','pc':'Компьютеры','print':'3D-печать','dacha':'Дача'}
TEMPLATES={
    'empty':('С чистого листа','other',[]),
    'pc':('Сборка компьютера','pc',[
        'Записать задачи, бюджет и уже имеющиеся комплектующие',
        'Проверить совместимость процессора, платы, памяти и корпуса',
        'Выбрать питание и охлаждение с учётом размеров и разъёмов',
        'Сверить комплектность и собрать компьютер с кабель-менеджментом',
        'Проверить температуры и стабильность, сохранить результаты']),
    'print':('Проект 3D-печати','print',[
        'Записать назначение детали и измерить посадочные размеры',
        'Подготовить модель и проверить допуски',
        'Выбрать материал, ориентацию и профиль печати',
        'Напечатать пробный вариант и проверить посадку',
        'Внести правки и сохранить итоговую модель с параметрами']),
    'dacha':('Работы на даче','dacha',[
        'Описать результат и снять необходимые размеры',
        'Составить список материалов и инструмента',
        'Проверить наличие материалов и подходящую погоду',
        'Выполнить основной этап работ',
        'Проверить результат и записать оставшиеся вопросы']),
}


def _title(value,limit=160):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:
        raise ValueError(f'Нужно название от 1 до {limit} символов.')
    return value.strip()


def _row(db,project_id):
    row=db.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
    if row is None:raise ValueError('Проект не найден.')
    return dict(row)


def create(title,template='empty',category=None):
    title=_title(title)
    if template not in TEMPLATES:raise ValueError('Неизвестный шаблон.')
    _,default_category,steps=TEMPLATES[template]
    category=category or default_category
    if category not in CATEGORIES:raise ValueError('Неизвестное направление.')
    project_id=uuid4().hex; now=datetime.now(store.LOCAL).isoformat()
    with store.connect() as db:
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?,NULL)',
                   (project_id,title,category,'active','',now,now))
        db.executemany('INSERT INTO project_steps VALUES(?,?,?,?,?)',
                       [(uuid4().hex,project_id,text,0,index) for index,text in enumerate(steps)])
    return project_id


def get(project_id):
    with store.connect() as db:
        value=_row(db,project_id)
        value['steps']=[dict(r) for r in db.execute('SELECT * FROM project_steps WHERE project_id=? ORDER BY position,id',(project_id,))]
        value['links']=[dict(r) for r in db.execute('SELECT * FROM project_links WHERE project_id=? ORDER BY rowid',(project_id,))]
    return value


def summaries(search='',state='current',limit=None):
    query=search.strip().casefold();params=[];where=[]
    if state=='current':where.append("p.state IN ('active','paused')")
    elif state!='all':where.append('p.state=?');params.append(state)
    if query:where.append("instr(casefold(p.title || ' ' || p.notes),?)>0");params.append(query)
    suffix=(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY p.updated DESC,p.id'
    if limit is not None:
        if type(limit) is not int or limit<1:raise ValueError('Нужен положительный предел списка.')
        suffix+=' LIMIT ?';params.append(limit)
    with store.connect() as db:
        db.create_function('casefold',1,str.casefold,deterministic=True)
        return [dict(r) for r in db.execute('''SELECT p.*,
            (SELECT COUNT(*) FROM project_steps s WHERE s.project_id=p.id) AS total,
            (SELECT COUNT(*) FROM project_steps s WHERE s.project_id=p.id AND s.done=1) AS done,
            (SELECT title FROM project_steps s WHERE s.project_id=p.id AND s.done=0 ORDER BY position,id LIMIT 1) AS next_step
            FROM projects p'''+suffix,params)]


def _touch(db,project_id):
    db.execute('UPDATE projects SET updated=? WHERE id=?',(datetime.now(store.LOCAL).isoformat(),project_id))


def _cancel_reminder(db,task_id):
    if not task_id:return
    db.execute('UPDATE tasks SET enabled=0 WHERE id=?',(task_id,))
    db.execute("UPDATE runs SET status='cancelled',finished=?,lease_until=NULL,summary='Напоминание проекта отменено' WHERE task_id=? AND status IN ('queued','retry','running')",
               (datetime.now(store.LOCAL).isoformat(),task_id))
    db.execute("UPDATE snoozes SET status='cancelled' WHERE status='pending' AND event_id IN (SELECT id FROM events WHERE task_id=?)",(task_id,))
    db.execute("UPDATE events SET delivered=1,seen=1,action_state='cancelled' WHERE task_id=? AND action_state IN ('pending','snoozed')",(task_id,))


def save(project_id,**changes):
    if set(changes)-{'title','category','state','notes'}:raise ValueError('Неизвестное поле проекта.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE'); value=_row(db,project_id); old_state=value['state'];value.update(changes)
        value['title']=_title(value['title'])
        if value['category'] not in CATEGORIES or value['state'] not in STATES:raise ValueError('Неизвестное состояние проекта.')
        if not isinstance(value['notes'],str):raise ValueError('Заметки должны быть текстом.')
        db.execute('UPDATE projects SET title=?,category=?,state=?,notes=? WHERE id=?',
                   (value['title'],value['category'],value['state'],value['notes'],project_id))
        if value['state']!='active' and value['state']!=old_state:_cancel_reminder(db,value['reminder_task_id'])
        _touch(db,project_id)


def add_step(project_id,title):
    title=_title(title,300); step_id=uuid4().hex
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');_row(db,project_id)
        position=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM project_steps WHERE project_id=?',(project_id,)).fetchone()[0]
        db.execute('INSERT INTO project_steps VALUES(?,?,?,?,?)',(step_id,project_id,title,0,position));_touch(db,project_id)
    return step_id


def edit_step(project_id,step_id,title=None,done=None):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');_row(db,project_id)
        row=db.execute('SELECT * FROM project_steps WHERE id=? AND project_id=?',(step_id,project_id)).fetchone()
        if row is None:raise ValueError('Шаг не найден в этом проекте.')
        text=_title(title,300) if title is not None else row['title']
        if done is not None and type(done) is not bool:raise ValueError('Нужно состояние шага.')
        db.execute('UPDATE project_steps SET title=?,done=? WHERE id=?',(text,row['done'] if done is None else int(done),step_id))
        _touch(db,project_id)


def remove_step(project_id,step_id):
    with store.connect() as db:
        _row(db,project_id);db.execute('DELETE FROM project_steps WHERE id=? AND project_id=?',(step_id,project_id));_touch(db,project_id)


def validate_url(url):
    if not isinstance(url,str):raise ValueError('Нужна ссылка http:// или https://.')
    url=url.strip()
    if any(c.isspace() for c in url) or any(ord(c)<32 for c in url):raise ValueError('Убери пробелы из адреса.')
    try:
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Используй веб-ссылку http:// или https:// без пароля в адресе.')
        parsed.port
    except (ValueError,UnicodeError):raise ValueError('Нужна корректная ссылка http:// или https:// без данных входа.')
    return url


def add_link(project_id,label,url):
    label=_title(label);url=validate_url(url);link_id=uuid4().hex
    with store.connect() as db:
        _row(db,project_id)
        db.execute('INSERT OR IGNORE INTO project_links VALUES(?,?,?,?)',(link_id,project_id,label,url));_touch(db,project_id)
        return db.execute('SELECT id FROM project_links WHERE project_id=? AND url=?',(project_id,url)).fetchone()[0]


def remove_link(project_id,link_id):
    with store.connect() as db:
        _row(db,project_id);db.execute('DELETE FROM project_links WHERE id=? AND project_id=?',(link_id,project_id));_touch(db,project_id)


def save_reminder(project_id,at,enabled=False,timezone_name=None):
    scheduled=parse_time(at)
    timezone_name=timezone_name or store.timezone_name()
    if scheduled<=datetime.now(store.LOCAL):raise ValueError('Выбери будущее время.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');project=_row(db,project_id)
        if project['state']!='active':raise ValueError('Сначала верни проект в работу.')
        task_id=project['reminder_task_id'] or uuid4().hex
        _cancel_reminder(db,task_id)
        task=new_task('Проект: '+project['title'],'reminder',{'type':'once','at':scheduled.isoformat(),'timezone':timezone_name},
                      {'project_id':project_id},enabled=enabled)
        db.execute('''INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,enabled=excluded.enabled,schedule=excluded.schedule,config=excluded.config,
            policy=excluded.policy,grace_seconds=excluded.grace_seconds,max_attempts=excluded.max_attempts,retry_seconds=excluded.retry_seconds''',
            (task_id,task['name'],task['kind'],int(task['enabled']),json.dumps(task['schedule']),json.dumps(task['config']),
             task['policy'],task['grace_seconds'],task['max_attempts'],task['retry_seconds'],task['created']))
        db.execute('UPDATE projects SET reminder_task_id=? WHERE id=?',(task_id,project_id));_touch(db,project_id)
    return task_id


def reminder_is_current(db,task):
    project_id=task['config'].get('project_id')
    row=db.execute('SELECT state,reminder_task_id FROM projects WHERE id=?',(project_id,)).fetchone()
    return bool(row and row['state']=='active' and row['reminder_task_id']==task['id'])


def reminder_content(project_id):
    project=get(project_id)
    next_step=next((s['title'] for s in project['steps'] if not s['done']),None)
    body=('Следующий шаг: '+next_step if next_step else 'Незавершённых шагов нет. Проверь результат и дальнейшие планы.')
    return 'Проект: '+project['title'],body+'\nОткрой карточку проекта, чтобы продолжить. Шаги отмечаются в чек-листе.', 'project:'+project_id
