"""Standard-library configuration shared by services, CLI and desktop adapters."""
from datetime import timezone,timedelta
import os
from pathlib import Path
import sys

VERSION='0.9.1'
# Stable storage offset: preserves existing ISO timestamps and deduplication keys.
# Calendar schedules and displayed times use an explicit IANA timezone instead.
LOCAL=timezone(timedelta(hours=5))


def data_home(platform=None,environ=None,home=None):
    platform=platform or sys.platform;env=os.environ if environ is None else environ
    home=Path.home() if home is None else Path(home)
    if env.get('AUTOMATION_HOME'):return Path(env['AUTOMATION_HOME']).expanduser()
    if platform=='win32':
        base=Path(env.get('LOCALAPPDATA') or home)
        modern=base/'Orbita';legacy=base/'UrayAssistant'
        # Existing installations stay on their database; new users get a neutral path.
        if not (modern/'inbox.sqlite').exists() and (legacy/'inbox.sqlite').exists():return legacy
        return modern
    if platform=='darwin':return home/'Library'/'Application Support'/'Orbita'
    return Path(env.get('XDG_DATA_HOME') or home/'.local'/'share')/'orbita'


def program_dir():
    return Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent


def docs_dir():
    if getattr(sys,'frozen',False) and sys.platform=='darwin':
        return program_dir().parent/'Resources'/'docs'
    return program_dir()/'docs'


def timezone_from_settings(settings):
    """Weather follows its selected place; otherwise use the user's local preference."""
    return (settings.get('location_profile') or {}).get('timezone') or settings.get('user_timezone','UTC')
