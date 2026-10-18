"""One entry point for core checks and full desktop checks; emits a release report."""
import argparse
import json
from pathlib import Path
import sys
import time
import unittest
from app_config import VERSION

CORE=['test_automation','test_desktop','test_weather','test_learning','test_projects','test_today','test_portability','test_location','test_tomorrow','test_performance','test_onboarding','test_release']
GUI=['test_glass','test_ui','test_visual','test_location_ui','test_tomorrow_ui']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--core',action='store_true')
    parser.add_argument('--report');args=parser.parse_args()
    if sys.platform=='win32' and sys.version_info[:2]==(3,12):
        runtime=Path(__file__).resolve().parent/'.ui-runtime'
        if runtime.is_dir():sys.path.insert(0,str(runtime))
    names=CORE if args.core else CORE+GUI;started=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    report={'version':VERSION,'scope':'core' if args.core else 'desktop','tests':result.testsRun,
            'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'seconds':round(time.perf_counter()-started,3),'python':sys.version.split()[0]}
    output=Path(args.report) if args.report else Path(__file__).resolve().parent/'data'/('checks-core.json' if args.core else 'checks-desktop.json')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
