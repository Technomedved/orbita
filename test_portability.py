import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from app_config import data_home


class PortabilityTests(unittest.TestCase):
    def test_windows_fresh_profile_has_neutral_path(self):
        self.assertEqual(data_home('win32',{'LOCALAPPDATA':'C:/User/AppData/Local'},'C:/User'),Path('C:/User/AppData/Local/Orbita'))

    def test_windows_existing_database_keeps_legacy_path_without_copying(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);legacy=base/'UrayAssistant';legacy.mkdir();(legacy/'inbox.sqlite').touch()
            self.assertEqual(data_home('win32',{'LOCALAPPDATA':folder}),legacy)
            modern=base/'Orbita';modern.mkdir();(modern/'inbox.sqlite').touch()
            self.assertEqual(data_home('win32',{'LOCALAPPDATA':folder}),modern)

    def test_macos_and_linux_data_paths_do_not_use_windows_settings(self):
        self.assertEqual(data_home('darwin',{'LOCALAPPDATA':'wrong'},'/Users/test'),Path('/Users/test/Library/Application Support/Orbita'))
        self.assertEqual(data_home('linux',{},'/home/test'),Path('/home/test/.local/share/orbita'))
        self.assertEqual(data_home('linux',{'XDG_DATA_HOME':'/var/user-data'},'/home/test'),Path('/var/user-data/orbita'))

    def test_explicit_data_home_overrides_every_platform(self):
        for platform in ('win32','darwin','linux'):
            self.assertEqual(data_home(platform,{'AUTOMATION_HOME':'isolated-tests'},'/unused'),Path('isolated-tests'))

    def test_core_works_with_qt_and_windows_adapter_imports_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            script='''import importlib.abc,sys,json
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in ('PySide6','windows_integration','winreg'):
            raise RuntimeError('Forbidden platform dependency: '+fullname)
sys.meta_path.insert(0,Block())
import app_config,automation_models,automation_engine,project_service,learning_service,today_service,agenda_service,weather_service
import backup_service,health_service,profile_access,profile_recovery
engine=automation_engine.Engine(inline=True);engine.tick()
project_service.create('Portable core')
assert today_service.snapshot()['counts']['active_projects']==1
assert learning_service.progress('diagnostic')['state']=='not_started'
assert agenda_service.snapshot()['counts']['events']==0
assert 'PySide6' not in sys.modules and 'windows_integration' not in sys.modules
print(json.dumps({'ok':True}))
'''
            result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parent,
                                  env=dict(os.environ,AUTOMATION_HOME=folder),capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('true',result.stdout)
