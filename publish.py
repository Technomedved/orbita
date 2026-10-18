"""Publish an automation result without requiring the desktop window to be open."""
import argparse
import json
from pathlib import Path
from desktop_store import publish


def main():
    p = argparse.ArgumentParser(description='Add a notification to the local assistant')
    p.add_argument('--file', required=True, help='UTF-8 JSON: title, body, category, optional dedupe')
    args = p.parse_args()
    data = json.loads(Path(args.file).read_text(encoding='utf-8-sig'))
    result = publish(data['title'], data['body'], data.get('category', 'Задачи'), data.get('dedupe'))
    print('Published' if result else 'Already published')


if __name__ == '__main__':
    main()
