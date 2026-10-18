"""Calendar-day planning projection. Viewing a plan never executes or delivers it."""
from datetime import datetime,timedelta,time
import json
from zoneinfo import ZoneInfo
import desktop_store as store
from automation_models import occurrences,parse_time

TERMINAL={'success','failed','skipped','cancelled'}


def event(event_id):
    with store.connect() as db:
        row=db.execute("SELECT * FROM events WHERE id=? AND category!='Демо'",(event_id,)).fetchone()
        return dict(row) if row else None


def snapshot(now=None,day_offset=1):
    if type(day_offset) is not int or not 0<=day_offset<=7:raise ValueError('Choose a day from today to a week ahead.')
    with store.connect() as db:
        db.execute('BEGIN')
        settings={r['key']:json.loads(r['value']) for r in db.execute("SELECT * FROM settings WHERE key IN ('location_profile','user_timezone','paused')")}
        zone=ZoneInfo(store.timezone_from_settings(settings))
        local=(now or datetime.now(zone)).astimezone(zone);day=local.date()+timedelta(days=day_offset)
        start=datetime.combine(day,time.min,zone).astimezone(store.LOCAL)
        end=datetime.combine(day+timedelta(days=1),time.min,zone).astimezone(store.LOCAL)
        tasks={r['id']:dict(r) for r in db.execute('SELECT * FROM tasks')}
        # Only active attempts and terminal slots that can overlap the day are needed.
        runs=[dict(r) for r in db.execute('''SELECT * FROM runs WHERE
            (scheduled_at>=? AND scheduled_at<?) OR (status IN ('queued','running','retry') AND retry_at>=? AND retry_at<?)''',
            (start.isoformat(),end.isoformat(),start.isoformat(),end.isoformat()))]
        actions=[dict(r) for r in db.execute('''SELECT e.*,s.due AS due FROM snoozes s JOIN events e ON e.id=s.event_id
            WHERE s.status='pending' AND e.action_state='snoozed' AND e.category!='Демо' AND s.due>=? AND s.due<?
            AND NOT EXISTS(SELECT 1 FROM events newer WHERE newer.root_id=e.root_id AND newer.id>e.id)''',(start.isoformat(),end.isoformat()))]
        projects={r['id']:dict(r) for r in db.execute('''SELECT p.*,
            (SELECT title FROM project_steps s WHERE s.project_id=p.id AND s.done=0 ORDER BY position,id LIMIT 1) AS next_step
            FROM projects p WHERE p.state='active' ''')}
    for task in tasks.values():
        task['schedule']=json.loads(task['schedule']);task['config']=json.loads(task['config']);task['enabled']=bool(task['enabled'])
    by_slot={(r['task_id'],r['slot']):r for r in runs};timeline=[];included=set();related=set()
    def add(task,at,state='scheduled',run=None):
        project_id=task['config'].get('project_id')
        if project_id and (project_id not in projects or projects[project_id]['reminder_task_id']!=task['id']):return
        key='task:'+task['id']+':'+(run['slot'] if run else at.isoformat())
        if key in included:return
        included.add(key)
        if project_id:related.add(project_id)
        timeline.append({'id':key,'source':'task','task_id':task['id'],'kind':task['kind'],'title':task['name'],
                         'body':task['config'].get('body','') if task['kind']=='reminder' else '',
                         'at':at.astimezone(zone).isoformat(),'state':state,'project_id':project_id,
                         'task_timezone':task['schedule'].get('timezone','Asia/Yekaterinburg')})
    for task in tasks.values():
        for at in occurrences(task,start,end):
            run=by_slot.get((task['id'],at.isoformat()))
            if run and run['status'] in TERMINAL:continue
            effective=parse_time(run['retry_at'] or run['scheduled_at']) if run else at
            if start<=effective<end:add(task,effective,run['status'] if run else 'scheduled',run)
    for run in runs:
        task=tasks.get(run['task_id'])
        if task and task['enabled'] and run['status'] in ('queued','running','retry'):
            at=parse_time(run['retry_at'] or run['scheduled_at'])
            if start<=at<end:add(task,at,run['status'],run)
    for event in actions:
        event_key='snooze:'+str(event['root_id'] or event['id'])
        if event_key in included:continue
        included.add(event_key)
        project_id=(event.get('target') or '').removeprefix('project:') if (event.get('target') or '').startswith('project:') else None
        if project_id and project_id not in projects:continue
        if project_id:related.add(project_id)
        timeline.append({'id':event_key,'source':'snooze',
                         'event_id':event['id'],'task_id':event['task_id'],'kind':'reminder','title':event['title'],
                         'body':event['body'],'at':parse_time(event['due']).astimezone(zone).isoformat(),
                         'state':'snoozed','project_id':project_id,'task_timezone':str(zone)})
    timeline.sort(key=lambda item:(parse_time(item['at']),item['id']))
    return {'version':1,'date':day.isoformat(),'timezone':str(zone),'day_offset':day_offset,
            'paused':bool(settings.get('paused',False)),
            'counts':{'events':len(timeline),'reminders':sum(i['kind']=='reminder' for i in timeline),'projects':len(related)},
            'timeline':timeline,'projects':[projects[key] for key in sorted(related)]}
