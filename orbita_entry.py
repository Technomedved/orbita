"""Fast CLI publisher path does not load Qt, the scheduler, or Windows adapters."""
import json
from pathlib import Path
import sys


def main():
    if '--publish-file' in sys.argv:
        import argparse
        import desktop_store as store
        parser=argparse.ArgumentParser()
        parser.add_argument('--publish-file',required=True)
        args=parser.parse_args()
        payload=json.loads(Path(args.publish_file).read_text(encoding='utf-8-sig'))
        store.publish(payload['title'],payload['body'],payload.get('category','Задачи'),payload.get('dedupe'))
    else:
        from orbita_glass import main as gui_main
        gui_main()


if __name__=='__main__':main()
