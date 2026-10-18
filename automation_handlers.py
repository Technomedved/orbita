"""Read-only work and result construction; no UI or platform dependencies."""
from datetime import timedelta
import desktop_store as store
from automation_models import Result
import weather


def weather_result(task, now):
    from location_service import current,location_key
    from zoneinfo import ZoneInfo
    from weather_service import build_forecasts
    place=current()
    if not place:raise ValueError('Сначала выбери местоположение в настройках.')
    local=now.astimezone(ZoneInfo(place['timezone']));day = str(local.date())
    hours=store.get_setting('weather_hours',[9,13,17]);forecasts=build_forecasts(place,now,hours)
    snapshot=forecasts[day];tomorrow=str(local.date()+timedelta(days=1))
    body=weather.render(snapshot['hourly'],day,now,place,hours)+'\n\nЗАВТРА\n'+weather.render(forecasts[tomorrow]['hourly'],tomorrow,now,place,hours)
    return Result(f"{place['name']} · погода {local:%d.%m}–{local+timedelta(days=1):%d.%m}",body,'Погода','Получен прогноз на два дня',
                  {'weather_snapshot':snapshot,'weather_forecasts':forecasts})


def reminder_result(task, now):
    if task['config'].get('project_id'):
        from project_service import reminder_content
        title,body,target=reminder_content(task['config']['project_id'])
        return Result(title,body,'Проекты','Напоминание о следующем шаге проекта',reminder=True,target=target)
    return Result(task['name'], task['config'].get('body') or task['name'],
                  'Напоминания', 'Напоминание сохранено в ленте', reminder=True)


def audit_result(task, now):
    since = (now-timedelta(days=7)).isoformat()
    with store.connect() as db:
        total_tasks, enabled = db.execute('SELECT COUNT(*),COALESCE(SUM(enabled),0) FROM tasks').fetchone()
        counts = dict(db.execute('SELECT status,COUNT(*) FROM runs WHERE scheduled_at>=? GROUP BY status',(since,)))
        unread = db.execute("SELECT COUNT(*) FROM events WHERE seen=0 AND category!='Демо'").fetchone()[0]
        errors = list(db.execute('''SELECT t.name,COUNT(*) FROM runs r JOIN tasks t ON t.id=r.task_id
            WHERE r.status='failed' AND r.scheduled_at>=? GROUP BY t.id HAVING COUNT(*)>=2''',(since,)))
        old = list(db.execute('''SELECT t.name,COUNT(*) FROM events e JOIN tasks t ON t.id=e.task_id
            WHERE e.seen=0 AND e.category!='Демо' AND e.created<? GROUP BY t.id''',((now-timedelta(days=2)).isoformat(),)))
    local=now.astimezone(store.local_zone())
    lines = [f'Обзор за 7 дней · {local:%d.%m.%Y}', '',f'Задач: {total_tasks}, включено: {enabled}.',
             f"Успешных запусков: {counts.get('success',0)}.",f"Ошибок: {counts.get('failed',0)}.",
             f"Пропущено по правилам расписания: {counts.get('skipped',0)}.",
             f"Ожидают повторной попытки: {counts.get('retry',0)}.",f'Непрочитанных уведомлений: {unread}.','']
    if sum(counts.values()) < 5:
        lines.append('Данных пока мало: для устойчивых выводов нужно больше реальных запусков.')
    lines += [f'Повторяющиеся ошибки: {name} — {count}. Проверь источник и настройки.' for name,count in errors]
    lines += [f'Не прочитаны более двух дней: {name} — {count}. Возможно, стоит пересмотреть частоту.' for name,count in old]
    if not errors and not old: lines.append('Повторяющихся проблем по доступному журналу не найдено.')
    lines.append('Рекомендации не меняют настройки и не отключают задачи автоматически.')
    return Result('Еженедельный аудит автоматизаций','\n'.join(lines),'Аудит','Сводка по реальным журналам')


def learning_result(task,now):
    import learning_service as learning
    item=learning.current_lesson()
    if item is None:
        return Result('Практика Db2 · стартовый набор завершён',
                      'Все семь разделов отмечены тобой как завершённые. Это не автоматическая проверка SQL. '
                      'Можно вернуться к материалам в разделе «Обучение» или поставить расписание на паузу.',
                      'Обучение','Курс завершён пользователем',target='course:db2',
                      notification_key='learning-db2-finished',coalesce=True)
    ongoing=learning.progress(item['id'])['state']=='in_progress'
    return Result(('Продолжить: ' if ongoing else 'Практика Db2: ')+item['title'],
                  f"{item['goal']}\nВремя: {item['minutes']} минут.\n"
                  'Открой занятие: ответ, заметки и подсказки сохраняются. Новые уроки не накапливаются, пока текущий не завершён.',
                  'Обучение','Продолжение текущего занятия' if ongoing else 'Занятие готово к открытию',
                  target='lesson:db2:'+item['id'],notification_key='learning-db2-'+item['id'],coalesce=True)


HANDLERS = {'weather':weather_result,'reminder':reminder_result,'audit':audit_result,'learning':learning_result}
