"""Neutral, disabled templates shared by storage and first-run configuration."""
from copy import deepcopy

WEATHER_NAME='Отчёт о погоде'
TEMPLATES=[
    dict(id='weather',name=WEATHER_NAME,kind='weather',enabled=False,
         schedule={'type':'daily','time':'08:00','days':list(range(7))},config={},
         policy='skip',grace_seconds=3600,max_attempts=3,retry_seconds=300),
    dict(id='audit',name='Аудит автоматизаций',kind='audit',enabled=False,
         schedule={'type':'weekly','time':'18:00','days':[4]},config={},
         policy='latest',grace_seconds=604800,max_attempts=2,retry_seconds=300),
    dict(id='learning-db2',name='Практика Db2',kind='learning',enabled=False,
         schedule={'type':'daily','time':'19:30','days':[1,3]},config={'course_id':'db2'},
         policy='latest',grace_seconds=604800,max_attempts=1,retry_seconds=300)]


def templates(timezone='UTC'):
    values=deepcopy(TEMPLATES)
    for value in values:value['schedule']['timezone']=timezone
    return values
