"""Location-based weather functions; legacy mail CLI remains outside the desktop UI."""
import argparse
import json
import logging
import os
from pathlib import Path
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOCAL = timezone(timedelta(hours=5))
FIELDS = ["temperature_2m", "apparent_temperature", "relative_humidity_2m",
          "precipitation_probability", "precipitation", "snowfall",
          "wind_speed_10m", "wind_gusts_10m", "weather_code", "is_day"]


def forecast(day, attempts=3, timeout=25, location=None,end_day=None):
    from location_service import current,validate
    from zoneinfo import ZoneInfo
    place=location or current()
    if place is None:raise ValueError('Местоположение для прогноза не выбрано.')
    place=validate(place)
    first=datetime.fromisoformat(day).date();last=datetime.fromisoformat(end_day or day).date()
    if last<first or (last-first).days>7:raise ValueError('Invalid forecast interval')
    # The API ISO format uses one fixed offset for the whole response. Epochs
    # plus a boundary day on either side preserve real local dates across DST.
    query = urlencode(dict(latitude=place['latitude'], longitude=place['longitude'],
                           hourly=",".join(FIELDS), timezone=place['timezone'],
                           timeformat='unixtime',wind_speed_unit="ms",
                           start_date=str(first-timedelta(days=1)),end_date=str(last+timedelta(days=1))))
    for attempt in range(attempts):
        try:
            with urlopen("https://api.open-meteo.com/v1/forecast?" + query, timeout=timeout) as r:
                payload = json.load(r)
            hourly = payload["hourly"]
            for field in FIELDS:
                if len(hourly[field]) != len(hourly["time"]):
                    raise ValueError("Incomplete weather response")
            stamps=[datetime.fromtimestamp(value,ZoneInfo(place['timezone'])).strftime('%Y-%m-%dT%H:%M')
                    if isinstance(value,(int,float)) else value for value in hourly['time']]
            indices=[i for i,value in enumerate(stamps) if str(first)<=value[:10]<=str(last)]
            if not indices:raise ValueError('Empty forecast interval')
            return {key:[(stamps if key=='time' else values)[i] for i in indices] for key,values in hourly.items()}
        except (OSError, ValueError, KeyError):
            if attempt == attempts-1:
                raise
            time.sleep(3 * (attempt + 1))


def period_index(hourly,day,hour):
    target=datetime.fromisoformat(f'{day}T{hour:02d}:00')
    points=[(abs((datetime.fromisoformat(stamp)-target).total_seconds()),i)
            for i,stamp in enumerate(hourly['time']) if stamp[:10]==day]
    if not points:raise ValueError('Missing forecast day')
    distance,index=min(points)
    if distance>1800:raise ValueError('Missing requested forecast hour')
    return index


def render(hourly, day, fetched, location=None, hours=None):
    from location_service import current
    place=location or current()
    if place is None:raise ValueError('Местоположение для прогноза не выбрано.')
    from zoneinfo import ZoneInfo
    fetched=fetched.astimezone(ZoneInfo(place['timezone']))
    lines = [f"{place['name']} · {day}", 'Прогноз · '+place['timezone'], ""]
    for title, periods in zip(('Утро','День','Вечер'),hours or (9,13,17)):
        period_hours=[periods]
        lines.append(title)
        for hour in period_hours:
            try:i=period_index(hourly,day,hour)
            except ValueError:
                lines.append(f'  {hour:02d}:00 — час отсутствует в данных (возможен переход времени).')
                continue
            values = {key: hourly[key][i] for key in FIELDS}
            if any(v is None for v in values.values()):
                raise ValueError("Missing forecast value")
            lines.append(
                f"  {hourly['time'][i][11:16]} — {values['temperature_2m']:+.0f} °C, "
                f"ощущается {values['apparent_temperature']:+.0f} °C; "
                f"влажность {values['relative_humidity_2m']:.0f}%; "
                f"вероятность осадков {values['precipitation_probability']:.0f}%; "
                f"осадки {values['precipitation']:.1f} мм за предыдущий час; "
                f"снег {values['snowfall']:.1f} см за предыдущий час; "
                f"ветер {values['wind_speed_10m']:.1f}, "
                f"порывы {values['wind_gusts_10m']:.1f} м/с."
            )
        lines.append("")
    lines += ["Прогноз почасовой: показаны выбранные часы дня.",
              "Источник: Open-Meteo, https://open-meteo.com/",
              f"Получено: {fetched:%d.%m.%Y %H:%M} ({place['timezone']})."]
    return "\n".join(lines)


def send(subject, body, day, test=False):
    config = json.loads((ROOT / "mail.local.json").read_text(encoding="utf-8-sig"))
    username = config.get("username") or config["sender"]
    if "@" not in username or not all(username.split("@", 1)) or any(c.isspace() for c in username):
        raise ValueError("SMTP login must be a full email address; run set-mail-login.ps1")
    password = os.environ.get("URAY_SMTP_PASSWORD")
    if not password:
        raise ValueError("Use run.ps1 to load the protected app password")
    msg = EmailMessage()
    msg["From"] = config["sender"]
    msg["To"] = config["recipient"]
    msg["Subject"] = subject
    msg.set_content(body)
    # SMTP acceptance is not proof of inbox delivery or an iPhone notification.
    # Never retry automatically after entering SMTP: ambiguous failures may duplicate mail.
    with smtplib.SMTP_SSL("smtp.yandex.ru", 465, timeout=30,
                          context=ssl.create_default_context()) as smtp:
        smtp.login(username, password)
        smtp.send_message(msg)
    if not test:
        state = DATA / f"sent-{day}.json"
        state.write_text(json.dumps({"smtp_accepted_at": datetime.now(LOCAL).isoformat()}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--test", action="store_true", help="Send a clearly marked delivery test")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date())
    args = parser.parse_args()
    if args.date and args.send:
        parser.error("Explicit date is preview-only")
    if args.test and not args.send:
        parser.error("--test requires --send")
    DATA.mkdir(exist_ok=True)
    logging.basicConfig(filename=DATA / "weather.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(LOCAL)
    day = str(args.date or now.date())
    if args.scheduled and (now.weekday() >= 5 or not (8 <= now.hour < 9)):
        logging.info("Skipped outside weekday 08:00-08:59 local window")
        return
    # Exclusive file prevents concurrent sending. A crash leaves it for manual inspection.
    lock = DATA / "send.lock"
    locked = False
    try:
        if args.send:
            lock.open("x").close()
            locked = True
            if not args.test and (DATA / f"sent-{day}.json").exists():
                logging.info("Already accepted by SMTP today; skipped")
                return
        try:
            body = render(forecast(day), day, now)
            subject = f"Отчёт о погоде · {day}"
        except Exception:
            logging.exception("Weather unavailable")
            if not args.send:
                raise
            subject = f"Прогноз недоступен · {day}"
            body = ("Не удалось получить свежий прогноз. Погодная сводка на сегодня "
                    "не подготовлена. Проверьте погоду другим способом.\n"
                    f"Время проверки: {now:%H:%M}.")
        (DATA / "preview.txt").write_text(subject + "\n\n" + body, encoding="utf-8")
        if args.send:
            send(("ТЕСТ · " if args.test else "") + subject, body, day, args.test)
            logging.info("SMTP accepted message; phone delivery remains unverified")
            print("SMTP accepted the message. Check inbox and phone notification.")
        else:
            print(body)
    finally:
        if locked:
            lock.unlink()


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        main()
    except Exception as exc:
        logging.error("Run failed: %s", type(exc).__name__)
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            print(f"Yandex SMTP rejected authentication ({exc.smtp_code}): "
                  f"{exc.smtp_error.decode('utf-8', errors='replace')}", file=sys.stderr)
        print(f"Run failed ({type(exc).__name__}). See data/weather.log.", file=sys.stderr)
        sys.exit(1)
