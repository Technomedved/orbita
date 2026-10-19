"""Cross-process profile gate backed by SQLite locks (no UI/platform API).

Normal operations hold a shared transaction on a separate gate database.
Maintenance takes an exclusive transaction. OS process death releases the lock.
"""
from contextlib import contextmanager, closing
from pathlib import Path
import json
import sqlite3
import threading

_local=threading.local()


@contextmanager
def access(home, exclusive=False):
    home=Path(home).resolve();home.mkdir(parents=True,exist_ok=True)
    key=str(home);held=getattr(_local,'held',{})
    if key in held:
        if exclusive and not held[key]:raise RuntimeError('Cannot upgrade an active profile operation')
        yield
        return
    gate=home/'.profile-access.sqlite'
    if gate.is_symlink():raise ValueError('Profile gate must not be a link')
    with closing(sqlite3.connect(gate,timeout=30,isolation_level=None)) as db:
        # No DDL under other readers after initialization.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='gate'").fetchone():
            db.execute('CREATE TABLE IF NOT EXISTS gate(id INTEGER PRIMARY KEY)')
        recovery_attempted=False
        while True:
            db.execute('BEGIN EXCLUSIVE' if exclusive else 'BEGIN')
            db.execute('SELECT id FROM gate').fetchall()
            pending=(home/'.restore/journal.json').exists()
            committed=False
            if pending and recovery_attempted:
                journal=json.loads((home/'.restore/journal.json').read_text(encoding='utf-8'))
                committed=journal.get('format')==1 and journal.get('phase')=='committed'
            if pending and not exclusive and not committed:
                db.rollback()
                with access(home,True):pass
                recovery_attempted=True
                continue
            held=dict(held);held[key]=exclusive;_local.held=held
            try:
                if pending and exclusive:
                    from profile_recovery import recover_locked
                    recover_locked(home)
                yield
            finally:
                _local.held={k:v for k,v in _local.held.items() if k!=key}
                db.rollback()
            break
