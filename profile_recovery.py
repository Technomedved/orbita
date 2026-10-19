"""Durable recovery journal. Called only while the profile gate is exclusive."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time


def write_json(path,value):
    path=Path(path);temporary=path.with_suffix('.writing')
    with temporary.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def database_copy(source,destination):
    """SQLite commits the destination copy atomically; bound lock/contention waits."""
    deadline=time.monotonic()+45
    def progress(status,remaining,total):
        if time.monotonic()>deadline:raise TimeoutError('Database copy timed out')
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True,timeout=10)) as src, closing(sqlite3.connect(destination,timeout=10)) as dst:
        dst.execute('PRAGMA synchronous=FULL')
        src.backup(dst,pages=256,progress=progress,sleep=.05)


def check_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        deadline=time.monotonic()+30
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Повреждена база резервной копии.')


def cleanup(home):
    folder=Path(home)/'.restore'
    if folder.is_symlink() or folder.is_junction():raise ValueError('Recovery directory must not be a link')
    # Fixed own files only, never recursively remove an arbitrary directory.
    for name in ('journal.json','journal.writing','previous.sqlite','incoming.sqlite'):
        try:(folder/name).unlink(missing_ok=True)
        except OSError:pass # committed cleanup can be retried; data is already consistent
    try:folder.rmdir()
    except OSError:pass


def recover_locked(home):
    home=Path(home);folder=home/'.restore'
    if folder.is_symlink() or folder.is_junction():raise ValueError('Recovery directory must not be a link')
    journal=json.loads((folder/'journal.json').read_text(encoding='utf-8'))
    if journal.get('format')!=1 or journal.get('phase') not in ('prepared','applying','committed'):
        raise ValueError('Неизвестный журнал восстановления. Данные не изменены.')
    if journal['phase']!='committed':
        check_database(folder/'previous.sqlite')
        database_copy(folder/'previous.sqlite',home/'inbox.sqlite')
        check_database(home/'inbox.sqlite')
        # If cleanup is temporarily blocked, never roll back later user writes
        # again on the next shared access. Recovery itself is now committed.
        write_json(folder/'journal.json',{'format':1,'phase':'committed'})
    cleanup(home)
