"""Portable schedules with explicit IANA zones; stable legacy storage offset."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app_config import LOCAL


def parse_time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Datetime must include its UTC offset')
    return result.astimezone(LOCAL)


def validate_schedule(spec):
    ZoneInfo(spec.get('timezone','Asia/Yekaterinburg'))
    if spec.get('start_at'):parse_time(spec['start_at'])
    kind = spec.get('type')
    if kind == 'once':
        parse_time(spec['at'])
    elif kind in ('daily', 'weekly'):
        datetime.strptime(spec['time'], '%H:%M')
        days = spec.get('days', list(range(7)))
        if not days or any(type(d) is not int or d not in range(7) for d in days):
            raise ValueError('Select at least one weekday')
        if kind == 'weekly' and len(days) != 1:
            raise ValueError('A weekly schedule needs one weekday')
    else:
        raise ValueError('Unknown schedule type')


def wall_time(day,clock,zone):
    """First occurrence on overlap; nonexistent DST wall times are skipped."""
    hour,minute=map(int,clock.split(':'))
    at=datetime(day.year,day.month,day.day,hour,minute,tzinfo=zone,fold=0)
    if at.astimezone(LOCAL).astimezone(zone).replace(tzinfo=None)!=at.replace(tzinfo=None):return None
    return at.astimezone(LOCAL)


def latest_due(task, now):
    spec = task['schedule']
    zone=ZoneInfo(spec.get('timezone','Asia/Yekaterinburg'))
    local=now.astimezone(zone);now=now.astimezone(LOCAL)
    created = max(parse_time(task['created']),parse_time(spec.get('start_at',task['created'])))
    if spec['type'] == 'once':
        at = parse_time(spec['at'])
        return at if at <= now else None
    for offset in range(8):
        day=(local-timedelta(days=offset)).date()
        at=wall_time(day,spec['time'],zone)
        if at and day.weekday() in spec.get('days', range(7)) and created <= at <= now:
            return at
    return None


def next_due(task, now):
    if not task['enabled']:
        return None
    spec = task['schedule']
    zone=ZoneInfo(spec.get('timezone','Asia/Yekaterinburg'))
    local=now.astimezone(zone);now=now.astimezone(LOCAL)
    if spec['type'] == 'once':
        at = parse_time(spec['at'])
        return max(at, now)
    for offset in range(8):
        day=(local+timedelta(days=offset)).date()
        at=wall_time(day,spec['time'],zone)
        if at and at > now and day.weekday() in spec.get('days', range(7)):
            return at
    return None


def occurrences(task,start,end):
    """Enabled calendar slots in an absolute half-open interval, without writes."""
    if not task['enabled']:return []
    start,end=start.astimezone(LOCAL),end.astimezone(LOCAL)
    spec=task['schedule'];created=max(parse_time(task['created']),parse_time(spec.get('start_at',task['created'])))
    if spec['type']=='once':
        at=parse_time(spec['at']);return [at] if start<=at<end and at>=created else []
    zone=ZoneInfo(spec.get('timezone','Asia/Yekaterinburg'))
    day=start.astimezone(zone).date()-timedelta(days=1);last=end.astimezone(zone).date()+timedelta(days=1);result=[]
    while day<=last:
        if day.weekday() in spec.get('days',range(7)):
            at=wall_time(day,spec['time'],zone)
            if at and start<=at<end and at>=created:result.append(at)
        day+=timedelta(days=1)
    return sorted(result)


def new_task(name, kind, schedule, config=None, enabled=False, now=None):
    schedule=dict(schedule);schedule.setdefault('timezone','UTC')
    validate_schedule(schedule)
    now = now or datetime.now(LOCAL)
    if not name.strip():
        raise ValueError('Task name is required')
    return dict(id=uuid4().hex, name=name.strip(), kind=kind, enabled=bool(enabled),
                schedule=schedule, config=config or {}, policy='latest', grace_seconds=3600,
                max_attempts=1 if kind == 'reminder' else 3, retry_seconds=300,
                created=now.astimezone(LOCAL).isoformat())


def schedule_text(task):
    spec = task['schedule']
    name=spec.get('timezone','Asia/Yekaterinburg');zone=ZoneInfo(name)
    if spec['type'] == 'once':
        return parse_time(spec['at']).astimezone(zone).strftime('%d.%m.%Y в %H:%M') + ' · '+name
    weekdays = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
    days = ', '.join(weekdays[d] for d in spec.get('days', range(7)))
    return f"{days} · {spec['time']} · {name}"


@dataclass
class Result:
    title: str
    body: str
    category: str
    summary: str = 'Готово'
    settings: dict = None
    reminder: bool = False
    target: str = None
    notification_key: str = None
    coalesce: bool = False
