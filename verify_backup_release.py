"""Built UI/CLI + service restore in an isolated synthetic Windows profile."""
from contextlib import closing
import hashlib,json,os
from pathlib import Path
import sqlite3,subprocess,tempfile,time
from app_config import VERSION
import desktop_store as store
from profile_access import access
import backup_service as backups


def main():
    root=Path(__file__).resolve().parent;exe=root/'dist/Orbita/Orbita.exe'
    manifest=json.loads((exe.parent/'release-manifest.json').read_text(encoding='utf-8'))
    assert manifest['version']==VERSION and not manifest['source_dirty']
    scratch=Path(tempfile.mkdtemp(prefix='orbita-backup-release-'));profile=scratch/'profile';copies=scratch/'copies';copies.mkdir()
    env=dict(os.environ,AUTOMATION_HOME=str(profile));runs=[]
    def run(*args):
        result=subprocess.run([str(exe),*map(str,args)],env=env,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(args,result.returncode)
        runs.append({'args':list(map(str,args)),'exit_code':0})
    def payload(name):
        file=scratch/(name+'.json');file.write_text(json.dumps({'title':name,'body':'Synthetic result','dedupe':name}),encoding='utf-8');return file
    first=payload('initial');run('--publish-file',first);run('--publish-file',first)
    capture=root/'data/data-exe-093.png';run('--data','--capture',capture)
    store.HOME=profile;store.initialize();backup=backups.create(profile,copies)
    later=payload('later');run('--publish-file',later)
    backups.restore(profile,backup);run('--publish-file',later)
    blocked=payload('blocked')
    with access(profile,True):
        child=subprocess.Popen([str(exe),'--publish-file',str(blocked)],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(.7);assert child.poll() is None,'Native publisher did not wait on maintenance gate'
    assert child.wait(30)==0
    run('--smoke-test')
    with closing(sqlite3.connect(profile/'inbox.sqlite')) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA user_version').fetchone()[0]==9
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0]==2
        assert json.loads(db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()[0]) is True
        assert db.execute("SELECT enabled FROM tasks WHERE id='profile-backup'").fetchone()[0]==0
    report={'version':VERSION,'profile':str(profile),'source_commit':manifest['source_commit'],'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
            'native_data_dialog_capture':str(capture),'native_publish_deduplicated':True,'native_publisher_waits_for_gate':True,
            'service_restore_roundtrip':True,'no_replay_after_restart':True,'default_restore_pause':True,'runs':runs,
            'limits':'One Windows 11 x64 host. Built exe UI/CLI and restart are exercised; restore itself uses source service here. Full UI restore/restart path and crash recovery are covered separately by isolated integration tests.'}
    (root/'data/backup-release-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
