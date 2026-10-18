"""Optional Windows-only adapter. Never imported by the automation core."""
from pathlib import Path
import sys

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'Orbita'


def instance_name(data_path):
    import hashlib
    key=str(Path(data_path).resolve()).casefold().encode('utf-8')
    return 'Local\\OrbitaDesktop-'+hashlib.sha256(key).hexdigest()[:24]


def clear_window_backdrop(handle):
    """Disable whole-HWND effects; Qt owns the antialiased per-pixel glass shape.

    Accent blur processes even alpha-zero corner pixels inside the HWND rectangle.
    Do not replace this with a coarse SetWindowRgn mask: it loses smooth edges.
    This changes only this app's window, never Windows transparency preferences.
    """
    if sys.platform!='win32':return
    import ctypes
    from ctypes import wintypes
    class Accent(ctypes.Structure):
        _fields_=[('state',ctypes.c_int),('flags',ctypes.c_int),('color',ctypes.c_uint),('animation',ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_=[('attribute',ctypes.c_int),('data',ctypes.c_void_p),('size',ctypes.c_size_t)]
    try:
        user32=ctypes.WinDLL('user32',use_last_error=True)
        configure=user32.SetWindowCompositionAttribute
        configure.argtypes=[wintypes.HWND,ctypes.POINTER(Data)];configure.restype=wintypes.BOOL
        accent=Accent(0,0,0,0)  # ACCENT_DISABLED, including old blur on this HWND.
        data=Data(19,ctypes.cast(ctypes.pointer(accent),ctypes.c_void_p),ctypes.sizeof(accent))
        configure(handle,ctypes.byref(data))
    except (AttributeError,OSError):pass
    try:
        dwm=ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype=ctypes.c_long
        none=ctypes.c_int(1)  # DWMSBT_NONE; older Windows may reject this attribute.
        dwm.DwmSetWindowAttribute(handle,38,ctypes.byref(none),ctypes.sizeof(none))
    except (AttributeError,OSError):pass


def autostart_enabled():
    if sys.platform != 'win32': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
            return bool(winreg.QueryValueEx(key,NAME)[0])
    except FileNotFoundError:
        return False


def set_autostart(enabled):
    if sys.platform != 'win32':
        if enabled:raise RuntimeError('Autostart is currently supported on Windows only')
        return
    import winreg
    if getattr(sys,'frozen',False):
        command = f'"{sys.executable}" --background'
    else:
        launcher = Path(__file__).resolve().parent/'launch-assistant.vbs'
        command = f'wscript.exe "{launcher}" --background'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,KEY) as key:
        if enabled:
            winreg.SetValueEx(key,NAME,0,winreg.REG_SZ,command)
        else:
            try:winreg.DeleteValue(key,NAME)
            except FileNotFoundError:pass
