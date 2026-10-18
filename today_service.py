"""Read-only dashboard projection. JSON-compatible data, no Qt or Windows APIs."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo

import desktop_store as store
from automation_models import next_due,parse_time


def snapshot(now=None):
    with store.connect() as db:
        db.execute('BEGIN')
        tasks=[dict(r) for r in db.execute('SELECT * FROM tasks WHERE enabled=1')]
        settings={r['key']:json.loads(r['value']) for r in db.execute("SELECT * FROM settings WHERE key IN ('location_profile','user_timezone','paused')")}
        zone=ZoneInfo(store.timezone_from_settings(settings))
        now=(now or datetime.now(zone)).astimezone(zone)
        actions=[dict(r) for r in db.execute('''SELECT e.*,s.due AS snoozed_until
            FROM events e LEFT JOIN snoozes s ON s.event_id=e.id AND s.status='pending'
            WHERE e.category!='Демо' AND e.action_state IN ('pending','snoozed')
            AND NOT EXISTS (SELECT 1 FROM events newer WHERE newer.root_id=e.root_id AND newer.id>e.id)
            ORDER BY e.created,e.id''')]
        runs=store.latest_runs(db)
        projects=[dict(r) for r in db.execute('''SELECT p.id,p.title,p.updated,
            (SELECT title FROM project_steps s WHERE s.project_id=p.id AND s.done=0 ORDER BY position,id LIMIT 1) AS next_step
            FROM projects p WHERE p.state='active' ORDER BY p.updated DESC,p.id''')]
    actions=[row for row in actions if not row['snoozed_until'] or parse_time(row['snoozed_until']).astimezone(zone).date()<=now.date()]
    upcoming=[];enabled=0
    for task in tasks:
        task['enabled']=bool(task['enabled']);task['schedule']=json.loads(task['schedule']);task['config']=json.loads(task['config'])
        if not task['enabled']:continue
        enabled+=1;last=runs.get(task['id']);due=next_due(task,now)
        state='scheduled'
        if task['schedule']['type']=='once' and parse_time(task['schedule']['at'])<now:
            due=parse_time(task['schedule']['at']);state='overdue'
        if last and last['status'] in ('queued','running','retry'):
            due=parse_time(last['retry_at'] or last['scheduled_at'])
            state=last['status']
        if due:due=due.astimezone(zone)
        if due and (due.date()==now.date() or due<now and state in ('overdue','queued','running','retry')):
            upcoming.append({'task_id':task['id'],'name':task['name'],'at':due.isoformat(),'state':state})
    upcoming.sort(key=lambda r:(r['at'],r['task_id']))
    return {'version':2,'date':now.date().isoformat(),'timezone':str(zone),
            'paused':bool(settings.get('paused',False)),
            'counts':{'enabled_tasks':enabled,'active_projects':len(projects),'pending_reminders':len(actions)},
            'upcoming':upcoming[:3],'reminders':actions[:3],'projects':projects[:2]}
