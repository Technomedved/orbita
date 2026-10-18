"""Course workflow and persistence, independent of Qt and any SQL server."""
from datetime import datetime
import json

import desktop_store as store
from db2_content import COURSE_ID, CONTENT_VERSION, LESSONS, BY_ID, TOPICS, TABLES, fixture_sql

STATES={'not_started':'Не начато','in_progress':'В процессе','completed_user':'Завершено пользователем'}
LEVELS={'unknown':'Пока не оценивал','needs_work':'Нужно повторить','comfortable':'Понимаю уверенно'}


def lesson(lesson_id,course_id=COURSE_ID):
    if course_id!=COURSE_ID or lesson_id not in BY_ID:raise ValueError('Unknown lesson')
    return BY_ID[lesson_id]


def progress(lesson_id,course_id=COURSE_ID):
    lesson(lesson_id,course_id)
    with store.connect() as db:
        row=db.execute('SELECT * FROM learning_progress WHERE course_id=? AND lesson_id=?',(course_id,lesson_id)).fetchone()
    if row:
        result=dict(row); result['assessment']=json.loads(result['assessment'])
        result['solution_revealed']=bool(result['solution_revealed']); return result
    return dict(course_id=course_id,lesson_id=lesson_id,state='not_started',answer='',notes='',
                hints_revealed=0,solution_revealed=False,assessment={},updated=None,content_version=CONTENT_VERSION)


def save_progress(lesson_id,course_id=COURSE_ID,**changes):
    item=lesson(lesson_id,course_id)
    allowed={'state','answer','notes','hints_revealed','solution_revealed','assessment'}
    if set(changes)-allowed:raise ValueError('Unsupported progress field')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM learning_progress WHERE course_id=? AND lesson_id=?',(course_id,lesson_id)).fetchone()
        current=dict(row) if row else progress(lesson_id,course_id)
        if isinstance(current['assessment'],str):current['assessment']=json.loads(current['assessment'])
        current.update(changes)
        if current['state']=='not_started' and 'state' not in changes:
            current['state']='in_progress'
        if current['state'] not in STATES:raise ValueError('Invalid learning state')
        if not all(isinstance(current[key],str) for key in ('answer','notes')):raise ValueError('Answer and notes must be text')
        if not 0<=current['hints_revealed']<=len(item['hints']):raise ValueError('Invalid hint count')
        if any(key not in TOPICS or value not in LEVELS for key,value in current['assessment'].items()):
            raise ValueError('Invalid self-assessment')
        db.execute('''INSERT INTO learning_progress VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(course_id,lesson_id) DO UPDATE SET state=excluded.state,answer=excluded.answer,
            notes=excluded.notes,hints_revealed=excluded.hints_revealed,solution_revealed=excluded.solution_revealed,
            assessment=excluded.assessment,updated=excluded.updated,content_version=excluded.content_version''',
            (course_id,lesson_id,current['state'],current['answer'],current['notes'],current['hints_revealed'],
             int(bool(current['solution_revealed'])),json.dumps(current['assessment']),
             datetime.now(store.LOCAL).isoformat(),CONTENT_VERSION))


def profile():
    with store.connect() as db:
        row=db.execute('SELECT * FROM learning_profiles WHERE course_id=?',(COURSE_ID,)).fetchone()
    return dict(row) if row else dict(course_id=COURSE_ID,active_lesson=None,platform='',server_version='')


def set_profile(**changes):
    if set(changes)-{'active_lesson','platform','server_version'}:raise ValueError('Invalid profile field')
    if changes.get('active_lesson'):lesson(changes['active_lesson'])
    if 'platform' in changes and changes['platform'] not in ('','LUW','z/OS','IBM i'):raise ValueError('Unknown platform')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM learning_profiles WHERE course_id=?',(COURSE_ID,)).fetchone()
        value=dict(row) if row else dict(course_id=COURSE_ID,active_lesson=None,platform='',server_version='')
        value.update(changes)
        db.execute('INSERT OR REPLACE INTO learning_profiles VALUES(?,?,?,?)',
                   (COURSE_ID,value['active_lesson'],value['platform'],value['server_version']))


def start(lesson_id):
    record=progress(lesson_id)
    if record['state']=='not_started':save_progress(lesson_id,state='in_progress')
    set_profile(active_lesson=lesson_id)


def complete(lesson_id):
    save_progress(lesson_id,state='completed_user')
    if profile()['active_lesson']==lesson_id:set_profile(active_lesson=None)


def recommended_order():
    assessments=progress('diagnostic')['assessment']
    pending={item['id']:item for item in LESSONS if item['id']!='diagnostic' and progress(item['id'])['state']!='completed_user'}
    order=[]
    positions={item['id']:index for index,item in enumerate(LESSONS)}
    def rank(item):
        levels=[assessments.get(topic,'unknown') for topic in item['topics']]
        priority=min({'needs_work':0,'unknown':1,'comfortable':2}[level] for level in levels)
        return priority,positions[item['id']]
    while pending:
        candidates=[item for item in pending.values() if not any(prereq in pending for prereq in item['prerequisites'])]
        if not candidates:raise ValueError('Cyclic curriculum prerequisites')
        choice=min(candidates,key=rank); order.append(choice['id']); pending.pop(choice['id'])
    return order


def overview():
    with store.connect() as db:
        rows=[dict(r) for r in db.execute('SELECT lesson_id,state,assessment,hints_revealed,solution_revealed FROM learning_progress WHERE course_id=?',(COURSE_ID,))]
    return {row['lesson_id']:row for row in rows}


def current_lesson():
    active=profile()['active_lesson']
    if active in BY_ID and progress(active)['state']!='completed_user':return BY_ID[active]
    if progress('diagnostic')['state']!='completed_user':return BY_ID['diagnostic']
    order=recommended_order()
    return BY_ID[order[0]] if order else None


def reveal_hint(lesson_id):
    record=progress(lesson_id); count=min(record['hints_revealed']+1,len(lesson(lesson_id)['hints']))
    save_progress(lesson_id,hints_revealed=count)
    return count


def reveal_solution(lesson_id):
    save_progress(lesson_id,solution_revealed=True)


def codex_question(lesson_id,question):
    item=lesson(lesson_id); record=progress(lesson_id); server=profile()
    columns='\n'.join(name+'('+', '.join(c[0]+' '+c[1] for c in table['columns'])+')' for name,table in TABLES.items())
    data='\n'.join(name+': '+json.dumps(table['rows'],ensure_ascii=False) for name,table in TABLES.items())
    return (f"Помоги разобрать моё решение учебного задания IBM Db2 из Орбиты.\n"
            f"Занятие: {item['id']} · {item['title']} · материалы {CONTENT_VERSION}.\n"
            f"Платформа: {server['platform'] or 'не указана'}; версия: {server['server_version'] or 'не указана'}. "
            'Не предполагай LUW, z/OS или IBM i без основания.\n\n'
            f"Условие:\n{item['task']}\n\nСтруктура таблиц:\n{columns}\n\n"
            f"Вымышленные данные (значения по порядку колонок; null означает SQL NULL):\n{data}\n\n"
            f"Мой ответ:\n```sql\n{record['answer'] or '(пока нет ответа)'}\n```\n\n"
            f"Мои заметки:\n{record['notes'] or '(нет)'}\n\n"
            f"Мой вопрос:\n{question.strip() or 'Проверь логику и объясни возможные ошибки, сначала дай подсказку.'}\n\n"
            'Не считай запрос выполненным, если не выполнял его в настоящей Db2. '
            'Не подменяй Db2 исполнением в SQLite. Различай анализ логики и подтверждённый результат сервера. '
            'Рабочие данные и доступ к корпоративной системе здесь не используются.')


def export_fixture(path):
    from pathlib import Path
    Path(path).write_text(fixture_sql(),encoding='utf-8')
