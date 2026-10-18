"""Two-day weather construction and date-aware cache selection, independent of UI."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import weather
from location_service import location_key


def build_forecasts(place,now,hours):
    local=now.astimezone(ZoneInfo(place['timezone']));days=[local.date()+timedelta(days=i) for i in (0,1)]
    hourly=weather.forecast(str(days[0]),attempts=1,timeout=12,location=place,end_day=str(days[1]))
    result={}
    for day in days:
        indices=[i for i,stamp in enumerate(hourly['time']) if stamp[:10]==str(day)]
        if not indices:raise ValueError('Forecast is missing a requested day')
        selected={key:[values[i] for i in indices] for key,values in hourly.items()}
        result[str(day)]={'date':str(day),'fetched':now.isoformat(),'hourly':selected,
                          'location':place,'location_key':location_key(place)}
    return result


def select(cache,legacy,day,place):
    if not place:return None
    candidate=(cache or {}).get(str(day))
    if not candidate or candidate.get('date')!=str(day) or candidate.get('location_key')!=location_key(place):candidate=legacy
    if candidate and candidate.get('date')==str(day) and candidate.get('location_key')==location_key(place):return candidate
    return None


def is_stale(snapshot,now):
    fetched=datetime.fromisoformat(snapshot['fetched'])
    if fetched.tzinfo is None:raise ValueError('Forecast timestamp must have an offset')
    return (now.timestamp()-fetched.timestamp())>21600 or fetched.timestamp()>now.timestamp()+300
