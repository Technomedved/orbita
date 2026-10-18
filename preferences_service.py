"""Offline first-run preferences; no platform or UI dependencies."""
import json
from zoneinfo import ZoneInfo
import desktop_store as store
from automation_defaults import templates


def _template_zones(db,old_zone,new_zone):
    for template in templates(old_zone):
        row=db.execute('''SELECT schedule FROM tasks WHERE id=? AND enabled=0
            AND NOT EXISTS(SELECT 1 FROM runs WHERE task_id=tasks.id)''',(template['id'],)).fetchone()
        if row and json.loads(row[0])==template['schedule']:
            spec=dict(template['schedule'],timezone=new_zone)
            db.execute('UPDATE tasks SET schedule=? WHERE id=?',(json.dumps(spec),template['id']))


def bootstrap(system_zone):
    """Seed a new desktop profile once; never move existing user schedules."""
    try:ZoneInfo(system_zone)
    except (ValueError,KeyError):system_zone='UTC'
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        values={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}
        if not values.get('onboarding_pending') or 'user_timezone' in values:return
        zone=(values.get('location_profile') or {}).get('timezone',system_zone)
        _template_zones(db,'UTC',zone)
        db.execute('INSERT INTO settings VALUES(?,?)',('user_timezone',json.dumps(zone)))
        db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('topmost','false'))


def complete(timezone,toasts=True,animations=True):
    ZoneInfo(timezone)
    if type(toasts) is not bool or type(animations) is not bool:raise ValueError('Нужны логические настройки уведомлений и анимаций.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        values={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}
        if values.get('onboarding_pending'):
            _template_zones(db,values.get('user_timezone','UTC'),timezone)
            db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('location_setup_complete','true'))
        for key,value in [('user_timezone',timezone),('toasts',toasts),('animations',animations),('onboarding_pending',False)]:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))


def set_timezone(timezone):
    ZoneInfo(timezone)
    store.set_setting('user_timezone',timezone)
