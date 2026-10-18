"""Location profiles and public geocoding. No UI, device access or IP lookup."""
from datetime import datetime
import hashlib
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LEGACY_LOCATION={'name':'Урай','latitude':60.13044,'longitude':64.78896,
                 'timezone':'Asia/Yekaterinburg','source':'legacy','accuracy_m':None}


def validate(profile):
    value=dict(profile)
    for key,limit in [('latitude',90),('longitude',180)]:
        number=float(value[key])
        if not math.isfinite(number) or not -limit<=number<=limit:raise ValueError('Некорректные координаты.')
        value[key]=number
    name=str(value.get('name','')).strip()
    if not name or len(name)>200:raise ValueError('Укажи название места (до 200 символов).')
    value['name']=name
    try:ZoneInfo(value['timezone'])
    except (KeyError,ValueError,ZoneInfoNotFoundError):raise ValueError('Неизвестный часовой пояс IANA.') from None
    value['source']=value.get('source','manual')
    if value['source'] not in ('legacy','manual','device'):raise ValueError('Неизвестный источник местоположения.')
    accuracy=value.get('accuracy_m')
    if accuracy is not None and (not math.isfinite(float(accuracy)) or float(accuracy)<0):raise ValueError('Некорректная точность.')
    value['accuracy_m']=None if accuracy is None else float(accuracy)
    return value


def location_key(profile):
    return hashlib.sha256(json.dumps([profile['latitude'],profile['longitude'],profile['timezone']],separators=(',',':')).encode()).hexdigest()[:20]


def current():
    import desktop_store as store
    value=store.get_setting('location_profile')
    return validate(value) if value else None


def request_json(url,timeout=12):
    req=Request(url,headers={'User-Agent':'Orbita/0.6 (desktop weather location)','Accept':'application/json'})
    with urlopen(req,timeout=timeout) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Слишком большой ответ сервиса.')
    return json.loads(raw)


def search_cities(query,fetch=None):
    query=query.strip()
    if not 2<=len(query)<=120:raise ValueError('Введи от 2 до 120 символов названия города.')
    payload=(fetch or request_json)('https://geocoding-api.open-meteo.com/v1/search?'+urlencode(
        {'name':query,'count':10,'language':'ru','format':'json'}))
    result=[]
    for row in payload.get('results',[]):
        try:
            item=validate(dict(name=row['name'],latitude=row['latitude'],longitude=row['longitude'],
                               timezone=row['timezone'],source='manual'))
            item['region']=' · '.join(str(row.get(k,'')) for k in ('admin1','country') if row.get(k))
            result.append(item)
        except (ValueError,KeyError,TypeError):continue
    return result


def from_device(latitude,longitude,accuracy_m=None,fetch=None):
    # Round before the external request: weather does not need an exact address.
    lat,lon=round(float(latitude),2),round(float(longitude),2)
    value=validate(dict(name='Текущее местоположение',latitude=lat,longitude=lon,
                        timezone='UTC',source='device',accuracy_m=accuracy_m))
    payload=(fetch or request_json)('https://api.open-meteo.com/v1/forecast?'+urlencode(
        {'latitude':lat,'longitude':lon,'timezone':'auto','forecast_days':1}))
    value['timezone']=payload['timezone']
    return validate(value)


def save(profile,hours=(9,13,17),refresh_on_start=False):
    import desktop_store as store
    value=validate(profile)
    if len(hours)!=3 or any(type(n) is not int or not 0<=n<=23 for n in hours):raise ValueError('Для каждого периода укажи час от 0 до 23.')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute("SELECT value FROM settings WHERE key='location_profile'").fetchone()
        old=json.loads(old[0]) if old else None
        for key,item in [('location_profile',value),('location_setup_complete',True),('weather_hours',list(hours)),
                         ('location_refresh_on_start',bool(refresh_on_start and value['source']=='device'))]:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(item,ensure_ascii=False)))
        if not old or location_key(old)!=location_key(value):
            # Weather follows the place. Existing reminders retain their own zones.
            for row in db.execute("SELECT id,schedule FROM tasks WHERE kind='weather'").fetchall():
                spec=json.loads(row['schedule']);spec['timezone']=value['timezone']
                spec['start_at']=datetime.now(store.LOCAL).isoformat()
                db.execute('UPDATE tasks SET schedule=? WHERE id=?',(json.dumps(spec),row['id']))
        if old is None:
            # Initial disabled templates are not yet user schedules.
            for row in db.execute("SELECT id,schedule FROM tasks WHERE id IN ('audit','learning-db2') AND enabled=0 AND NOT EXISTS (SELECT 1 FROM runs WHERE task_id=tasks.id)").fetchall():
                spec=json.loads(row['schedule'])
                default=('18:00',[4]) if row['id']=='audit' else ('19:30',[1,3])
                if spec.get('timezone')=='UTC' and (spec.get('time'),spec.get('days'))==default:
                    spec['timezone']=value['timezone'];db.execute('UPDATE tasks SET schedule=? WHERE id=?',(json.dumps(spec),row['id']))
    return value


def defer_setup():
    import desktop_store as store
    store.set_setting('location_setup_complete',True)
