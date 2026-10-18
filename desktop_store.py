"""Local notification inbox shared by the desktop UI and automation publishers."""
import json
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
import threading
from datetime import datetime,timedelta

from app_config import LOCAL,data_home,timezone_from_settings
from automation_defaults import templates,WEATHER_NAME
HOME = data_home()
SCHEMA_VERSION = 8
_schema_lock = threading.RLock()
_initialized = set()


def initialize():
    """Transactional, versioned migration; SQLite backup made before any schema changes."""
    path_key = str(HOME.resolve())
    if path_key in _initialized and (HOME / 'inbox.sqlite').exists(): return
    HOME.mkdir(parents=True, exist_ok=True)
    with _schema_lock:
        db = sqlite3.connect(HOME / 'inbox.sqlite', timeout=20)
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError('Database was created by a newer Orbita version')
            if version == SCHEMA_VERSION:
                _initialized.add(path_key)
                return
            has_history = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone())
            legacy = has_history and version < 2
            if has_history:
                folder = HOME / 'backups'; folder.mkdir(exist_ok=True)
                path = folder / ('inbox-v%d-%s.sqlite' % (version, datetime.now().strftime('%Y%m%d-%H%M%S-%f')))
                with closing(sqlite3.connect(path)) as backup:
                    db.backup(backup)
                    if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Backup integrity check failed')
            db.execute('BEGIN IMMEDIATE')
            # Another publisher may have completed migration while this process waited.
            if db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION:
                db.rollback(); _initialized.add(path_key); return
            db.execute('''CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,body TEXT NOT NULL,category TEXT NOT NULL,created TEXT NOT NULL,
                seen INTEGER NOT NULL DEFAULT 0,dedupe TEXT UNIQUE)''')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            columns = {row[1] for row in db.execute('PRAGMA table_info(events)')}
            for name, definition in [('task_id','TEXT'),('run_id','INTEGER'),
                                     ('action_state',"TEXT NOT NULL DEFAULT ''"),('root_id','INTEGER'),
                                     ('delivered','INTEGER NOT NULL DEFAULT 0'),('target','TEXT')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE events ADD COLUMN {name} {definition}')
            if legacy:
                db.execute('UPDATE events SET delivered=1')
            db.execute('''CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY,name TEXT NOT NULL,
                kind TEXT NOT NULL,enabled INTEGER NOT NULL,schedule TEXT NOT NULL,config TEXT NOT NULL,
                policy TEXT NOT NULL,grace_seconds INTEGER NOT NULL,max_attempts INTEGER NOT NULL,
                retry_seconds INTEGER NOT NULL,created TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,slot TEXT NOT NULL,scheduled_at TEXT NOT NULL,status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,started TEXT,finished TEXT,retry_at TEXT,
                lease_until TEXT,owner TEXT,error TEXT,summary TEXT,UNIQUE(task_id,slot))''')
            if 'recoveries' not in {row[1] for row in db.execute('PRAGMA table_info(runs)')}:
                db.execute('ALTER TABLE runs ADD COLUMN recoveries INTEGER NOT NULL DEFAULT 0')
            db.execute('''CREATE TABLE IF NOT EXISTS snoozes (id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_id INTEGER NOT NULL,event_id INTEGER NOT NULL,due TEXT NOT NULL,status TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS events_pending ON events(delivered,seen,id)')
            db.execute('CREATE INDEX IF NOT EXISTS runs_status ON runs(status,retry_at)')
            # Bound history lookups to the requested task, day or reminder chain.
            db.execute('CREATE INDEX IF NOT EXISTS runs_task_latest ON runs(task_id,id DESC)')
            db.execute('CREATE INDEX IF NOT EXISTS runs_day ON runs(scheduled_at)')
            db.execute('CREATE INDEX IF NOT EXISTS events_root ON events(root_id,id)')
            db.execute('CREATE INDEX IF NOT EXISTS events_action ON events(action_state,created,id)')
            db.execute('CREATE INDEX IF NOT EXISTS snoozes_due ON snoozes(status,due)')
            db.execute('CREATE INDEX IF NOT EXISTS snoozes_event ON snoozes(event_id,status)')
            db.execute('CREATE INDEX IF NOT EXISTS snoozes_root ON snoozes(root_id,status)')
            db.execute('CREATE TABLE IF NOT EXISTS revision (id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER NOT NULL)')
            db.execute('INSERT OR IGNORE INTO revision VALUES(1,0)')
            db.execute('''CREATE TABLE IF NOT EXISTS learning_progress (
                course_id TEXT NOT NULL,lesson_id TEXT NOT NULL,state TEXT NOT NULL,
                answer TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',
                hints_revealed INTEGER NOT NULL DEFAULT 0,solution_revealed INTEGER NOT NULL DEFAULT 0,
                assessment TEXT NOT NULL DEFAULT '{}',updated TEXT NOT NULL,content_version TEXT NOT NULL,
                PRIMARY KEY(course_id,lesson_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS learning_profiles (
                course_id TEXT PRIMARY KEY,active_lesson TEXT,platform TEXT NOT NULL DEFAULT '',
                server_version TEXT NOT NULL DEFAULT '')''')
            db.execute('''CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL,state TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',created TEXT NOT NULL,updated TEXT NOT NULL,
                reminder_task_id TEXT UNIQUE)''')
            db.execute('''CREATE TABLE IF NOT EXISTS project_steps (
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
                title TEXT NOT NULL,done INTEGER NOT NULL DEFAULT 0,position INTEGER NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS project_links (
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
                label TEXT NOT NULL,url TEXT NOT NULL,UNIQUE(project_id,url))''')
            db.execute('CREATE INDEX IF NOT EXISTS project_steps_order ON project_steps(project_id,position)')
            for table in ('events','tasks','runs','settings','learning_progress','learning_profiles',
                          'projects','project_steps','project_links'):
                for action in ('INSERT','UPDATE','DELETE'):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS rev_{table}_{action}
                        AFTER {action} ON {table} BEGIN UPDATE revision SET value=value+1 WHERE id=1; END''')
            now = datetime.now(LOCAL)
            existing = {k: json.loads(v) for k,v in db.execute('SELECT key,value FROM settings')}
            defaults = templates()
            if legacy:
                defaults[0]['enabled']=existing.get('weather_enabled',False)
                defaults[0]['schedule']['days']=[0,1,2,3,4]
            for task in defaults:
                task['schedule']['timezone']='Asia/Yekaterinburg' if has_history else 'UTC'
                db.execute('INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (task['id'],task['name'],task['kind'],int(task['enabled']),json.dumps(task['schedule']),
                     json.dumps(task['config']),task['policy'],task['grace_seconds'],task['max_attempts'],
                     task['retry_seconds'],now.replace(hour=0,minute=0,second=0,microsecond=0).isoformat()))
            old_day = existing.get('weather_day')
            if old_day and version<2:
                stamp = old_day+'T08:00:00+05:00'
                db.execute('''INSERT OR IGNORE INTO runs(task_id,slot,scheduled_at,status,finished,summary)
                    VALUES('weather',?,?,'success',?,'Импортировано из предыдущей версии')''',(stamp,stamp,stamp))
            if version<6:
                from location_service import LEGACY_LOCATION,location_key
                for row in db.execute('SELECT id,schedule FROM tasks').fetchall():
                    spec=json.loads(row[1]);spec.setdefault('timezone','Asia/Yekaterinburg')
                    db.execute('UPDATE tasks SET schedule=? WHERE id=?',(json.dumps(spec),row[0]))
                if has_history:
                    db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('location_profile',json.dumps(LEGACY_LOCATION,ensure_ascii=False)))
                    snapshot=existing.get('weather_snapshot')
                    if snapshot and 'location_key' not in snapshot:
                        snapshot['location_key']=location_key(LEGACY_LOCATION);snapshot['location']=LEGACY_LOCATION
                        db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(snapshot,ensure_ascii=False),'weather_snapshot'))
            if version<8:
                # Change only the exact former built-in title; user titles remain theirs.
                db.execute("UPDATE tasks SET name=? WHERE id='weather' AND name=?",(WEATHER_NAME,'Погода для поездок'))
                if not has_history:
                    db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('onboarding_pending','true'))
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Migration integrity check failed')
            db.commit()
            _initialized.add(path_key)
        except Exception:
            db.rollback(); raise
        finally:
            db.close()


@contextmanager
def connect():
    initialize()
    db = sqlite3.connect(HOME / 'inbox.sqlite', timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def publish(title, body, category='Задачи', dedupe=None):
    if not title.strip() or not body.strip():
        raise ValueError('Title and body must not be empty')
    with connect() as db:
        row = db.execute('INSERT OR IGNORE INTO events(title,body,category,created,dedupe) VALUES(?,?,?,?,?)',
                         (title, body, category, datetime.now(LOCAL).isoformat(), dedupe))
        return row.lastrowid if row.rowcount else None


def events(limit=100):
    with connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,))]


def user_events(limit=100):
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM events WHERE category!='Демо' ORDER BY id DESC LIMIT ?",(limit,))]


def mark_seen(event_id=None):
    with connect() as db:
        if event_id is None:
            db.execute('UPDATE events SET seen=1,delivered=1')
        else:
            db.execute('UPDATE events SET seen=1,delivered=1 WHERE id=?', (event_id,))


def get_setting(key, default=None):
    with connect() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default


def get_settings():
    """One consistent settings snapshot, without a connection per property."""
    with connect() as db:
        return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}


def set_setting(key, value):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))


def timezone_name():
    return timezone_from_settings(get_settings())


def local_zone():
    from zoneinfo import ZoneInfo
    return ZoneInfo(timezone_name())


def display_time(value):
    return datetime.fromisoformat(value).astimezone(local_zone())


def revision():
    with connect() as db:
        return db.execute('SELECT value FROM revision WHERE id=1').fetchone()[0]


class RevisionReader:
    """A UI-thread reader avoids reopening SQLite for every idle poll."""
    def __init__(self):
        initialize()
        self.db=sqlite3.connect(HOME/'inbox.sqlite',timeout=5)

    def value(self):
        return self.db.execute('SELECT value FROM revision WHERE id=1').fetchone()[0]

    def close(self):
        self.db.close()


def tasks():
    with connect() as db:
        result = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY created,id')]
    for row in result:
        row['schedule'] = json.loads(row['schedule']); row['config'] = json.loads(row['config'])
        row['enabled'] = bool(row['enabled'])
    return result


def save_task(task):
    from automation_models import validate_schedule
    validate_schedule(task['schedule'])
    if task['kind'] not in ('weather','reminder','audit','learning') or not task['name'].strip():
        raise ValueError('Invalid task')
    if task['policy'] not in ('skip','latest') or not 1 <= task['max_attempts'] <= 5:
        raise ValueError('Invalid retry policy')
    if not 0 <= task['grace_seconds'] <= 31536000 or not 1 <= task['retry_seconds'] <= 86400:
        raise ValueError('Invalid schedule limits')
    with connect() as db:
        if task['enabled'] and task['config'].get('project_id'):
            project=db.execute('SELECT state,reminder_task_id FROM projects WHERE id=?',(task['config']['project_id'],)).fetchone()
            if not project or project['state']!='active' or project['reminder_task_id']!=task['id']:
                raise ValueError('Сначала верни связанный проект в работу и настрой его напоминание.')
        db.execute('''INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,enabled=excluded.enabled,schedule=excluded.schedule,config=excluded.config,
            policy=excluded.policy,grace_seconds=excluded.grace_seconds,max_attempts=excluded.max_attempts,
            retry_seconds=excluded.retry_seconds''',
            (task['id'],task['name'],task['kind'],int(task['enabled']),json.dumps(task['schedule']),
             json.dumps(task['config']),task['policy'],task['grace_seconds'],task['max_attempts'],
             task['retry_seconds'],task['created']))


def runs(task_id=None, limit=100):
    with connect() as db:
        if task_id:
            return [dict(row) for row in db.execute('SELECT * FROM runs WHERE task_id=? ORDER BY id DESC LIMIT ?', (task_id,limit))]
        return [dict(row) for row in db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT ?', (limit,))]


def latest_runs(db=None):
    """One indexed seek per task; cost does not grow with the run history."""
    if db is None:
        with connect() as connection:return latest_runs(connection)
    return {r['task_id']:dict(r) for r in db.execute('''SELECT r.* FROM tasks t JOIN runs r
        ON r.id=(SELECT id FROM runs WHERE task_id=t.id ORDER BY id DESC LIMIT 1)''')}


def pending_events(limit=50):
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM events WHERE delivered=0 AND seen=0 AND category!='Демо' ORDER BY id LIMIT ?", (limit,))]


def delivered(event_id):
    with connect() as db: db.execute('UPDATE events SET delivered=1 WHERE id=?',(event_id,))


def reminder_action(event_id, action, now=None):
    now = (now or datetime.now(LOCAL)).astimezone(LOCAL)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
        if not row or not row['root_id'] or row['action_state'] in ('done','cancelled'): return
        root = row['root_id']
        db.execute("UPDATE snoozes SET status='cancelled' WHERE root_id=? AND status='pending'",(root,))
        if action == 'done':
            db.execute("UPDATE events SET action_state='done',seen=1,delivered=1 WHERE root_id=?",(root,))
        elif action == 'snooze':
            db.execute("UPDATE events SET action_state='snoozed',seen=1,delivered=1 WHERE root_id=? AND action_state!='done'",(root,))
            db.execute("INSERT INTO snoozes(root_id,event_id,due,status) VALUES(?,?,?,'pending')",
                       (root,event_id,(now+timedelta(minutes=15)).isoformat()))
        else: raise ValueError('Unknown reminder action')


def deliver_snoozes(now):
    now=now.astimezone(LOCAL)
    with connect() as db:
        if not db.execute("SELECT 1 FROM snoozes WHERE status='pending' AND due<=? LIMIT 1",(now.isoformat(),)).fetchone():return
        db.execute('BEGIN IMMEDIATE')
        rows = list(db.execute("SELECT * FROM snoozes WHERE status='pending' AND due<=?",(now.isoformat(),)))
        for snooze in rows:
            row = db.execute('SELECT * FROM events WHERE id=?',(snooze['event_id'],)).fetchone()
            if row and row['action_state'] not in ('done','cancelled'):
                db.execute('''INSERT OR IGNORE INTO events(title,body,category,created,dedupe,task_id,run_id,action_state,root_id,target)
                    VALUES(?,?,?,?,?,?,?,'pending',?,?)''',
                    (row['title'],row['body'],row['category'],now.isoformat(),f"snooze-{snooze['id']}",
                     row['task_id'],row['run_id'],snooze['root_id'],row['target']))
            db.execute("UPDATE snoozes SET status='delivered' WHERE id=?",(snooze['id'],))
