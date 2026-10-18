"""Repeatable in-process Qt benchmark; isolated database, visible/hidden phases."""
import argparse
import ctypes
import json
import os
import sys
from pathlib import Path
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
parser.add_argument('--animated', action='store_true', help='Paint three representative weather scenes')
parser.add_argument('--source', help='Optional baseline source directory with the same UI contract')
parser.add_argument('--no-motion',action='store_true',help='Measure the saved static weather preference')
args = parser.parse_args()
scratch = tempfile.TemporaryDirectory()
os.environ['AUTOMATION_HOME'] = scratch.name
if args.source:sys.path.insert(0,str(Path(args.source).resolve()))
start = time.perf_counter()
import orbita_glass as ui
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

app = QApplication([])
app.setStyle('Fusion')
app.setStyleSheet(ui.STYLE)
if args.no_motion:ui.store.set_setting('animations',False)
window = ui.Window()
window.show()
app.processEvents()
if args.animated:
    for card,kind in zip(window.periods,('sun','rain','snow')):
        if hasattr(card.art,'set_scene'):card.art.set_scene(kind)
        else:card.art.kind=kind
result = {'startup_seconds': round(time.perf_counter()-start, 3), 'sample_seconds': 8,
          'version':ui.VERSION,'scenario':'static_weather' if args.no_motion else 'animated' if args.animated else 'empty_forecast',
          'cpu_definition': 'percent of one logical CPU; time.process_time / elapsed'}


def memory():
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ['PeakWorkingSetSize','WorkingSetSize',
            'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage']]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb)
    return {'working_set_mb': round(counters.WorkingSetSize/1048576, 1),
            'private_mb': round(counters.PrivateUsage/1048576, 1)}


phase_start = None
cpu_start = None


def begin_visible():
    global phase_start, cpu_start
    phase_start = time.perf_counter(); cpu_start = time.process_time()
    QTimer.singleShot(8000, end_visible)


def end_visible():
    result['visible'] = dict(memory(), cpu_percent=round(100*(time.process_time()-cpu_start)/(time.perf_counter()-phase_start),2))
    result['visible']['animation_phases']=[round(card.art.phase,3) for card in window.periods]
    window.hide()
    QTimer.singleShot(500, begin_hidden)


def begin_hidden():
    global phase_start, cpu_start
    phase_start = time.perf_counter(); cpu_start = time.process_time()
    QTimer.singleShot(8000, finish)


def finish():
    result['hidden'] = dict(memory(), cpu_percent=round(100*(time.process_time()-cpu_start)/(time.perf_counter()-phase_start),2))
    Path(args.output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    if hasattr(window, 'engine'):window.engine.stop()
    if hasattr(window, 'revision_reader'):window.revision_reader.close()
    app.quit()


QTimer.singleShot(500, begin_visible)
app.exec()
